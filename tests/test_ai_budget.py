from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.ai.budget import pre_call_budget_decision


class PreCallBudgetDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_run_limit = os.environ.get("MODEL_FACTORY_MAX_COST_USD_PER_RUN")
        self.previous_day_limit = os.environ.get("MODEL_FACTORY_MAX_COST_USD_PER_DAY_LOCAL")
        self.previous_multiplier = os.environ.get("MODEL_FACTORY_PRE_CALL_COST_SAFETY_MULTIPLIER")
        os.environ["MODEL_FACTORY_MAX_COST_USD_PER_RUN"] = "1"
        os.environ["MODEL_FACTORY_MAX_COST_USD_PER_DAY_LOCAL"] = "5"
        os.environ["MODEL_FACTORY_PRE_CALL_COST_SAFETY_MULTIPLIER"] = "1.25"
        tmp_parent = Path(__file__).resolve().parent / ".tmp"
        tmp_parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=tmp_parent)
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        for key, value in (
            ("MODEL_FACTORY_MAX_COST_USD_PER_RUN", self.previous_run_limit),
            ("MODEL_FACTORY_MAX_COST_USD_PER_DAY_LOCAL", self.previous_day_limit),
            ("MODEL_FACTORY_PRE_CALL_COST_SAFETY_MULTIPLIER", self.previous_multiplier),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp_dir.cleanup()

    def _append(self, path: Path, *, cost: float, run_id: str = "run-1") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "created_utc": "2026-07-17T12:00:00Z",
            "build_run_id": run_id,
            "cost_summary": {"estimated_cost_usd": cost},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def test_allows_when_recorded_spend_plus_conservative_estimate_fits(self) -> None:
        usage_ledger = self.root / "usage.jsonl"
        suite_ledger = self.root / "suite.jsonl"
        self._append(usage_ledger, cost=0.2)
        self._append(suite_ledger, cost=1.0)

        result = pre_call_budget_decision(
            model="gpt-5.6-terra",
            body_json="{}",
            output_tokens=10_000,
            usage_ledger_path=usage_ledger,
            run_id="run-1",
            suite_ledger_path=suite_ledger,
            suite_limit_usd=8.0,
            now=datetime(2026, 7, 17, 13, tzinfo=UTC),
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["checks"]["run"]["recorded_spend_usd"], 0.2)
        self.assertEqual(result["checks"]["suite"]["recorded_spend_usd"], 1.0)
        self.assertGreater(result["conservative_estimated_cost_usd"], result["estimate"]["estimated_pre_call_cost_usd"])

    def test_blocks_before_call_when_any_enabled_scope_would_exceed_limit(self) -> None:
        usage_ledger = self.root / "usage.jsonl"
        suite_ledger = self.root / "suite.jsonl"
        self._append(usage_ledger, cost=0.95)
        self._append(suite_ledger, cost=7.95)

        result = pre_call_budget_decision(
            model="gpt-5.6-terra",
            body_json="large request",
            output_tokens=10_000,
            usage_ledger_path=usage_ledger,
            run_id="run-1",
            suite_ledger_path=suite_ledger,
            suite_limit_usd=8.0,
            now=datetime(2026, 7, 17, 13, tzinfo=UTC),
        )

        self.assertFalse(result["allowed"])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("run", result["blocked_by"])
        self.assertIn("suite", result["blocked_by"])

    def test_ignores_malformed_ledger_lines_and_other_days_or_runs(self) -> None:
        ledger = self.root / "usage.jsonl"
        self._append(ledger, cost=99.0, run_id="another-run")
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write("not-json\n")
            handle.write(json.dumps({"created_utc": "2026-07-16T12:00:00Z", "build_run_id": "another-run", "cost_summary": {"estimated_cost_usd": 99}}) + "\n")

        result = pre_call_budget_decision(
            model="gpt-5.6-terra",
            body_json="{}",
            output_tokens=1,
            usage_ledger_path=ledger,
            run_id="run-1",
            now=datetime(2026, 7, 17, 13, tzinfo=UTC),
        )

        self.assertEqual(result["checks"]["run"]["recorded_spend_usd"], 0.0)
        self.assertEqual(result["checks"]["day"]["recorded_spend_usd"], 99.0)
        self.assertIn("day", result["blocked_by"])


if __name__ == "__main__":
    unittest.main()
