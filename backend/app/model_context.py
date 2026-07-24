from __future__ import annotations

import json
import os
import re
import shutil
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib import request

from backend.ai import prompts, usage as openai_usage
from backend.app import model_builder, model_config, model_registry

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RUNTIME_DIR = Path(os.environ.get("MODEL_FACTORY_RUNTIME_DIR", DATA_DIR)).resolve()
ARTIFACTS_DIR = RUNTIME_DIR / "artifacts"
RUN_STATE_DIR = RUNTIME_DIR / "runs"
USAGE_DIR = RUNTIME_DIR / "usage"
LATEST_BUILD_PATH = RUN_STATE_DIR / "latest_build.json"
LATEST_RUN_PATH = RUN_STATE_DIR / "latest_run.json"
OPENAI_USAGE_LEDGER_PATH = USAGE_DIR / ("runtime_openai_usage.jsonl" if RUNTIME_DIR == DATA_DIR.resolve() else "openai_usage.jsonl")
INPUT_AGENT_CONVERSATION = "input_agent_conversation.json"
INPUT_AGENT_SCOPE_HISTORY = "input_agent_scope_history.json"
REVIEW_AGENT_CONVERSATION = "review_agent_conversation.json"

DEFAULT_MODEL = model_config.model_for_role("modeler")
EMPTY_WORKSPACE_PAYLOAD = {
    "workspace": {
        "id": "local_workspace",
        "name": "Model Factory Workspace",
        "company": "",
        "seeded": False,
        "description": "Local workspace for Custom composable models.",
    },
    "scenario": {
        "id": "empty_case",
        "name": "Draft",
        "prompt": "",
        "description": "No generated model selected.",
        "horizon_years": [],
        "assumptions": {},
        "validation_expectations": [],
    },
    "chat_seed": [],
}

WORKFLOW_STAGES = [
    {"id": "define", "label": "Define"},
    {"id": "prepare_inputs", "label": "Prepare Inputs"},
    {"id": "review_plan", "label": "Review Plan"},
    {"id": "build_run_draft", "label": "Build / Run Draft"},
    {"id": "validate", "label": "Validate"},
    {"id": "refine", "label": "Refine"},
]

LOGIC_CHANGE_KEYWORDS = {
    "scope",
    "timeline",
    "structure",
    "logic",
    "module",
    "recipe",
    "calculation",
    "relationship",
    "output",
    "schema",
}
SCOPE_CHECKLIST_QUESTIONS = [
    "Model purpose",
    "Modeled objects",
    "Editable drivers",
    "Required outputs",
]
INITIAL_INPUT_AGENT_MESSAGE = (
    "Describe the model you want to build. If possible, answer by number:\n"
    "1. What purpose should the model support?\n"
    "2. What objects or segments should be modeled separately?\n"
    "3. Which editable drivers should shape the outputs?\n"
    "4. Which outputs, tables, charts, or summaries matter most?"
)
MODEL_SETUP_QUESTION_RE = re.compile(
    r"\b(start\s+(year|month|quarter|period)|reporting\s+currency|currency|periodicity|granularity|forecast\s+granularity|model\s+setup)\b",
    re.IGNORECASE,
)
OPTIONAL_REFINEMENT_RE = re.compile(
    r"\b(sensitiv(?:ity|ities)|stress\s+cases?|scenario\s+cases?|dashboard|charts?|kpis?|which\s+drivers|drivers?\s+to\s+vary|output\s+detail|reporting\s+detail)\b",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_run_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def _ensure_runtime_dirs() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    USAGE_DIR.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))

BUILD_INDEX_PATH = ARTIFACTS_DIR / "build_index.json"

__all__ = [name for name in globals() if not name.startswith("__")]

