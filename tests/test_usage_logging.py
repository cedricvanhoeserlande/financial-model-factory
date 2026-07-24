from __future__ import annotations

import importlib
import json
import os
import shutil
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp_usage_runtime"


class OpenAIUsageLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)
        self.previous_runtime_dir = os.environ.get("MODEL_FACTORY_RUNTIME_DIR")
        self.previous_openai_model = os.environ.get("OPENAI_MODEL")
        os.environ["MODEL_FACTORY_RUNTIME_DIR"] = str(RUNTIME_DIR)
        os.environ.pop("OPENAI_MODEL", None)
        from backend.app import model_loop

        self.model_loop = importlib.reload(model_loop)

    def tearDown(self) -> None:
        if self.previous_runtime_dir is None:
            os.environ.pop("MODEL_FACTORY_RUNTIME_DIR", None)
        else:
            os.environ["MODEL_FACTORY_RUNTIME_DIR"] = self.previous_runtime_dir
        if self.previous_openai_model is None:
            os.environ.pop("OPENAI_MODEL", None)
        else:
            os.environ["OPENAI_MODEL"] = self.previous_openai_model
        importlib.reload(self.model_loop)
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def test_record_openai_usage_writes_tokens_and_costs(self) -> None:
        self.assertEqual(self.model_loop.DEFAULT_MODEL, "gpt-5.6-terra")
        artifact_dir = RUNTIME_DIR / "artifacts" / "build_test"
        artifact_dir.mkdir(parents=True)
        usage = {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 100},
            "output_tokens": 2000,
            "output_tokens_details": {"reasoning_tokens": 50},
            "total_tokens": 3000,
        }

        report = self.model_loop._record_openai_usage(
            build_run_id="build_test",
            model=self.model_loop.DEFAULT_MODEL,
            status="completed",
            usage=usage,
            artifact_dir=artifact_dir,
        )

        self.assertEqual(report["usage_summary"]["input_tokens"], 1000)
        self.assertEqual(report["usage_summary"]["cached_input_tokens"], 100)
        self.assertEqual(report["usage_summary"]["output_tokens"], 2000)
        self.assertEqual(report["usage_summary"]["total_tokens"], 3000)
        self.assertAlmostEqual(report["cost_summary"]["estimated_cost_usd"], 0.032275)

        artifact_report = json.loads((artifact_dir / "usage_report.json").read_text(encoding="utf-8"))
        ledger_lines = self.model_loop.OPENAI_USAGE_LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(artifact_report["build_run_id"], "build_test")
        self.assertEqual(artifact_report["model"], "gpt-5.6-terra")
        self.assertEqual(len(ledger_lines), 1)
        self.assertEqual(json.loads(ledger_lines[0])["cost_summary"]["estimated_cost_usd"], 0.032275)


if __name__ == "__main__":
    unittest.main()
