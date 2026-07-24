from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.app import model_builder
from backend.output.dashboard_contract import validate_dashboard_spec


def valid_spec() -> dict:
    return {
        "version": "2.0",
        "template_id": "executive_finance",
        "title": "Synthetic company",
        "subtitle": "Five-year outlook",
        "currency": "EUR",
        "display_units": "millions",
        "sections": [{
            "id": "overview",
            "title": "Overview",
            "widgets": [{
                "id": "revenue",
                "block_id": "revenue_trend",
                "component": "chart",
                "visual": "combo",
                "columns": 8,
                "rows": 2,
                "options": {"x": "period", "bars": ["revenue"], "lines": ["margin"]},
            }],
        }],
    }


class DashboardContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.blocks = [{"id": "revenue_trend", "type": "time_series", "data": []}]

    def test_strict_v2_accepts_bound_widgets(self) -> None:
        report = validate_dashboard_spec(valid_spec(), self.blocks)
        self.assertTrue(report["passed"])
        self.assertFalse(report["legacy_auto_layout"])

    def test_legacy_spec_uses_deterministic_auto_layout(self) -> None:
        report = validate_dashboard_spec({"layout": "cards"}, self.blocks)
        self.assertTrue(report["passed"])
        self.assertTrue(report["legacy_auto_layout"])

    def test_missing_block_and_inline_numbers_are_rejected(self) -> None:
        spec = valid_spec()
        widget = spec["sections"][0]["widgets"][0]
        widget["block_id"] = "invented"
        widget["data"] = [123]
        report = validate_dashboard_spec(spec, self.blocks)
        self.assertFalse(report["passed"])
        messages = " ".join(item["message"] for item in report["errors"])
        self.assertIn("existing output block", messages)
        self.assertIn("may not embed output values", messages)

    def test_invalid_grid_span_is_rejected(self) -> None:
        spec = valid_spec()
        spec["sections"][0]["widgets"][0]["columns"] = 13
        self.assertFalse(validate_dashboard_spec(spec, self.blocks)["passed"])

    def test_presentation_agent_can_only_replace_outputs(self) -> None:
        files = [
            {"path": "model/main.py", "content": "from model.assumptions import load_inputs\nfrom model.schedules import run_all\nfrom model.outputs import build_output\ndef run_model(inputs):\n    clean = load_inputs(inputs)\n    return build_output(run_all(clean))\n"},
            {"path": "model/assumptions.py", "content": "def load_inputs(inputs):\n    return inputs\n"},
            {"path": "model/schedules/__init__.py", "content": "def run_all(inputs):\n    return inputs\n"},
            {"path": "model/schedules/core.py", "content": "def build_schedules(inputs): return {}\n"},
            {"path": "model/checks.py", "content": "def run_checks(inputs, schedules, output): return []\n"},
            {"path": "model/outputs.py", "content": "def build_output(schedules):\n    return {}\n"},
        ]
        replacement = "def build_output(schedules):\n    return {'output_version': '2026-05-25'}\n"
        replaced = model_builder._replace_package_file(files, "model/outputs.py", replacement)
        by_path = {item["path"]: item["content"] for item in replaced}
        self.assertEqual(by_path["model/outputs.py"], replacement)
        self.assertEqual(by_path["model/schedules/core.py"], files[3]["content"])
        with self.assertRaisesRegex(RuntimeError, "cannot replace missing"):
            model_builder._replace_package_file(files, "model/finance.py", "x = 1\n")

    def test_review_amendments_route_to_the_correct_agent(self) -> None:
        presentation_report = {"required_amendments": [{"severity": "high", "category": "dashboard_layout"}]}
        model_report = {"required_amendments": [{"severity": "high", "category": "model_logic"}]}
        with patch.object(model_builder, "_perform_presentation_review_repair", return_value={"route": "presentation"}) as presentation, patch.object(
            model_builder, "_perform_modeler_review_repair", return_value={"route": "modeler"}
        ) as modeler:
            self.assertEqual(model_builder._perform_review_repair({}, "", Path("."), presentation_report, [], 1)["route"], "modeler")
            presentation.assert_not_called()
            self.assertEqual(model_builder._perform_review_repair({}, "", Path("."), model_report, [], 1)["route"], "modeler")
            self.assertEqual(modeler.call_count, 2)

    def test_disabled_presentation_agent_never_calls_openai_or_mutates_package(self) -> None:
        files = [{"path": "model/outputs.py", "content": "def build_output(inputs, schedules):\n    return {}\n"}]
        with tempfile.TemporaryDirectory() as temp, patch.object(model_builder, "request_presentation_package") as request:
            returned, report, usage = model_builder._present_replacement_package(
                "Build.", Path(temp), files, {}, {}, []
            )
        self.assertEqual(returned, files)
        self.assertEqual(report["status"], "wip_disabled")
        self.assertFalse(report["blocking"])
        self.assertFalse(usage["openai_called"])
        request.assert_not_called()

    def test_presentation_context_excludes_finance_and_test_amendments(self) -> None:
        report = {
            "attempt": "after_repair_2",
            "summary": "Mixed review.",
            "required_amendments": [
                {"issue_id": "finance", "category": "scenario_behavior", "required_change": "Repair scenarios."},
                {"issue_id": "tests", "category": "test_coverage", "required_change": "Repair probes."},
                {"issue_id": "layout", "category": "dashboard_layout", "required_change": "Repair layout."},
                {"issue_id": "binding", "category": "presentation_data", "required_change": "Repair binding."},
            ],
        }

        scoped = model_builder._presentation_scope_review_report(report)

        self.assertTrue(scoped["presentation_scope_only"])
        self.assertEqual([item["issue_id"] for item in scoped["required_amendments"]], ["layout", "binding"])
        self.assertEqual(scoped["repair_instructions"], ["Repair layout.", "Repair binding."])

    def test_presentation_response_requires_execution_evidence(self) -> None:
        payload = {
            "outputs_py": "def build_output(inputs, schedules):\n    return {}\n",
            "dashboard_spec": valid_spec(),
            "presentation_agent_report": {"passed": True, "summary": "Bindings checked."},
        }
        raw = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload)}]}]}
        with self.assertRaisesRegex(RuntimeError, "Code Interpreter evidence"):
            model_builder._parse_presentation_response(raw)
        raw["output"].insert(0, {"type": "code_interpreter_call", "status": "completed", "code": "print('checked')", "outputs": [{"type": "logs", "logs": "checked"}]})
        outputs_py, dashboard, report = model_builder._parse_presentation_response(raw)
        self.assertIn("build_output", outputs_py)
        self.assertEqual(dashboard["version"], "2.0")
        self.assertTrue(report["passed"])

    def test_presentation_prompt_requires_executable_python_literals(self) -> None:
        prompt = (Path(__file__).resolve().parents[1] / "backend" / "prompts" / "presentation_agent.md").read_text(encoding="utf-8")
        self.assertIn("`True`, `False`, and `None`", prompt)
        self.assertIn("Compile and execute the exact returned source", prompt)
        self.assertIn("assesses only the work you are authorized to perform", prompt)
        self.assertIn("do not fail an otherwise valid presentation", prompt)

    def test_execution_failure_is_reported_before_spec_comparison(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "backend" / "app" / "model_builder.py").read_text(encoding="utf-8")
        function = source.split("def request_presentation_package(", 1)[1].split("def _parse_presentation_response", 1)[0]
        self.assertLess(function.index('if evidence.get("passed") is not True'), function.index("if actual_spec != returned_spec"))

    def test_presentation_retry_context_preserves_exact_output_contract_errors(self) -> None:
        evidence = {
            "passed": False,
            "failure_reasons": ["output_contract_valid"],
            "validation_report": {
                "passed": False,
                "checks": [{
                    "id": "output_contract_valid",
                    "passed": False,
                    "report": {"errors": [{"path": "output_blocks[8].data.x", "message": "Time series x must be a non-empty array."}]},
                }],
            },
        }

        compact = model_builder._compact_mechanical_preflight_for_prompt(evidence)

        failed = compact["validation_report"]["checks"][0]
        self.assertEqual(failed["report"]["errors"][0]["path"], "output_blocks[8].data.x")


if __name__ == "__main__":
    unittest.main()
