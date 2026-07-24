from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
FACTORY_CONFIG_PATH = ROOT_DIR / "factory_config.json"
DEFAULT_MODEL = "gpt-5.6-terra"
ACTIVE_LLM_ROLES = ("input_agent", "modeler", "review_agent")
STAGE_ROLE_MAP = {
    "modeler_model_spec": "modeler",
    "modeler_model_theory": "modeler",
    "modeler_package_build": "modeler",
    "modeler_package_self_check": "modeler",
    "modeler_package_preflight_repair": "modeler",
    "modeler_package_backend_repair": "modeler",
    "modeler_package_amendment": "modeler",
    "modeler_package_repair": "modeler",
    "presentation_agent_assembly": "presentation_agent",
    "presentation_agent_repair": "presentation_agent",
    "review_agent_audit": "review_agent",
}


@lru_cache(maxsize=1)
def load_factory_config() -> dict[str, Any]:
    if not FACTORY_CONFIG_PATH.exists():
        return {"llm_roles": {}}
    return json.loads(FACTORY_CONFIG_PATH.read_text(encoding="utf-8"))


def role_config(role: str) -> dict[str, Any]:
    config = load_factory_config()
    roles = config.get("llm_roles") if isinstance(config.get("llm_roles"), dict) else {}
    value = roles.get(role)
    return dict(value) if isinstance(value, dict) else {}


def configured_model_for_role(role: str) -> str:
    configured = role_config(role).get("model")
    return str(configured or DEFAULT_MODEL)


def role_enabled(role: str) -> bool:
    return role_config(role).get("enabled", True) is not False


def model_for_role(role: str) -> str:
    scoped_override = os.environ.get(f"MODEL_FACTORY_{role.upper()}_MODEL")
    if scoped_override:
        return scoped_override
    override = os.environ.get("OPENAI_MODEL")
    if override:
        return override
    return configured_model_for_role(role)


def model_for_stage(stage: str) -> str:
    return model_for_role(STAGE_ROLE_MAP.get(stage, "modeler"))


def ai_runtime_config() -> dict[str, Any]:
    config = load_factory_config()
    runtime = config.get("ai_runtime")
    return dict(runtime) if isinstance(runtime, dict) else {}


def ai_runtime_int(key: str, default: int) -> int:
    value = ai_runtime_config().get(key)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def attempt_policy_int(key: str, default: int) -> int:
    config = load_factory_config()
    policy = config.get("attempt_policy")
    value = policy.get(key) if isinstance(policy, dict) else None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def budget_config() -> dict[str, Any]:
    config = load_factory_config()
    budgets = config.get("budgets")
    return dict(budgets) if isinstance(budgets, dict) else {}


def budget_float(key: str, default: float | None = None) -> float | None:
    """Return a positive budget value, honoring a scoped environment override."""
    env_key = f"MODEL_FACTORY_{key.upper()}"
    value = os.environ.get(env_key, budget_config().get(key, default))
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
