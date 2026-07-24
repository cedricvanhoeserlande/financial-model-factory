from __future__ import annotations

import importlib
import os
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp_workflow_runtime"


class WorkflowStateTest(unittest.TestCase):
    def setUp(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)
        self.previous_runtime_dir = os.environ.get("MODEL_FACTORY_RUNTIME_DIR")
        os.environ["MODEL_FACTORY_RUNTIME_DIR"] = str(RUNTIME_DIR)
        from backend.app import model_loop

        self.model_loop = importlib.reload(model_loop)

    def tearDown(self) -> None:
        if self.previous_runtime_dir is None:
            os.environ.pop("MODEL_FACTORY_RUNTIME_DIR", None)
        else:
            os.environ["MODEL_FACTORY_RUNTIME_DIR"] = self.previous_runtime_dir
        importlib.reload(self.model_loop)
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def test_workflow_state_builder_remains_available_without_legacy_build_entrypoint(self) -> None:
        params = self.model_loop.default_input_params()
        input_review = self.model_loop.build_input_review_summary(params)
        state = self.model_loop.build_workflow_state(
            current_stage="review_plan",
            input_review_summary=input_review,
            change_classification={"type": "logic_structure", "source": "test", "reason": "exercise state builder"},
            run_type="rebuild",
            draft_status="draft_generated",
        )

        self.assertEqual(state["current_stage"], "review_plan")
        self.assertEqual(state["change_classification"]["type"], "logic_structure")
        self.assertFalse(state["validation_passed"])
        self.assertFalse(state["stress_passed"])
        self.assertFalse(hasattr(self.model_loop, "build_model"))


if __name__ == "__main__":
    unittest.main()
