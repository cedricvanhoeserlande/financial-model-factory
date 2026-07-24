from __future__ import annotations

import http.client
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error as urllib_error

from tests.test_minimal_product_path import (
    stub_base_inputs,
    stub_checks_py,
    stub_model_theory,
    stub_input_schema,
    stub_main_py,
    stub_modeler_self_check,
    stub_package_files,
    stub_scenario_cases,
)
from tests.test_minimal_product_path import stub_model_spec

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp" / "model_builder_validation"


def _write_main(source: str, *, checks_source: str | None = None) -> Path:
    package_dir = RUNTIME_DIR / "model_package"
    for file_record in stub_package_files(main_py=source, checks_py=checks_source or stub_checks_py()):
        path = package_dir / file_record["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file_record["content"].strip() + "\n", encoding="utf-8")
    (package_dir / "model" / "__init__.py").write_text("", encoding="utf-8")
    return package_dir


def _write_package_inputs(package_dir: Path, *, scenarios: list[dict] | None = None, inputs: dict | None = None, schema: dict | None = None) -> None:
    inputs_dir = package_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    (inputs_dir / "base_case.json").write_text(json.dumps(inputs or stub_base_inputs()), encoding="utf-8")
    (inputs_dir / "input_schema.json").write_text(json.dumps(schema or stub_input_schema()), encoding="utf-8")
    (inputs_dir / "scenarios.json").write_text(json.dumps({"scenario_cases": scenarios if scenarios is not None else stub_scenario_cases()}), encoding="utf-8")


def _constant_output_source() -> str:
    return """
def run_model(inputs):
    return {
        "output_version": "2026-05-25",
        "output_blocks": [
            {"id": "primary_result", "type": "kpi", "label": "Primary result", "data": {"value": 100.0}}
        ],
        "dashboard_spec": {},
        "metadata": {"openai_called": False},
    }
"""


def _raw_openai_response(parsed: dict, *, include_code_interpreter: bool = True) -> dict:
    output = []
    if include_code_interpreter:
        output.append(
            {
                "id": "ci_1",
                "type": "code_interpreter_call",
                "status": "completed",
                "code": "print('checked')",
                "outputs": [{"type": "logs", "logs": "checked"}],
            }
        )
    output.append(
        {
            "id": "msg_1",
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps(parsed)}],
        }
    )
    return {"output": output, "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}


def _raw_review_response(parsed: dict) -> dict:
    return {
        "output": [
            {
                "id": "msg_1",
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(parsed)}],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }


class ModelBuilderValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def tearDown(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def test_validate_package_blocks_disallowed_imports(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
import os
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    clean_inputs = load_inputs(inputs)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules)
"""
        )

        validation, _output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertFalse(validation["passed"])
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["package_imports"]["passed"])
        self.assertIn("Blocked import", checks["package_imports"]["error"])

    def test_validate_package_allows_safe_stdlib_transitive_imports(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
from copy import deepcopy
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    copied = deepcopy(inputs)
    clean_inputs = load_inputs(copied)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules)
"""
        )
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertTrue(validation["passed"], validation)

    def test_validate_package_blocks_disallowed_calls(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    open("x.txt", "w")
    clean_inputs = load_inputs(inputs)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules)
"""
        )

        validation, _output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertFalse(validation["passed"])
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["package_imports"]["passed"])
        self.assertIn("Blocked call", checks["package_imports"]["error"])

    def test_validate_package_blocks_hidden_module_state(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
DEFAULT_VALUE = 100
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    clean_inputs = load_inputs(inputs)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules)
"""
        )
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, stub_base_inputs())

        self.assertFalse(validation["passed"])
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["package_imports"]["passed"])
        self.assertIn("hidden module-level state", checks["package_imports"]["error"])

    def test_validate_package_requires_run_checks(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(_constant_output_source(), checks_source="def removed_checks(inputs, outputs):\n    return {}")
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertFalse(validation["passed"])
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["run_checks_callable"]["passed"])

    def test_validate_package_fails_missing_output_blocks(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
def run_model(inputs):
    return {"output_version": "2026-05-25", "dashboard_spec": {}, "metadata": {"openai_called": False}}
"""
        )

        validation, output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertEqual(output["output_version"], "2026-05-25")
        self.assertFalse(validation["passed"])
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["output_contract_valid"]["passed"])
        self.assertIn("output_blocks", {error["path"] for error in checks["output_contract_valid"]["report"]["errors"]})

    def test_validate_package_does_not_run_obsolete_first_input_movement_check(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, stub_base_inputs())

        self.assertTrue(validation["passed"], validation)
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertNotIn("editable_input_changes_output", checks)

    def test_validate_package_fails_hidden_default_fallbacks(self) -> None:
        from backend.app import model_builder

        fallback_source = stub_main_py().replace('inputs["drivers"]["primary_value"]', 'inputs.get("drivers", {}).get("primary_value", 100.0)')
        package_dir = _write_main(fallback_source)
        (package_dir / "model" / "assumptions.py").write_text(
            """
def load_inputs(inputs):
    _ = inputs["periods"]
    drivers = inputs.get("drivers", {})
    _ = drivers.get("primary_value", 100.0)
    _ = drivers["change_rate"]
    _ = inputs["settings"]["opening_value"]
    return inputs
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (package_dir / "model" / "schedules" / "core.py").write_text(
            """
def build_rows(inputs):
    periods = inputs["periods"]
    drivers = inputs.get("drivers", {})
    primary = float(drivers.get("primary_value", 100.0))
    change_rate = float(drivers["change_rate"])
    opening = float(inputs["settings"]["opening_value"])
    rows = []
    running = opening
    for index, period in enumerate(periods):
        if index:
            primary *= 1 + change_rate
        running += primary
        rows.append({"period": period, "primary_value": round(primary, 2), "ending_value": round(running, 2)})
    return rows
""".strip()
            + "\n",
            encoding="utf-8",
        )
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, stub_base_inputs())

        self.assertFalse(validation["passed"], validation)
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertFalse(checks["missing_required_inputs_fail"]["passed"])
        self.assertIn("drivers.primary_value", checks["missing_required_inputs_fail"]["fallback_paths"])

    def test_validate_package_accepts_missing_required_input_failure(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)

        validation, _output = model_builder.validate_package(package_dir, stub_base_inputs())

        self.assertTrue(validation["passed"], validation)
        checks = {check["id"]: check for check in validation["checks"]}
        self.assertTrue(checks["missing_required_inputs_fail"]["passed"])

    def test_validate_package_reports_execution_errors(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
def run_model(inputs):
    raise RuntimeError("boom")
"""
        )

        validation, output = model_builder.validate_package(package_dir, model_builder.default_inputs())

        self.assertEqual(output, {})
        self.assertFalse(validation["passed"])
        self.assertIn("boom", validation["execution_error"])

    def test_validate_package_accepts_generated_stub_contract(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)

        validation, output = model_builder.validate_package(package_dir, stub_base_inputs())

        self.assertTrue(validation["passed"])
        self.assertEqual(output["output_blocks"][0]["id"], "primary_result")

    def test_model_tests_fail_when_declared_check_returns_false(self) -> None:
        from backend.app import model_builder

        checks_source = stub_checks_py().replace('"passed": "primary_result" in block_ids and "model_rows" in block_ids', '"passed": False')
        package_dir = _write_main(stub_main_py(), checks_source=checks_source)
        _write_package_inputs(package_dir)
        model_builder._write_json(RUNTIME_DIR / "model_tests.json", {"status": "ready", "path": "model_tests.json", "model_tests": stub_model_theory()["model_tests"]})
        validation, output = model_builder.validate_package(package_dir, stub_base_inputs())
        report = model_builder.run_model_tests(package_dir, output, {"passed": True})

        self.assertTrue(validation["passed"], validation)
        self.assertFalse(report["passed"], report)
        self.assertFalse({check["id"]: check for check in report["checks"]}["model_tests_all_passed"]["passed"])

    def test_model_test_report_accepts_explicit_not_applicable_without_counting_it_as_passed(self) -> None:
        from backend.app import model_builder

        report = model_builder._validate_model_test_execution_report(
            {
                "checks": [
                    {
                        "id": "base_fixture_calibration",
                        "passed": False,
                        "status": "skipped",
                        "message": "This build-time calibration applies only to the saved Base fixture.",
                        "evidence": {"not_applicable": True, "executed_case": "downside"},
                    }
                ]
            },
            ["base_fixture_calibration"],
            case_id="downside",
        )

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["counts"], {"passed": 0, "failed": 0, "skipped": 1})
        self.assertEqual(report["checks"][0]["status"], "skipped")
        self.assertEqual(report["false_checks"], [])

    def test_model_test_report_rejects_unsubstantiated_skip(self) -> None:
        from backend.app import model_builder

        with self.assertRaisesRegex(RuntimeError, "evidence.not_applicable=true"):
            model_builder._validate_model_test_execution_report(
                {
                    "checks": [
                        {
                            "id": "base_fixture_calibration",
                            "passed": False,
                            "status": "skipped",
                            "message": "Skipped.",
                            "evidence": {"executed_case": "downside"},
                        }
                    ]
                },
                ["base_fixture_calibration"],
                case_id="downside",
            )

    def test_model_test_report_preserves_legacy_boolean_status(self) -> None:
        from backend.app import model_builder

        passed = model_builder._validate_model_test_execution_report(
            {"checks": [{"id": "identity", "passed": True, "message": "Ties.", "evidence": {"residual": 0.0}}]},
            ["identity"],
            case_id="base",
        )
        failed = model_builder._validate_model_test_execution_report(
            {"checks": [{"id": "identity", "passed": False, "message": "Does not tie.", "evidence": {"residual": 1.0}}]},
            ["identity"],
            case_id="base",
        )

        self.assertEqual(passed["checks"][0]["status"], "passed")
        self.assertTrue(passed["passed"])
        self.assertEqual(failed["checks"][0]["status"], "failed")
        self.assertFalse(failed["passed"])

    def test_invalid_optional_review_probe_is_preserved_without_crashing_review(self) -> None:
        from backend.app import model_builder

        result = model_builder._execute_repair_input_probe(
            RUNTIME_DIR,
            {"drivers": {"primary_value": 100.0}},
            {"drivers.primary_value"},
            {"output_blocks": []},
            {
                "input_path": "drivers.primary_value",
                "changed_value": 90.0,
                "output_path": "output_blocks.0.data.missing",
                "expected_behavior": "decrease",
            },
            "missing_output_probe",
        )

        self.assertFalse(result["executed"])
        self.assertFalse(result["probe_valid"])
        self.assertTrue(result["input_path_valid"])
        self.assertFalse(result["output_path_valid"])
        self.assertIn("not in latest output", result["probe_error"])

    def test_model_tests_use_active_rerun_inputs_with_active_output(self) -> None:
        from backend.app import model_builder, package_runtime

        checks_source = stub_checks_py().replace(
            '"passed": "primary_result" in block_ids and "model_rows" in block_ids,',
            '"passed": "primary_result" in block_ids and "model_rows" in block_ids and blocks[1]["data"]["rows"][0]["primary_value"] == inputs["drivers"]["primary_value"],',
        )
        package_dir = _write_main(stub_main_py(), checks_source=checks_source)
        _write_package_inputs(package_dir)
        model_builder._write_json(
            RUNTIME_DIR / "model_tests.json",
            {"status": "ready", "path": "model_tests.json", "model_tests": stub_model_theory()["model_tests"]},
        )
        active = stub_base_inputs()
        active["drivers"]["primary_value"] = 175.0
        output = package_runtime.execute_package(package_dir, active)

        stale = model_builder.run_model_tests(package_dir, output, {"passed": True})
        aligned = model_builder.run_model_tests(package_dir, output, {"passed": True}, active_inputs=active)

        self.assertFalse(stale["passed"])
        self.assertTrue(aligned["passed"], aligned)

    def test_model_tests_execute_cross_scenario_checks_once_with_backend_cases(self) -> None:
        from backend.app import model_builder

        checks_source = stub_checks_py() + """

def run_suite_checks(cases):
    def value(case_id):
        return cases[case_id]["output"]["output_blocks"][1]["data"]["rows"][0]["primary_value"]
    base = value("base")
    downside = value("downside")
    upside = value("upside")
    return {"checks": [{
        "id": "scenario_directionality",
        "passed": downside < base < upside,
        "message": "Backend-executed scenarios move in the declared direction.",
        "evidence": {"base": base, "downside": downside, "upside": upside},
    }]}
"""
        package_dir = _write_main(stub_main_py(), checks_source=checks_source)
        _write_package_inputs(package_dir)
        theory = stub_model_theory()
        theory["model_tests"].append(
            {
                "id": "scenario_directionality",
                "label": "Scenario directionality",
                "test_type": "input_probe",
                "execution_scope": "scenario_suite",
                "purpose": "Compare the backend-executed scenario cases.",
                "logic_description": "Downside is below Base and Upside is above Base.",
                "evidence_expected": "Three observed output values.",
                "repair_guidance": "Correct scenario inputs or model sensitivity.",
            }
        )
        model_builder._write_json(
            RUNTIME_DIR / "model_tests.json",
            {"status": "ready", "path": "model_tests.json", "model_tests": theory["model_tests"]},
        )
        _validation, output = model_builder.validate_package(package_dir, stub_base_inputs())

        report = model_builder.run_model_tests(package_dir, output, {"passed": True})

        self.assertTrue(report["passed"], report)
        self.assertEqual(
            [[check["id"] for check in case["checks"]] for case in report["case_reports"]],
            [["output_blocks_present"], ["output_blocks_present"], ["output_blocks_present"]],
        )
        self.assertEqual([check["id"] for check in report["suite_report"]["checks"]], ["scenario_directionality"])

    def test_model_tests_reject_checks_returned_in_the_wrong_scope(self) -> None:
        from backend.app import model_builder

        checks_source = stub_checks_py().replace(
            ']\n    }',
            ', {"id": "scenario_directionality", "passed": True, "message": "wrong scope", "evidence": {"wrong": True}}]\n    }',
        )
        package_dir = _write_main(stub_main_py(), checks_source=checks_source)
        _write_package_inputs(package_dir)
        theory = stub_model_theory()
        theory["model_tests"].append(
            {
                "id": "scenario_directionality",
                "label": "Scenario directionality",
                "test_type": "input_probe",
                "execution_scope": "scenario_suite",
                "purpose": "Compare scenarios.",
                "logic_description": "Compare executed cases.",
                "evidence_expected": "Observed values.",
                "repair_guidance": "Use run_suite_checks.",
            }
        )
        model_builder._write_json(
            RUNTIME_DIR / "model_tests.json",
            {"status": "ready", "path": "model_tests.json", "model_tests": theory["model_tests"]},
        )
        _validation, output = model_builder.validate_package(package_dir, stub_base_inputs())

        report = model_builder.run_model_tests(package_dir, output, {"passed": True})

        self.assertFalse(report["passed"])
        self.assertIn("wrong execution scope", report["case_reports"][0]["error"])

    def test_model_theory_requires_at_least_one_case_scoped_test(self) -> None:
        from backend.app import model_builder

        theory = stub_model_theory()
        theory["model_tests"][0]["execution_scope"] = "scenario_suite"

        with self.assertRaisesRegex(RuntimeError, "at least one model test"):
            model_builder.parse_model_theory(theory)

    def test_scenarios_reject_base_overrides_as_duplicate_base_ownership(self) -> None:
        from backend.app import model_builder

        scenarios = stub_scenario_cases()
        scenarios[0]["input_overrides"] = {"drivers.primary_value": 100.0}

        with self.assertRaisesRegex(RuntimeError, "Base.*input_overrides"):
            model_builder._parse_scenario_cases(scenarios, source="test scenarios")

    def test_modeler_repair_scope_admits_coherent_python_dependency_changes(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)
        current = {item["path"]: item["content"] for item in stub_package_files()}
        candidate = [
            {"path": path, "content": content + f"\n# candidate {path}\n"}
            for path, content in current.items()
        ]
        scenarios = stub_scenario_cases()
        scenarios[1]["input_overrides"]["drivers.primary_value"] = 70.0
        report = {
            "required_amendments": [
                {"category": "model_logic"},
                {"category": "test_coverage"},
                {"category": "scenario_behavior"},
                {"category": "presentation_data"},
            ]
        }

        files, inputs, schema, admitted_scenarios, scope = model_builder._scope_modeler_review_repair(
            RUNTIME_DIR,
            package_files=candidate,
            base_inputs={"rewritten": True},
            schema={"rewritten": True},
            scenarios=scenarios,
            review_report=report,
            repair_round=1,
        )

        by_path = {item["path"]: item["content"] for item in files}
        self.assertNotEqual(by_path["model/main.py"], current["model/main.py"])
        self.assertNotEqual(by_path["model/checks.py"], current["model/checks.py"])
        self.assertNotEqual(by_path["model/schedules/core.py"], current["model/schedules/core.py"])
        self.assertNotEqual(by_path["model/assumptions.py"], current["model/assumptions.py"])
        self.assertNotEqual(by_path["model/outputs.py"], current["model/outputs.py"])
        self.assertEqual(inputs, stub_base_inputs())
        self.assertEqual(schema, stub_input_schema())
        self.assertEqual(admitted_scenarios[1]["input_overrides"]["drivers.primary_value"], 70.0)
        self.assertTrue(scope["allowed_all_package_files"])
        self.assertEqual(scope["rejected_unowned_file_changes"], [])

    def test_modeler_scope_excludes_presentation_amendments(self) -> None:
        from backend.app import model_builder

        scoped = model_builder._modeler_scope_review_report(
            {
                "summary": "mixed",
                "required_amendments": [
                    {"issue_id": "finance", "category": "model_logic", "required_change": "fix schedule"},
                    {"issue_id": "layout", "category": "presentation_data", "required_change": "fix label"},
                ],
            }
        )

        self.assertEqual([item["issue_id"] for item in scoped["required_amendments"]], ["finance"])
        self.assertEqual(scoped["repair_instructions"], ["fix schedule"])
        self.assertTrue(scoped["modeler_scope_only"])

    def test_model_theory_parser_requires_model_tests(self) -> None:
        from backend.app import model_builder

        plan = stub_model_theory()
        _thesis, _graph, model_tests = model_builder.parse_model_theory(plan)
        self.assertEqual(model_tests[0]["id"], "output_blocks_present")

        bad = {**plan, "model_tests": []}
        with self.assertRaisesRegex(RuntimeError, "model_tests"):
            model_builder.parse_model_theory(bad)

        duplicate = {**plan, "model_tests": [plan["model_tests"][0], plan["model_tests"][0]]}
        with self.assertRaisesRegex(RuntimeError, "duplicated"):
            model_builder.parse_model_theory(duplicate)

        wrong_outputs_key = {
            **plan,
            "model_thesis": {key: value for key, value in plan["model_thesis"].items() if key != "outputs"},
        }
        wrong_outputs_key["model_thesis"]["requested_outputs"] = plan["model_thesis"]["outputs"]
        with self.assertRaisesRegex(RuntimeError, "requested_outputs"):
            model_builder.parse_model_theory(wrong_outputs_key)

    def test_openai_build_parser_rejects_array_input_paths(self) -> None:
        from backend.app import model_builder

        schema = stub_input_schema()
        schema["fields"][0] = {**schema["fields"][0], "path": ["drivers", "primary_value"]}
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": schema,
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "string path"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_missing_input_schema_fields(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": {"type": "object", "fields": []},
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "non-empty fields array"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_input_paths_missing_from_base_inputs(self) -> None:
        from backend.app import model_builder

        schema = stub_input_schema()
        schema["fields"][0] = {**schema["fields"][0], "path": "missing.primary_value"}
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": schema,
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "does not exist in base_inputs"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_missing_editable_flag(self) -> None:
        from backend.app import model_builder

        schema = stub_input_schema()
        del schema["fields"][0]["editable"]
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": schema,
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "editable"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_missing_base_scalar_path_in_schema(self) -> None:
        from backend.app import model_builder

        schema = stub_input_schema()
        schema["fields"] = schema["fields"][1:]
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": schema,
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "missing scalar base_inputs paths"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_mechanical_stress_ignores_non_editable_numeric_fields(self) -> None:
        from backend.app import model_builder

        schema = stub_input_schema()
        schema["fields"][2] = {**schema["fields"][2], "editable": False}
        scenarios = stub_scenario_cases()
        scenarios[1]["input_overrides"].pop("settings.opening_value")
        scenarios[2]["input_overrides"].pop("settings.opening_value")
        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir, schema=schema, scenarios=scenarios)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertTrue(report["passed"], report)
        coverage = {check["id"]: check for check in report["checks"]}["scenario_covers_editable_inputs"]
        self.assertNotIn("settings.opening_value", coverage["editable_paths"])

    def test_openai_build_parser_rejects_malformed_scenario_cases(self) -> None:
        from backend.app import model_builder

        scenarios = stub_scenario_cases()
        scenarios[1] = {**scenarios[1], "id": "Downside"}
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": scenarios,
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "scenario_cases is invalid"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_draft_parser_admits_syntax_error_for_modeler_self_check(self) -> None:
        from backend.app import model_builder

        package_files = stub_package_files()
        for item in package_files:
            if item["path"] == "model/checks.py":
                item["content"] = "def run_checks(inputs, outputs):\n    return {'checks': [)}"
        parsed = {
            "package_files": package_files,
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
        }

        admitted, _inputs, _schema, _scenarios = model_builder._parse_openai_draft_package_response(
            _raw_openai_response(parsed, include_code_interpreter=False)
        )

        self.assertIn("[)}", next(item["content"] for item in admitted if item["path"] == "model/checks.py"))
        with self.assertRaisesRegex(RuntimeError, "model/checks.py has invalid syntax"):
            model_builder._validate_package_files(admitted, source="final package")

    def test_self_check_retries_exact_mechanical_error_without_using_review_round(self) -> None:
        from backend.app import model_builder

        invalid_files = stub_package_files()
        for item in invalid_files:
            if item["path"] == "model/checks.py":
                item["content"] = "def run_checks(inputs, outputs):\n    return {'checks': [)}"
        invalid = {
            "package_files": invalid_files,
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }
        valid = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }
        bodies: list[dict] = []

        def fake_post(_api_key: str, body: dict) -> dict:
            bodies.append(body)
            return _raw_openai_response(invalid if len(bodies) == 1 else valid)

        root = RUNTIME_DIR / "artifacts" / "model_versions" / "model_1" / "version_1"
        root.mkdir(parents=True)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(
            model_builder, "_post_openai", side_effect=fake_post
        ), patch.object(model_builder, "mechanical_preflight_repair_max_attempts", return_value=1):
            package_files, _inputs, _schema, _scenarios, _self_check, usage = model_builder.request_self_checked_package(
                "Build it.",
                root,
                approved_spec={},
                model_thesis={},
                equation_graph={},
                model_tests=[],
                draft_package={
                    "package_files": invalid_files,
                    "base_inputs": stub_base_inputs(),
                    "input_schema": stub_input_schema(),
                    "scenario_cases": stub_scenario_cases(),
                },
                initial_preflight={"passed": False, "error": "model/checks.py has invalid syntax"},
            )

        self.assertEqual(len(bodies), 2)
        repair_context = json.loads(bodies[1]["input"][1]["content"])
        self.assertIn("model/checks.py has invalid syntax", repair_context["mechanical_preflight"]["error"])
        self.assertEqual(repair_context["mechanical_repairs_used"], 1)
        self.assertEqual(usage["mechanical_preflight_repairs_used"], 1)
        self.assertEqual(len(usage["mechanical_preflight_usage"]), 2)
        self.assertEqual({item["path"] for item in package_files}, {item["path"] for item in stub_package_files()})
        history = json.loads((root / "mechanical_preflight_history.json").read_text(encoding="utf-8"))
        self.assertTrue(history["passed"])
        self.assertEqual(history["repairs_used"], 1)

    def test_review_repair_uses_authoritative_workspace_transport(self) -> None:
        from backend.app import model_builder
        workspace_result = (
            stub_package_files(),
            stub_base_inputs(),
            stub_input_schema(),
            stub_scenario_cases(),
            {**stub_modeler_self_check(), "transport": "workspace_tool_loop"},
            {"stage": "modeler_package_repair", "transport": "workspace_tool_loop"},
        )
        root = RUNTIME_DIR / "artifacts" / "model_versions" / "model_1" / "version_review_repair"
        root.mkdir(parents=True)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch.object(
            model_builder, "_request_workspace_package", return_value=workspace_result
        ) as workspace_call, patch.object(
            model_builder, "_scope_modeler_review_repair", return_value=(*workspace_result[:4], {"admitted_file_changes": []})
        ), patch.object(
            model_builder,
            "_present_replacement_package",
            return_value=(stub_package_files(), {"passed": True}, {"stage": "presentation_agent"}),
        ):
            package_files, *_rest, usage = model_builder.request_repaired_package(
                "Original request.",
                root,
                {
                    "required_amendments": [
                        {
                            "issue_id": "repair_output_contract",
                            "severity": "medium",
                            "category": "outputs",
                            "required_change": "Expose the required output.",
                        }
                    ]
                },
                repair_round=3,
                review_history=[],
            )

        self.assertEqual({item["path"] for item in package_files}, {item["path"] for item in stub_package_files()})
        self.assertTrue(workspace_call.call_args.kwargs["seed_package"])
        self.assertEqual(workspace_call.call_args.kwargs["attempt"], "repair_3")
        self.assertIn("repair_output_contract", workspace_call.call_args.args[0])
        self.assertNotEqual(workspace_call.call_args.args[0], "Original request.")
        self.assertEqual(workspace_call.call_args.kwargs["extra_context"]["original_user_prompt"], "Original request.")
        self.assertEqual(workspace_call.call_args.kwargs["extra_context"]["active_task"], "review_required_amendments")
        self.assertEqual(usage["transport"], "workspace_tool_loop")

    def test_openai_build_parser_requires_modeler_self_check(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
        }

        with self.assertRaisesRegex(RuntimeError, "modeler_self_check"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_missing_required_package_file(self) -> None:
        from backend.app import model_builder

        package_files = [item for item in stub_package_files() if item["path"] != "model/checks.py"]
        parsed = {
            "package_files": package_files,
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "missing required package files"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_rejects_unexpected_package_path(self) -> None:
        from backend.app import model_builder

        package_files = stub_package_files() + [{"path": "model/helpers/extra.py", "content": "def helper():\n    return 1"}]
        parsed = {
            "package_files": package_files,
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "outside the allowed generated package tree"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_requires_code_interpreter_evidence(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "Code Interpreter self-check evidence"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed, include_code_interpreter=False))

    def test_openai_build_parser_requires_passing_self_check(self) -> None:
        from backend.app import model_builder

        failed = stub_modeler_self_check()
        failed["passed"] = False
        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": failed,
        }

        with self.assertRaisesRegex(RuntimeError, "self-check did not pass"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_openai_build_parser_attaches_code_interpreter_evidence(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": {"passed": True, "summary": "ok", "checks": [], "issues": []},
        }

        package_files, _inputs, _schema, scenarios, self_check = model_builder._parse_openai_build_response(_raw_openai_response(parsed))

        self.assertEqual({item["path"] for item in package_files}, {item["path"] for item in stub_package_files()})
        self.assertEqual({case["id"] for case in scenarios}, {"base", "downside", "upside"})
        self.assertTrue(self_check["code_interpreter_required"])
        self.assertEqual(self_check["code_interpreter_call_count"], 1)
        self.assertEqual(self_check["code_interpreter_calls"][0]["outputs"][0]["logs"], "checked")

    def test_modeler_prompts_require_spec_to_output_self_check(self) -> None:
        prompt_dir = ROOT / "backend" / "prompts"
        for name in ("model_package_self_check.md", "model_package_repair.md", "model_package_amend.md"):
            with self.subTest(prompt=name):
                text = (prompt_dir / name).read_text(encoding="utf-8")
                self.assertIn("model_spec", text)
                self.assertIn("run_model(base_inputs)", text)
                self.assertIn("dashboard_spec", text)
                self.assertIn("output_data_contract_valid", text)
                self.assertIn("model_spec_output_alignment", text)
                self.assertIn("dashboard_spec_present", text)
                self.assertIn("json_shapes_strict", text)
        amend_text = (prompt_dir / "model_package_amend.md").read_text(encoding="utf-8")
        self.assertIn("scenario_design", amend_text)
        self.assertIn("not a partial diff", amend_text)

    def test_modeler_prompts_require_scenarios_to_cover_all_editable_inputs(self) -> None:
        prompt_dir = ROOT / "backend" / "prompts"
        for name in ("model_package_build.md", "model_package_self_check.md", "model_package_repair.md", "model_package_amend.md"):
            with self.subTest(prompt=name):
                text = (prompt_dir / name).read_text(encoding="utf-8")
                self.assertIn("collectively override every editable numeric", text)
                self.assertIn("scenario_covers_editable_inputs", text)
                self.assertIn("exactly base/downside/upside objects", text)
        review_text = (prompt_dir / "model_package_review.md").read_text(encoding="utf-8")
        self.assertIn("scenario_covers_editable_inputs", review_text)
        self.assertIn("wrong JSON list/object/string shapes", review_text)

    def test_prompts_require_explicit_inputs_and_no_fallback_defaults(self) -> None:
        prompt_dir = ROOT / "backend" / "prompts"
        for name in ("model_package_build.md", "model_package_self_check.md", "model_package_repair.md", "model_package_backend_repair.md", "model_package_amend.md"):
            with self.subTest(prompt=name):
                text = (prompt_dir / name).read_text(encoding="utf-8")
                self.assertIn("every scalar", text)
                self.assertIn("explicit editable", text)
                self.assertIn("fallback", text)
                self.assertIn("fail clearly", text)
        review_text = (prompt_dir / "model_package_review.md").read_text(encoding="utf-8")
        self.assertIn("meaningful audit evidence", review_text)
        self.assertIn("fallback/default assumptions", review_text)

    def test_openai_amendment_parser_requires_model_spec_and_change_summary(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "scenario_cases": stub_scenario_cases(),
            "modeler_self_check": stub_modeler_self_check(),
            "change_summary": {"summary": "Changed output table."},
        }

        with self.assertRaisesRegex(RuntimeError, "model_spec"):
            model_builder._parse_openai_amendment_response(_raw_openai_response(parsed))

        parsed["model_spec"] = stub_model_spec()
        parsed["change_summary"] = {}
        with self.assertRaisesRegex(RuntimeError, "change_summary"):
            model_builder._parse_openai_amendment_response(_raw_openai_response(parsed))

    def test_openai_build_parser_requires_scenario_cases(self) -> None:
        from backend.app import model_builder

        parsed = {
            "package_files": stub_package_files(),
            "base_inputs": stub_base_inputs(),
            "input_schema": stub_input_schema(),
            "modeler_self_check": stub_modeler_self_check(),
        }

        with self.assertRaisesRegex(RuntimeError, "scenario_cases"):
            model_builder._parse_openai_build_response(_raw_openai_response(parsed))

    def test_model_spec_parser_accepts_valid_structured_spec(self) -> None:
        from backend.app import model_spec

        parsed = model_spec.parse_model_spec(stub_model_spec())

        self.assertTrue(parsed["build_readiness"]["ready_to_build"])
        self.assertEqual(parsed["unresolved_questions"], [])

    def test_model_spec_parser_rejects_missing_required_fields(self) -> None:
        from backend.app import model_spec

        bad = stub_model_spec()
        bad.pop("outputs")

        with self.assertRaisesRegex(RuntimeError, "missing required fields"):
            model_spec.parse_model_spec(bad)

    def test_model_spec_parser_rejects_object_dashboard_intent(self) -> None:
        from backend.app import model_spec

        bad = stub_model_spec()
        bad["dashboard_intent"] = {"id": "summary", "label": "Summary"}

        with self.assertRaisesRegex(RuntimeError, "dashboard_intent must be a list"):
            model_spec.parse_model_spec(bad)

    def test_model_spec_approval_rejects_unresolved_blockers(self) -> None:
        from backend.app import model_spec

        spec = stub_model_spec()
        spec["unresolved_questions"] = ["Clarify required output."]
        parsed = model_spec.parse_model_spec(spec)
        self.assertIn("Clarify required output.", model_spec._spec_blockers(parsed))

    def test_pre_publish_summary_is_empty_before_review_readiness(self) -> None:
        from backend.app import model_builder

        summary = model_builder._pre_publish_summary(
            status="draft",
            spec_payload={},
            validation_report={},
            mechanical_report={},
            self_check={},
            review_report={},
            review_evidence={},
            repair_plan={},
            latest_output={},
        )

        self.assertEqual(summary, {})

    def test_review_parser_rejects_malformed_output(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": "yes",
            "repair_required": False,
            "summary": "bad",
            "findings": [],
            "required_amendments": [],
            "repair_instructions": [],
            "human_questions": [],
            "failure_reasons": [],
        }

        with self.assertRaisesRegex(RuntimeError, "approved and repair_required"):
            model_builder._parse_review_response(_raw_review_response(parsed))

    def test_review_parser_accepts_structured_findings(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": False,
            "repair_required": True,
            "summary": "Needs changes.",
            "findings": [
                {
                    "severity": "high",
                    "area": "outputs",
                    "claim_tested": "The package should expose useful outputs for the requested model.",
                    "symptom": "The output surface is too thin.",
                    "root_cause": "The model did not translate requested outputs into output blocks.",
                    "message": "Missing useful output.",
                    "evidence": {"artifact": "model_package/outputs/output.json", "output_block_id": "primary_result", "observed": "Only one KPI is present."},
                    "repair_instruction": "Add useful output rows.",
                    "requires_human_decision": False,
                }
            ],
            "required_amendments": [
                {
                    "issue_id": "missing_useful_output",
                    "severity": "high",
                    "category": "output_definition",
                    "artifacts": ["model_package/outputs/output.json"],
                    "observed": "Only one KPI is present.",
                    "required_change": "Add useful output rows.",
                    "acceptance_criteria": ["Requested output rows are present and correctly defined."],
                    "human_decision_required": False,
                }
            ],
            "repair_instructions": ["Add useful output rows."],
            "human_questions": [],
            "failure_reasons": ["Missing useful output."],
        }

        report = model_builder._parse_review_response(_raw_review_response(parsed))

        self.assertFalse(report["approved"])
        self.assertTrue(report["repair_required"])
        self.assertEqual(report["findings"][0]["area"], "outputs")
        self.assertEqual(report["required_amendments"][0]["issue_id"], "missing_useful_output")

    def test_review_parser_accepts_multiple_canonical_finding_citations(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": False,
            "repair_required": True,
            "summary": "Tests do not exercise the claimed branch.",
            "findings": [{
                "severity": "medium",
                "area": "model-test coverage",
                "claim_tested": "Timing tests exercise changed inputs.",
                "symptom": "The passing report contains no zero-lag rows.",
                "root_cause": "The check inspects one unchanged output.",
                "message": "Input-driven coverage is missing.",
                "evidence": {
                    "artifacts": ["model_package/model/checks.py", "model_package/reports/model_tests_report.json"],
                    "observed": "zero_lag_row_count is zero in a passing check.",
                },
                "repair_instruction": "Execute controlled changed-input cases.",
                "requires_human_decision": False,
            }],
            "required_amendments": [{
                "issue_id": "timing_test_coverage",
                "severity": "medium",
                "category": "test_coverage",
                "artifacts": ["model_package/model/checks.py", "model_package/reports/model_tests_report.json"],
                "observed": "The checks are not input-driven.",
                "required_change": "Execute controlled input cases.",
                "acceptance_criteria": ["Zero-day and positive-day cases execute and pass."],
                "human_decision_required": False,
            }],
            "repair_instructions": ["Repair test coverage."],
            "human_questions": [],
            "failure_reasons": ["Test coverage is unsupported."],
        }

        report = model_builder._parse_review_response(_raw_review_response(parsed))

        self.assertEqual(report["findings"][0]["evidence"]["artifact"], "model_package/model/checks.py")
        self.assertEqual(
            report["findings"][0]["evidence"]["artifacts"],
            ["model_package/model/checks.py", "model_package/reports/model_tests_report.json"],
        )

    def test_review_parser_rejects_repair_without_targets(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": False,
            "repair_required": True,
            "summary": "Needs changes.",
            "findings": [
                {
                    "severity": "high",
                    "area": "outputs",
                    "claim_tested": "The package should expose useful outputs.",
                    "symptom": "Missing output rows.",
                    "root_cause": "The output block set is incomplete.",
                    "message": "Missing useful output.",
                    "evidence": {"artifact": "model_package/outputs/output.json", "note": "Only one KPI is present."},
                    "repair_instruction": "Add useful output rows.",
                    "requires_human_decision": False,
                }
            ],
            "required_amendments": [],
            "repair_instructions": ["Add useful output rows."],
            "human_questions": [],
            "failure_reasons": ["Missing useful output."],
        }

        with self.assertRaisesRegex(RuntimeError, "requires at least one non-human"):
            model_builder._parse_review_response(_raw_review_response(parsed))

    def test_review_parser_rejects_malformed_repair_target(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": False,
            "repair_required": True,
            "summary": "Needs changes.",
            "findings": [
                {
                    "severity": "high",
                    "area": "outputs",
                    "claim_tested": "The package should expose useful outputs.",
                    "symptom": "Missing output rows.",
                    "root_cause": "The output block set is incomplete.",
                    "message": "Missing useful output.",
                    "evidence": {"artifact": "model_package/outputs/output.json", "note": "Only one KPI is present."},
                    "repair_instruction": "Add useful output rows.",
                    "requires_human_decision": False,
                }
            ],
            "required_amendments": [
                {
                    "issue_id": "Bad Id",
                    "severity": "high",
                    "category": "model_logic",
                    "artifacts": ["model_package/model/main.py"],
                    "verification_probe": {"input_path": "drivers.primary_value", "changed_value": 80, "output_path": "output_blocks.primary_result.data.value", "expected_behavior": "decrease"},
                    "observed": "Output does not change.",
                    "required_change": "Connect the driver to the output.",
                    "acceptance_criteria": ["The output decreases under the probe."],
                    "human_decision_required": False,
                }
            ],
            "repair_instructions": ["Repair the package."],
            "human_questions": [],
            "failure_reasons": ["Missing useful output."],
        }

        with self.assertRaisesRegex(RuntimeError, "issue_id"):
            model_builder._parse_review_response(_raw_review_response(parsed))

    def test_review_parser_rejects_findings_without_evidence_fields(self) -> None:
        from backend.app import model_builder

        parsed = {
            "approved": False,
            "repair_required": True,
            "summary": "Needs changes.",
            "findings": [{"severity": "high", "area": "outputs", "message": "Missing useful output.", "evidence": "latest output"}],
            "required_amendments": [
                {
                    "issue_id": "missing_useful_output",
                    "severity": "high",
                    "category": "output_definition",
                    "artifacts": ["model_package/outputs/output.json"],
                    "observed": "Only one KPI is present.",
                    "required_change": "Add useful output rows.",
                    "acceptance_criteria": ["Requested output rows are present."],
                    "human_decision_required": False,
                }
            ],
            "repair_instructions": ["Add useful output rows."],
            "human_questions": [],
            "failure_reasons": ["Missing useful output."],
        }

        with self.assertRaisesRegex(RuntimeError, "missing required fields"):
            model_builder._parse_review_response(_raw_review_response(parsed))

    def test_review_function_tools_validate_args_and_unknown_tools(self) -> None:
        from backend.app import model_builder

        extra_arg = model_builder._execute_review_function_call(
            RUNTIME_DIR,
            {"call_id": "call_1", "name": "validate_input_path", "arguments": json.dumps({"input_path": "drivers.primary_value", "extra": True})},
            stage="review_agent_audit",
            attempt="unit",
            round_index=0,
        )
        unknown = model_builder._execute_review_function_call(
            RUNTIME_DIR,
            {"call_id": "call_2", "name": "unknown_tool", "arguments": "{}"},
            stage="review_agent_audit",
            attempt="unit",
            round_index=0,
        )

        self.assertFalse(extra_arg["ok"])
        self.assertIn("unexpected args", extra_arg["error"])
        self.assertFalse(unknown["ok"])
        self.assertIn("Unknown function tool", unknown["error"])

    def test_review_artifact_reader_is_canonical_bounded_and_text_only(self) -> None:
        from backend.app import model_builder

        root = RUNTIME_DIR / "artifact_reader"
        artifact = root / "model_package" / "model" / "main.py"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("def run_model(inputs):\n    return inputs\n", encoding="utf-8")
        result = model_builder._read_review_artifact(root, "model_package/model/main.py")

        self.assertTrue(result["ok"])
        self.assertIn("run_model", result["content"])
        with self.assertRaisesRegex(RuntimeError, "escapes"):
            model_builder._read_review_artifact(root, "../outside.txt")
        artifact.write_bytes(b"\x00binary")
        with self.assertRaisesRegex(RuntimeError, "binary"):
            model_builder._read_review_artifact(root, "model_package/model/main.py")
        artifact.write_bytes(b"x" * (model_builder.REVIEW_ARTIFACT_READ_MAX_BYTES + 1))
        with self.assertRaisesRegex(RuntimeError, "review limit"):
            model_builder._read_review_artifact(root, "model_package/model/main.py")

    def test_structural_review_evidence_uses_receipts_not_keywords(self) -> None:
        from backend.app import model_builder

        root = RUNTIME_DIR / "structural_receipts"
        for relative in ("model_package/model/checks.py", "model_package/reports/model_tests_report.json"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}" if path.suffix == ".json" else "def run_checks(inputs, outputs): return {}", encoding="utf-8")
        report = {
            "findings": [{"evidence": {"artifact": "model_package/model/checks.py"}}],
            "required_amendments": [{"artifacts": ["model_package/model/checks.py"]}],
        }
        code_calls = [{"code": "values = [1, 2, 3]\nprint(sum(values), max(values), min(values))\n# independent numerical challenge of the supplied model", "outputs": [{"logs": "6 3 1"}]}]
        function_calls = [
            {"tool_name": "list_package_artifacts", "ok": True, "result": {"ok": True}},
            {"tool_name": "read_package_artifact", "ok": True, "result": {"artifact_path": "model_package/model/checks.py"}},
            {"tool_name": "read_package_artifact", "ok": True, "result": {"artifact_path": "model_package/reports/model_tests_report.json"}},
            {"tool_name": "execute_model_test", "ok": True, "result": {"ok": True}},
        ]

        evidence = model_builder._review_structural_evidence_quality(root, report, code_calls, function_calls)

        self.assertTrue(evidence["passed"], evidence)
        self.assertNotIn("matched_terms", evidence)
        report["findings"][0]["evidence"]["artifact"] = "model_package/model/missing.py"
        evidence = model_builder._review_structural_evidence_quality(root, report, code_calls, function_calls)
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["unresolved_citations"], ["model_package/model/missing.py"])

    def test_replays_terra_working_capital_review_with_structural_receipts(self) -> None:
        from backend.app import model_builder

        fixture = json.loads((ROOT / "tests" / "fixtures" / "terra_working_capital_review_replay.json").read_text(encoding="utf-8"))
        root = RUNTIME_DIR / "terra_review_replay"
        for relative, content in (
            ("model_package/model/checks.py", "def run_checks(inputs, outputs): return {}"),
            ("model_package/reports/model_tests_report.json", "{}"),
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        evidence = model_builder._review_structural_evidence_quality(
            root,
            fixture["review_report"],
            fixture["code_interpreter_calls"],
            fixture["function_tool_calls"],
        )

        self.assertTrue(evidence["passed"], evidence)
        self.assertIn("execute_input_probe", evidence["execution_tools"])
        self.assertEqual(evidence["cited_artifacts"], ["model_package/model/checks.py"])

    def test_shadow_review_architecture_is_removed(self) -> None:
        from backend.app import model_builder, model_config

        self.assertNotIn("review_quality_agent", model_config.ACTIVE_LLM_ROLES)
        self.assertNotIn("review_evidence_judge", model_config.STAGE_ROLE_MAP)
        self.assertFalse(hasattr(model_builder, "_run_review_evidence_ab_shadow"))
        self.assertFalse(hasattr(model_builder, "_semantic_judge_grounding"))
        self.assertFalse((ROOT / "tests" / "live_decision_gate" / "hidden_rubric.py").exists())
        self.assertFalse((ROOT / "tests" / "live_decision_gate" / "hidden_acceptance_rubric.json").exists())

    def test_function_tool_loop_carries_all_response_items_for_stateless_reasoning(self) -> None:
        from backend.app import model_builder

        carried = model_builder._function_call_input_items(
            [
                {"id": "rs_1", "type": "reasoning", "summary": []},
                {"id": "ci_1", "type": "code_interpreter_call", "code": "print('x')"},
                {"id": "fc_1", "type": "function_call", "name": "validate_input_path", "call_id": "call_1", "arguments": "{}"},
            ]
        )

        self.assertEqual(len(carried), 3)
        self.assertEqual([item["type"] for item in carried], ["reasoning", "code_interpreter_call", "function_call"])

    def test_function_tool_loop_forces_structured_verdict_after_evidence(self) -> None:
        from backend.app import model_builder

        root = RUNTIME_DIR / "version"
        root.mkdir(parents=True, exist_ok=True)
        first = {
            "output": [
                {"id": "rs_1", "type": "reasoning", "encrypted_content": "opaque", "summary": []},
                {
                    "id": "ci_1",
                    "type": "code_interpreter_call",
                    "status": "completed",
                    "code": "print('independent execution evidence that is deliberately nontrivial and long enough for admission')",
                    "outputs": [{"type": "logs", "logs": "passed"}],
                },
                {"id": "fc_1", "type": "function_call", "name": "list_package_artifacts", "call_id": "call_1", "arguments": "{}"},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        }
        verdict = {
            "output": [{"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
            "usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
        }
        body = {
            "model": "gpt-5.6-terra",
            "input": [{"role": "user", "content": "review"}],
            "tools": [{"type": "function", "name": "list_package_artifacts"}],
            "tool_choice": "required",
            "text": {"format": {"type": "json_schema", "name": "review", "schema": {"type": "object"}}},
            "store": False,
        }
        complete = {
            "checks": {
                "code_interpreter_nontrivial": True,
                "artifact_listing_succeeded": True,
                "logic_or_spec_read_succeeded": True,
                "output_or_report_read_succeeded": True,
                "executable_probe_or_test_succeeded": True,
            }
        }
        record = {"tool_name": "list_package_artifacts", "ok": True, "result": {"artifacts": []}}
        with patch.object(model_builder, "_post_openai", side_effect=[first, verdict]) as post_call, patch.object(
            model_builder, "_execute_review_function_call", return_value=record
        ), patch.object(model_builder, "_review_structural_evidence_quality", return_value=complete), patch.object(
            model_builder, "_write_agent_tool_calls_report"
        ):
            raw = model_builder._post_openai_with_function_tools(
                "test-key", body, root=root, stage="review_agent_audit", attempt="initial"
            )

        self.assertEqual(post_call.call_count, 2)
        final_body = post_call.call_args_list[1].args[1]
        self.assertEqual(final_body["tool_choice"], "none")
        self.assertTrue(any(item.get("type") == "reasoning" for item in final_body["input"] if isinstance(item, dict)))
        self.assertIn("Evidence collection is complete", final_body["input"][-1]["content"])
        self.assertEqual(raw["usage"]["total_tokens"], 35)
        self.assertEqual(model_builder._extract_response_text(raw), "{}")

    def test_review_function_tool_executes_input_probe(self) -> None:
        from backend.app import model_builder, package_runtime

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)
        output = package_runtime.execute_package(package_dir, stub_base_inputs())
        outputs_dir = package_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        (outputs_dir / "output.json").write_text(json.dumps(output), encoding="utf-8")

        record = model_builder._execute_review_function_call(
            RUNTIME_DIR,
            {
                "call_id": "call_probe",
                "name": "execute_input_probe",
                "arguments": json.dumps(
                    {
                        "issue_id": "primary_result_probe",
                        "input_path": "drivers.primary_value",
                        "changed_value": 80.0,
                        "output_path": "output_blocks.primary_result.data.value",
                        "expected_behavior": "decrease",
                    }
                ),
            },
            stage="review_agent_audit",
            attempt="unit",
            round_index=0,
        )

        self.assertTrue(record["ok"], record)
        self.assertTrue(record["result"]["executed"])
        self.assertTrue(record["result"]["expected_behavior_met"])

    def test_review_request_uses_function_tool_loop(self) -> None:
        from backend.app import model_builder

        root = RUNTIME_DIR / "version"
        root.mkdir(parents=True, exist_ok=True)
        model_builder._write_json(root / "version_manifest.json", {"status": "draft"})
        report_payload = {
            "approved": True,
            "repair_required": False,
            "summary": "Approved after audit.",
            "findings": [],
            "required_amendments": [],
            "repair_instructions": [],
            "human_questions": [],
            "failure_reasons": [],
        }
        raw = {
            "output": [
                {
                    "id": "ci_1",
                    "type": "code_interpreter_call",
                    "status": "completed",
                    "code": "values = [1, 2, 3]\nprint('independent review calculation', sum(values), 'output blocks and scenario checks inspected')",
                    "outputs": [{"type": "logs", "logs": "output_blocks validation scenario model_tests artifact review"}],
                },
                {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(report_payload)}]},
            ],
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "_function_tool_calls": [
                {"tool_name": "list_package_artifacts", "ok": True, "arguments": {}, "result": {"ok": True}},
                {"tool_name": "read_package_artifact", "ok": True, "arguments": {"artifact_path": "model_package/model/main.py"}, "result": {"ok": True, "artifact_path": "model_package/model/main.py"}},
                {"tool_name": "read_package_artifact", "ok": True, "arguments": {"artifact_path": "model_package/outputs/output.json"}, "result": {"ok": True, "artifact_path": "model_package/outputs/output.json"}},
                {"tool_name": "execute_model_test", "ok": True, "arguments": {"test_id": "output_blocks_present", "scenario_id": "base"}, "result": {"ok": True}},
            ],
        }
        captured: dict[str, object] = {}

        def fake_post(_api_key: str, body: dict, **_kwargs) -> dict:
            captured["body"] = body
            return raw

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch.object(model_builder, "_package_context", return_value={"latest_output": {}}):
                with patch.object(model_builder, "_post_openai_with_function_tools", side_effect=fake_post) as post_call:
                    report = model_builder.request_review_report("Build model", root, attempt="initial")

        self.assertTrue(post_call.called)
        body = captured["body"]
        tools = body["tools"]  # type: ignore[index]
        self.assertTrue(any(tool.get("type") == "code_interpreter" for tool in tools))  # type: ignore[union-attr]
        self.assertIn("execute_input_probe", {tool.get("name") for tool in tools if tool.get("type") == "function"})  # type: ignore[union-attr]
        self.assertIn("execute_model_test", {tool.get("name") for tool in tools if tool.get("type") == "function"})  # type: ignore[union-attr]
        self.assertIn("read_package_artifact", {tool.get("name") for tool in tools if tool.get("type") == "function"})  # type: ignore[union-attr]
        self.assertFalse(report["repair_required"])

    def test_review_prompt_requires_horizon_output_alignment_check(self) -> None:
        prompt = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")

        self.assertIn("forecast horizon and cadence", prompt)
        self.assertIn("actual output periods", prompt)
        self.assertIn("required_amendments", prompt)
        self.assertIn("Set repair_required=true only", prompt)
        self.assertIn("model_package/inputs/*.json", prompt)
        self.assertIn("Never invent model_package/model/input_schema.json", prompt)

    def test_review_prompt_does_not_block_on_warning_wording(self) -> None:
        prompt = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")

        self.assertIn("Do not deny solely because generated warnings", prompt)
        self.assertIn("hidden plugs that break model mechanics", prompt)

    def test_review_prompt_prioritizes_finance_over_wip_presentation(self) -> None:
        review = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")
        workspace = (ROOT / "backend" / "prompts" / "modeler_workspace.md").read_text(encoding="utf-8")

        self.assertIn("dashboard-layout review are currently WIP and disabled", review)
        self.assertIn("Challenge the approved specification", review)
        self.assertIn("fixed proportional impacts", review)
        self.assertIn("unsupported test coverage", review)
        self.assertIn("cannot publish values from the other two backend executions", review)
        self.assertIn("declared test IDs remain fixed", review)
        self.assertIn("latest explicit user amendment supersedes", review)
        self.assertIn("rerunning the actual model mechanics", workspace)

    def test_review_repair_continues_from_stage_limited_workspace(self) -> None:
        from backend.app import model_builder

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "modeler_workspaces" / "modeler_package_repair_repair_1"
            package = stub_package_files()
            inputs = stub_base_inputs()
            schema = stub_input_schema()
            scenarios = stub_scenario_cases()
            success = (package, inputs, schema, scenarios, {"passed": True}, {"stage": "modeler_package_repair"})

            def workspace_request(*_args, **_kwargs):
                if not workspace.exists():
                    workspace.mkdir(parents=True)
                    raise RuntimeError("Authoritative Modeler workspace exhausted 24 API turns in modeler_package_repair.")
                return success

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(
                model_builder, "_request_workspace_package", side_effect=workspace_request
            ) as request, patch.object(
                model_builder,
                "_scope_modeler_review_repair",
                return_value=(package, inputs, schema, scenarios, {"passed": True}),
            ), patch.object(
                model_builder,
                "_present_replacement_package",
                return_value=(package, {"status": "wip_disabled"}, {"openai_called": False}),
            ):
                model_builder.request_repaired_package(
                    "Repair.", root, {"required_amendments": []}, repair_round=1, review_history=[]
                )

            self.assertEqual(request.call_count, 2)
            second = request.call_args_list[1].kwargs
            self.assertEqual(second["attempt"], "repair_1_continuation_1")
            self.assertEqual(second["seed_package_dir"], workspace)

    def test_quality_prompts_require_generic_boundary_and_branch_evidence(self) -> None:
        prompt_names = (
            "model_theory.md",
            "model_package_self_check.md",
            "model_package_repair.md",
            "model_package_review.md",
        )
        for prompt_name in prompt_names:
            prompt = (ROOT / "backend" / "prompts" / prompt_name).read_text(encoding="utf-8")
            self.assertIn("exactly at", prompt, prompt_name)
            self.assertIn("activation and deactivation", prompt, prompt_name)
            self.assertIn("tautolog", prompt, prompt_name)
            self.assertNotIn("revolver", prompt.lower(), prompt_name)
            self.assertNotIn("working capital", prompt.lower(), prompt_name)

        review = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")
        self.assertIn("Reconcile each label and claimed meaning", review)
        self.assertIn("scenarios never reach the branch", review)

    def test_package_prompts_distinguish_python_literals_from_json_literals(self) -> None:
        for prompt_name in (
            "model_package_build.md",
            "model_package_self_check.md",
            "model_package_backend_repair.md",
            "model_package_repair.md",
            "model_package_amend.md",
        ):
            prompt = (ROOT / "backend" / "prompts" / prompt_name).read_text(encoding="utf-8")
            self.assertIn("use Python literals such as True, False, and None", prompt, prompt_name)
            self.assertIn("never emit JSON literals true, false, or null as executable Python", prompt, prompt_name)

    def test_modeler_repair_prompt_prioritizes_required_amendments(self) -> None:
        prompt = (ROOT / "backend" / "prompts" / "model_package_repair.md").read_text(encoding="utf-8")

        self.assertIn("required_amendments", prompt)
        self.assertIn("amendment_<issue_id>", prompt)

    def test_backend_repair_prompt_requires_exact_runtime_output_dict(self) -> None:
        prompt = (ROOT / "backend" / "prompts" / "model_package_backend_repair.md").read_text(encoding="utf-8")

        self.assertIn("backend_failure_report", prompt)
        self.assertIn("assert type(run_model(base_inputs)) is dict", prompt)
        self.assertIn("backend_failure_resolved", prompt)
        self.assertIn("report = run_checks(raw_inputs, output)", prompt)
        self.assertIn("Never test `run_checks(load_inputs(raw_inputs), output)`", prompt)

    def test_self_check_prompt_requires_exact_raw_input_runtime_contract(self) -> None:
        prompt = (ROOT / "backend" / "prompts" / "model_package_self_check.md").read_text(encoding="utf-8")

        self.assertIn("report = model.checks.run_checks(raw_inputs, output)", prompt)
        self.assertIn("Do not pass `load_inputs(raw_inputs)`", prompt)

    def test_spec_and_review_prompts_use_platform_scenario_selection(self) -> None:
        spec = (ROOT / "backend" / "prompts" / "model_spec_design.md").read_text(encoding="utf-8")
        review = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")

        self.assertIn("Scenario selection is a platform control", spec)
        self.assertIn("Do not require a model-local selector field", spec)
        self.assertIn("Scenario selection is owned by the platform", review)
        self.assertIn("Do not require or propose a model-local selector input", review)

    def test_backend_failure_reasons_preserve_model_test_tracebacks(self) -> None:
        from backend.app import model_builder

        reasons = model_builder._backend_failure_reasons(
            {"passed": True, "checks": []},
            {"passed": True, "checks": []},
            {
                "passed": False,
                "checks": [{
                    "id": "model_tests_executed",
                    "passed": False,
                    "execution_errors": [{"case_id": "base", "error": "TypeError: 'float' object is not subscriptable"}],
                }],
            },
        )

        self.assertEqual(
            reasons,
            ["model_tests_executed [base]: TypeError: 'float' object is not subscriptable"],
        )

    def test_review_finding_accepts_independent_calculation_evidence(self) -> None:
        from backend.app import model_builder

        finding = {
            "severity": "high",
            "area": "model_logic",
            "claim_tested": "UFCF is unlevered.",
            "symptom": "Interest changes enterprise value.",
            "root_cause": "Levered cash tax is used in UFCF.",
            "message": "The DCF includes an interest tax shield.",
            "evidence": {
                "artifacts": ["model_package/model/schedules/financial_model.py"],
                "independent_calculation": {"base_enterprise_value": 46.6, "changed_enterprise_value": 47.0},
                "input_probe": {"input_path": "interest_rate", "observed_behavior": "changed"},
            },
            "repair_instruction": "Use EBIT-based unlevered cash tax.",
            "requires_human_decision": False,
        }

        parsed = model_builder._parse_review_finding(finding)

        self.assertEqual(parsed["evidence"]["artifact"], "model_package/model/schedules/financial_model.py")
        self.assertIn("independent_calculation", parsed["evidence"])

    def test_review_finding_defaults_redundant_human_flag_without_discarding_evidence(self) -> None:
        from backend.app import model_builder

        finding = {
            "severity": "medium",
            "area": "model_logic",
            "claim_tested": "A branch is correct.",
            "symptom": "The branch fails at its boundary.",
            "root_cause": "The comparison uses the wrong operator.",
            "message": "Independent probing found the boundary defect.",
            "evidence": {
                "artifact": "model_package/model/schedules/financial_model.py",
                "input_probe": {"observed": "failed at exact boundary"},
            },
            "repair_instruction": "Correct and retest the boundary.",
        }

        parsed = model_builder._parse_review_finding(finding)

        self.assertFalse(parsed["requires_human_decision"])

    def test_review_finding_recovers_repair_instruction_nested_in_evidence(self) -> None:
        from backend.app import model_builder

        finding = {
            "severity": "medium",
            "area": "spec_alignment",
            "claim_tested": "Valuation convention is documented consistently.",
            "symptom": "The specification retained an obsolete convention.",
            "root_cause": "The amendment updated code but not its governing artifacts.",
            "message": "The calculation is right but its specification is stale.",
            "evidence": {
                "artifact": "model_package/spec/model_spec.json",
                "observed": "The saved text still refers to terminal net debt.",
                "repair_instruction": "Synchronize the specification with opening net debt.",
            },
            "requires_human_decision": False,
        }

        parsed = model_builder._parse_review_finding(finding)

        self.assertEqual(parsed["repair_instruction"], "Synchronize the specification with opening net debt.")

    def test_review_finding_recovers_explicit_paths_from_labeled_evidence(self) -> None:
        from backend.app import model_builder

        finding = {
            "severity": "high",
            "area": "scenario_behavior",
            "claim_tested": "Scenario evidence is causally attributable.",
            "symptom": "Composite movement is assigned to one driver.",
            "root_cause": "The suite compares aggregate cases.",
            "message": "The causal claim is unsupported.",
            "evidence": {
                "specification": "model_package/spec/model_tests.json declares isolated directionality.",
                "implementation": "model_package/model/checks.py compares composite scenarios.",
                "observed_output": "model_package/reports/model_tests_report.json records the aggregate delta.",
            },
            "repair_instruction": "Use controlled single-driver probes.",
            "requires_human_decision": False,
        }

        parsed = model_builder._parse_review_finding(finding)

        self.assertEqual(parsed["evidence"]["artifact"], "model_package/spec/model_tests.json")
        self.assertEqual(
            parsed["evidence"]["artifacts"],
            [
                "model_package/spec/model_tests.json",
                "model_package/model/checks.py",
                "model_package/reports/model_tests_report.json",
            ],
        )

    def test_output_path_resolver_accepts_bracketed_array_indices(self) -> None:
        from backend.app import model_builder

        output = {
            "output_blocks": [
                {"id": "summary", "data": {"value": 1}},
                {"id": "valuation", "data": {"wacc_direction_status": "verified"}},
            ]
        }

        self.assertEqual(
            model_builder._get_output_path_value(
                output,
                "output_blocks[1].data.wacc_direction_status",
            ),
            (True, "verified"),
        )

    def test_review_artifact_alias_resolves_only_to_existing_canonical_spec(self) -> None:
        from backend.app import model_builder

        with tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp") as temp_dir:
            root = Path(temp_dir) / "version"
            canonical = root / "model_package" / "spec" / "model_tests.json"
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.write_text("{}", encoding="utf-8")
            report = {
                "findings": [
                    {
                        "evidence": {
                            "artifact": "model_package/model_tests.json",
                            "artifacts": ["model_package/model_tests.json", "model_package/model/missing.py"],
                        }
                    }
                ],
                "required_amendments": [
                    {"artifacts": ["model_package/model_tests.json", "model_package/model/missing.py"]}
                ],
            }

            normalized = model_builder._normalize_review_artifact_aliases(root, report)

            self.assertEqual(normalized["findings"][0]["evidence"]["artifact"], "model_package/spec/model_tests.json")
            self.assertEqual(
                normalized["required_amendments"][0]["artifacts"],
                ["model_package/spec/model_tests.json", "model_package/model/missing.py"],
            )

    def test_review_finding_rejects_citations_without_concrete_detail(self) -> None:
        from backend.app import model_builder

        finding = {
            "severity": "medium",
            "area": "test_coverage",
            "claim_tested": "Scenario test is meaningful.",
            "symptom": "No detail.",
            "root_cause": "No detail.",
            "message": "No detail.",
            "evidence": {"artifact": "model_package/model/checks.py"},
            "repair_instruction": "Add evidence.",
            "requires_human_decision": False,
        }

        with self.assertRaisesRegex(RuntimeError, "concrete detail"):
            model_builder._parse_review_finding(finding)

    def test_generation_failure_classifier_reports_transport_subcodes(self) -> None:
        from backend.app import model_builder

        incomplete = http.client.IncompleteRead(b"", 10)
        timeout = TimeoutError("The read operation timed out")

        self.assertEqual(model_builder._classify_generation_failure(incomplete, default="spec_failed"), "openai_transport_failed")
        self.assertEqual(model_builder._classify_generation_failure_subcode(incomplete), "openai_incomplete_read")
        self.assertEqual(model_builder._classify_generation_failure(timeout, default="parser_failed"), "openai_transport_failed")
        self.assertEqual(model_builder._classify_generation_failure_subcode(timeout), "openai_timeout")

    def test_insufficient_quota_is_not_retried_and_has_distinct_failure_class(self) -> None:
        from backend.app import model_builder

        body = b'{"error":{"code":"insufficient_quota","message":"You exceeded your current quota"}}'
        exc = urllib_error.HTTPError("https://api.openai.com/v1/responses", 429, "Too Many Requests", {}, io.BytesIO(body))

        self.assertFalse(model_builder._is_retryable_openai_transport_error(exc))
        message = model_builder._openai_error_message(exc)
        self.assertIn("insufficient_quota", message)
        self.assertEqual(model_builder._classify_generation_failure(RuntimeError(message), default="parser_failed"), "quota_blocked")
        self.assertEqual(model_builder._classify_generation_failure_subcode(RuntimeError(message)), "insufficient_quota")
        exc.close()

    def test_post_openai_retries_transport_timeout_once(self) -> None:
        from backend.app import model_builder

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"output_text":"ok"}'

        with (
            patch.object(model_builder, "_openai_response_timeout_seconds", return_value=123),
            patch.object(model_builder, "_openai_transport_max_retries", return_value=1),
            patch.object(model_builder, "_openai_transport_retry_delay_seconds", return_value=0),
            patch.object(model_builder.request, "urlopen", side_effect=[TimeoutError("timed out"), Response()]) as urlopen,
        ):
            raw = model_builder._post_openai("test-key", {"model": "test", "input": []})

        self.assertEqual(raw["output_text"], "ok")
        self.assertIn("_transport", raw["usage"])
        self.assertEqual(raw["usage"]["_transport"]["attempt_count"], 2)
        self.assertEqual(raw["usage"]["_transport"]["timeout_seconds"], 123)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args_list[0].kwargs["timeout"], 123)

    def test_record_usage_includes_duration_fields(self) -> None:
        from backend.app import model_builder

        root = RUNTIME_DIR / "version"
        usage = {
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
            "_transport": {
                "started_utc": "2026-05-26T10:00:00Z",
                "completed_utc": "2026-05-26T10:00:03Z",
                "duration_seconds": 3.25,
                "timeout_seconds": 900,
                "attempt_count": 2,
                "max_attempts": 3,
                "retry_count": 1,
                "max_retries": 2,
            },
        }

        report = model_builder._record_usage(root, "gpt-5.4-mini", usage, stage="duration_test")

        self.assertEqual(report["duration_seconds"], 3.25)
        self.assertEqual(report["retry_count"], 1)
        self.assertNotIn("_transport", report["usage"])

    def test_post_openai_does_not_retry_parser_failures(self) -> None:
        from backend.app import model_builder

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b'{"output_text":'

        with (
            patch.object(model_builder, "_openai_response_timeout_seconds", return_value=123),
            patch.object(model_builder, "_openai_transport_max_retries", return_value=3),
            patch.object(model_builder.request, "urlopen", return_value=Response()) as urlopen,
        ):
            with self.assertRaises(json.JSONDecodeError):
                model_builder._post_openai("test-key", {"model": "test", "input": []})

        self.assertEqual(urlopen.call_count, 1)

    def test_mechanical_stress_passes_required_scenarios(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertTrue(report["passed"], report)
        self.assertEqual({case["id"] for case in report["cases"]}, {"base", "downside", "upside"})
        checks = {check["id"]: check for check in report["checks"]}
        self.assertTrue(checks["non_base_scenarios_change_outputs"]["passed"])
        self.assertTrue(checks["scenario_covers_editable_inputs"]["passed"])
        self.assertEqual(checks["scenario_covers_editable_inputs"]["coverage_ratio"], 1.0)
        self.assertEqual(checks["scenario_covers_editable_inputs"]["missing_paths"], [])

    def test_mechanical_stress_fails_when_scenarios_do_not_cover_all_editable_inputs(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        scenarios = stub_scenario_cases()
        scenarios[1] = {**scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
        scenarios[2] = {**scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}
        _write_package_inputs(package_dir, scenarios=scenarios)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        coverage = checks["scenario_covers_editable_inputs"]
        self.assertFalse(coverage["passed"])
        self.assertEqual(coverage["covered_paths"], ["drivers.primary_value"])
        self.assertEqual(set(coverage["missing_paths"]), {"drivers.change_rate", "settings.opening_value"})

    def test_mechanical_stress_rejects_base_overrides_as_duplicate_base_ownership(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        scenarios = stub_scenario_cases()
        scenarios[0] = {
            **scenarios[0],
            "input_overrides": {
                "drivers.primary_value": 100.0,
                "drivers.change_rate": 0.1,
                "settings.opening_value": 25.0,
            },
        }
        scenarios[1] = {**scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
        scenarios[2] = {**scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}
        _write_package_inputs(package_dir, scenarios=scenarios)

        report = model_builder.run_mechanical_stress(package_dir)

        checks = {check["id"]: check for check in report["checks"]}
        shape = checks["scenario_cases_shape_valid"]
        self.assertFalse(shape["passed"])
        self.assertIn("Base input_overrides must be empty", shape["error"])

    def test_mechanical_stress_reports_missing_required_scenario(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        _write_package_inputs(package_dir, scenarios=stub_scenario_cases()[:2])

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        self.assertFalse(checks["required_scenarios_present"]["passed"])
        self.assertIn("upside", checks["required_scenarios_present"]["missing_ids"])

    def test_mechanical_stress_reports_invalid_override_path(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(stub_main_py())
        scenarios = stub_scenario_cases()
        scenarios[1] = {**scenarios[1], "input_overrides": {"missing.path": 80.0}}
        _write_package_inputs(package_dir, scenarios=scenarios)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        self.assertFalse(checks["scenario_paths_valid"]["passed"])
        self.assertEqual(checks["scenario_paths_valid"]["invalid_paths"][0]["path"], "missing.path")

    def test_mechanical_stress_reports_execution_errors(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(
            """
def run_model(inputs):
    if float(inputs.get("drivers", {}).get("primary_value", 0)) < 90:
        raise RuntimeError("scenario boom")
    return {
        "output_version": "2026-05-25",
        "output_blocks": [
            {"id": "primary_result", "type": "kpi", "label": "Primary result", "data": {"value": inputs["drivers"]["primary_value"]}}
        ],
        "dashboard_spec": {},
        "metadata": {"openai_called": False},
    }
"""
        )
        _write_package_inputs(package_dir)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        self.assertFalse(checks["scenario_execution"]["passed"])
        self.assertIn("scenario boom", checks["scenario_execution"]["execution_errors"][0]["error"])

    def test_mechanical_stress_fails_when_non_base_outputs_do_not_move(self) -> None:
        from backend.app import model_builder

        package_dir = _write_main(_constant_output_source())
        _write_package_inputs(package_dir)

        report = model_builder.run_mechanical_stress(package_dir)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        self.assertFalse(checks["non_base_scenarios_change_outputs"]["passed"])

    def test_scalar_array_paths_accept_bracket_notation_and_normalize_to_dot_indices(self) -> None:
        from backend.app import model_builder

        inputs = {"weekly_sales": [100.0, 110.0]}
        schema = {
            "fields": [
                {"path": "weekly_sales[0]", "label": "Week 1", "type": "number", "editable": True},
                {"path": "weekly_sales[1]", "label": "Week 2", "type": "number", "editable": True},
            ]
        }

        parsed = model_builder._validate_input_schema(schema, inputs, source="test schema")

        self.assertEqual([field["path"] for field in parsed["fields"]], ["weekly_sales.0", "weekly_sales.1"])
        self.assertEqual(model_builder._get_path(inputs, "weekly_sales[1]"), 110.0)
        model_builder._set_path(inputs, "weekly_sales.0", 125.0)
        self.assertEqual(inputs["weekly_sales"][0], 125.0)

    def test_flexible_weekly_schema_accepts_scalar_or_thirteen_value_parent(self) -> None:
        from backend.app import model_builder

        schema = {
            "fields": [
                {
                    "path": "weekly_sales",
                    "label": "Weekly sales",
                    "type": "number_or_13_number_array",
                    "editable": True,
                }
            ]
        }

        scalar = model_builder._validate_input_schema(schema, {"weekly_sales": 100.0}, source="scalar schema")
        scheduled = model_builder._validate_input_schema(
            schema, {"weekly_sales": [100.0] * 13}, source="schedule schema"
        )

        self.assertEqual(scalar["fields"][0]["path"], "weekly_sales")
        self.assertEqual(scheduled["fields"][0]["path"], "weekly_sales")
        self.assertEqual(
            model_builder._editable_numeric_paths(scheduled, {"weekly_sales": [100.0] * 13}),
            {"weekly_sales"},
        )

    def test_flexible_weekly_schema_rejects_bad_length_and_duplicate_children(self) -> None:
        from backend.app import model_builder

        field = {
            "path": "weekly_sales",
            "label": "Weekly sales",
            "type": "number_or_13_number_array",
            "editable": True,
        }
        with self.assertRaisesRegex(RuntimeError, "13-number array"):
            model_builder._validate_input_schema(
                {"fields": [field]}, {"weekly_sales": [100.0] * 12}, source="bad schedule"
            )
        with self.assertRaisesRegex(RuntimeError, "contains paths not in scalar base_inputs"):
            model_builder._validate_input_schema(
                {
                    "fields": [
                        field,
                        {"path": "weekly_sales.0", "label": "Week 1", "type": "number", "editable": True},
                    ]
                },
                {"weekly_sales": [100.0] * 13},
                source="duplicate schedule",
            )

    def test_flexible_generic_schedule_uses_declared_period_count_and_labels(self) -> None:
        from backend.app import model_builder

        field = {
            "path": "annual_growth",
            "label": "Annual growth",
            "type": "number_or_number_array",
            "period_count": 5,
            "period_labels": ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5"],
            "editable": True,
        }
        scalar = model_builder._validate_input_schema({"fields": [field]}, {"annual_growth": 0.04}, source="annual scalar")
        scheduled = model_builder._validate_input_schema({"fields": [field]}, {"annual_growth": [0.04] * 5}, source="annual schedule")

        self.assertEqual(scalar["fields"][0]["period_count"], 5)
        self.assertEqual(model_builder._editable_numeric_paths(scheduled, {"annual_growth": [0.04] * 5}), {"annual_growth"})
        with self.assertRaisesRegex(RuntimeError, "5-number array"):
            model_builder._validate_input_schema({"fields": [field]}, {"annual_growth": [0.04] * 6}, source="bad annual schedule")
        bad_labels = {**field, "period_labels": ["Year 1"]}
        with self.assertRaisesRegex(RuntimeError, "period_labels"):
            model_builder._validate_input_schema({"fields": [bad_labels]}, {"annual_growth": 0.04}, source="bad labels")

    def test_prompts_require_flexible_weekly_and_finite_numeric_contract(self) -> None:
        for prompt_name in (
            "model_package_build.md",
            "model_package_self_check.md",
            "model_package_repair.md",
            "model_package_backend_repair.md",
            "model_package_amend.md",
            "model_package_review.md",
        ):
            prompt = (ROOT / "backend" / "prompts" / prompt_name).read_text(encoding="utf-8")
            self.assertIn("number_or_13_number_array", prompt, prompt_name)
            self.assertIn("number_or_number_array", prompt, prompt_name)
            self.assertIn("NaN", prompt, prompt_name)
            self.assertIn("infinity", prompt, prompt_name)

    def test_self_check_preflight_context_keeps_failures_and_compacts_success_payloads(self) -> None:
        from backend.app import model_builder

        bulky = "x" * 100000
        preflight = {
            "available": True,
            "passed": False,
            "validation_report": {
                "passed": True,
                "checks": [{"id": "imports", "passed": True, "evidence": {"output": bulky}}],
            },
            "mechanical_stress_report": {
                "passed": True,
                "checks": [{"id": "scenarios", "passed": True, "outputs": bulky}],
            },
            "model_tests_report": {
                "passed": False,
                "checks": [
                    {"id": "model_tests_all_passed", "passed": False, "false_tests": [{"id": "boundary", "message": "failed"}]}
                ],
            },
        }

        compact = model_builder._compact_mechanical_preflight_for_prompt(preflight)

        encoded = json.dumps(compact)
        self.assertLess(len(encoded), 2000)
        self.assertEqual(compact["validation_report"]["checks"], [{"id": "imports", "passed": True}])
        self.assertEqual(
            compact["model_tests_report"]["checks"][0]["false_tests"][0]["id"], "boundary"
        )


if __name__ == "__main__":
    unittest.main()




