from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ModelLoopFacadeTest(unittest.TestCase):
    def test_transitional_core_module_has_been_removed(self) -> None:
        removed_name = "model_loop" + "_core"
        self.assertFalse((ROOT / "backend" / "app" / f"{removed_name}.py").exists())
        for path in (ROOT / "backend" / "app").glob("model_*.py"):
            if path.name == f"{removed_name}.py":
                continue
            self.assertNotIn(removed_name, path.read_text(encoding="utf-8"))

    def test_facade_keeps_public_backend_api_grouped_by_focused_modules(self) -> None:
        from backend.app import model_conversations, model_lifecycle, model_loop, model_runs, model_workspace

        self.assertIs(model_loop.create_model_record, model_lifecycle.create_model_record)
        self.assertIs(model_loop.generate_model_spec_record, model_lifecycle.generate_model_spec_record)
        self.assertIs(model_loop.approve_model_spec_record, model_lifecycle.approve_model_spec_record)
        self.assertIs(model_loop.amend_model_package_record, model_lifecycle.amend_model_package_record)
        self.assertIs(model_loop.build_workspace_payload, model_workspace.build_workspace_payload)
        self.assertIs(model_loop.execute_run, model_runs.execute_run)
        self.assertIs(model_loop.read_input_agent_conversation, model_conversations.read_input_agent_conversation)
        self.assertFalse(hasattr(model_loop, "build_model"))

    def test_facade_preserves_legacy_private_test_hooks(self) -> None:
        from backend.app import model_loop

        self.assertEqual(model_loop.DEFAULT_MODEL, "gpt-5.6-terra")
        self.assertTrue(callable(model_loop._record_openai_usage))


if __name__ == "__main__":
    unittest.main()
