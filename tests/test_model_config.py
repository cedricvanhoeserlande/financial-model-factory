from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from backend.app import model_config

ROOT = Path(__file__).resolve().parents[1]


class ModelConfigTest(unittest.TestCase):
    def test_all_configured_agent_roles_use_terra_model(self) -> None:
        config = json.loads((ROOT / "factory_config.json").read_text(encoding="utf-8"))
        role_models = {
            role_name: role_config["model"]
            for role_name, role_config in config["llm_roles"].items()
        }

        self.assertEqual(
            role_models,
            {
                "input_agent": "gpt-5.6-terra",
                "modeler": "gpt-5.6-terra",
                "presentation_agent": "gpt-5.6-terra",
                "review_agent": "gpt-5.6-terra",
            },
        )

    def test_live_ai_stages_resolve_models_from_role_config(self) -> None:
        previous = os.environ.pop("OPENAI_MODEL", None)
        try:
            self.assertEqual(model_config.model_for_role("input_agent"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("modeler_package_build"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("modeler_model_theory"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("modeler_package_self_check"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("modeler_package_preflight_repair"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("presentation_agent_assembly"), "gpt-5.6-terra")
            self.assertEqual(model_config.model_for_stage("review_agent_audit"), "gpt-5.6-terra")
        finally:
            if previous is not None:
                os.environ["OPENAI_MODEL"] = previous

    def test_presentation_agent_is_wip_disabled_and_not_an_active_role(self) -> None:
        self.assertFalse(model_config.role_enabled("presentation_agent"))
        self.assertNotIn("presentation_agent", model_config.ACTIVE_LLM_ROLES)
        self.assertEqual(model_config.role_config("presentation_agent")["status"], "wip_disabled")

    def test_openai_model_env_is_explicit_override(self) -> None:
        previous = os.environ.get("OPENAI_MODEL")
        os.environ["OPENAI_MODEL"] = "gpt-5.5"
        try:
            self.assertEqual(model_config.model_for_stage("modeler_package_build"), "gpt-5.5")
            self.assertEqual(model_config.model_for_role("modeler"), "gpt-5.5")
            self.assertEqual(model_config.configured_model_for_role("modeler"), "gpt-5.6-terra")
        finally:
            if previous is None:
                os.environ.pop("OPENAI_MODEL", None)
            else:
                os.environ["OPENAI_MODEL"] = previous

    def test_role_scoped_model_override_is_selective(self) -> None:
        previous_global = os.environ.get("OPENAI_MODEL")
        previous_review = os.environ.get("MODEL_FACTORY_REVIEW_AGENT_MODEL")
        os.environ["OPENAI_MODEL"] = "gpt-5.6-terra"
        os.environ["MODEL_FACTORY_REVIEW_AGENT_MODEL"] = "gpt-5.6-luna"
        try:
            self.assertEqual(model_config.model_for_stage("review_agent_audit"), "gpt-5.6-luna")
            self.assertEqual(model_config.model_for_stage("modeler_package_amendment"), "gpt-5.6-terra")
        finally:
            if previous_global is None:
                os.environ.pop("OPENAI_MODEL", None)
            else:
                os.environ["OPENAI_MODEL"] = previous_global
            if previous_review is None:
                os.environ.pop("MODEL_FACTORY_REVIEW_AGENT_MODEL", None)
            else:
                os.environ["MODEL_FACTORY_REVIEW_AGENT_MODEL"] = previous_review

    def test_backend_repair_stage_uses_modeler_role_and_configured_cap(self) -> None:
        self.assertEqual(model_config.model_for_stage("modeler_package_backend_repair"), "gpt-5.6-terra")
        self.assertEqual(model_config.attempt_policy_int("backend_check_repair_max_attempts", 0), 3)
        self.assertEqual(model_config.attempt_policy_int("mechanical_preflight_repair_max_attempts", 0), 2)
        self.assertEqual(model_config.attempt_policy_int("review_repair_max_attempts", 0), 3)

    def test_modeler_total_turn_budget_can_reach_all_review_repairs(self) -> None:
        stage_turns = model_config.ai_runtime_int("modeler_workspace_max_turns_per_stage", 0)
        total_turns = model_config.ai_runtime_int("modeler_workspace_max_total_turns", 0)
        repair_rounds = model_config.attempt_policy_int("review_repair_max_attempts", 0)
        self.assertGreaterEqual(total_turns, stage_turns * (repair_rounds + 1) + 1)

    def test_budget_environment_override_is_scoped_and_positive(self) -> None:
        previous = os.environ.get("MODEL_FACTORY_MAX_COST_USD_PER_RUN")
        os.environ["MODEL_FACTORY_MAX_COST_USD_PER_RUN"] = "8.5"
        try:
            self.assertEqual(model_config.budget_float("max_cost_usd_per_run"), 8.5)
            self.assertIsNone(model_config.budget_float("max_cost_usd_per_day_local"))
        finally:
            if previous is None:
                os.environ.pop("MODEL_FACTORY_MAX_COST_USD_PER_RUN", None)
            else:
                os.environ["MODEL_FACTORY_MAX_COST_USD_PER_RUN"] = previous


if __name__ == "__main__":
    unittest.main()
