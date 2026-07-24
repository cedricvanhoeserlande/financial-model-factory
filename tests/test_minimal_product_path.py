from __future__ import annotations

import shutil
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from tests.runtime_helpers import isolated_runtime, reload_app_runtime_modules

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp" / "minimal_product_path"


def stub_main_py() -> str:
    return """
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    clean_inputs = load_inputs(inputs)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules)
""".strip()


def stub_assumptions_py() -> str:
    return """
def load_inputs(inputs):
    _ = inputs["periods"]
    _ = inputs["drivers"]["primary_value"]
    _ = inputs["drivers"]["change_rate"]
    _ = inputs["settings"]["opening_value"]
    return inputs
""".strip()


def stub_schedule_py() -> str:
    return """
def build_rows(inputs):
    periods = inputs["periods"]
    primary = float(inputs["drivers"]["primary_value"])
    change_rate = float(inputs["drivers"]["change_rate"])
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


def stub_schedules_init_py() -> str:
    return """
from model.schedules.core import build_rows


def run_all(inputs):
    return {"model_rows": build_rows(inputs)}
""".strip()


def stub_outputs_py() -> str:
    return """
def build_output(inputs, schedules):
    rows = schedules["model_rows"]
    primary_result = round(sum(row["primary_value"] for row in rows), 2)
    return {
        "output_version": "2026-05-25",
        "output_blocks": [
            {"id": "primary_result", "type": "kpi", "label": "Primary result", "data": {"value": primary_result, "unit": "number"}},
            {
                "id": "model_rows",
                "type": "table",
                "label": "Model rows",
                "data": {
                    "columns": [
                        {"id": "period", "label": "Period"},
                        {"id": "primary_value", "label": "Primary value"},
                        {"id": "ending_value", "label": "Ending value"},
                    ],
                    "rows": rows,
                },
            },
            {
                "id": "primary_value_series",
                "type": "time_series",
                "label": "Primary value series",
                "data": {
                    "x": [row["period"] for row in rows],
                    "series": [{"id": "primary_value", "label": "Primary value", "values": [row["primary_value"] for row in rows]}],
                },
            },
            {
                "id": "scenario_metric_comparison",
                "type": "scenario_comparison",
                "label": "Scenario metric comparison",
                "data": {
                    "scenarios": [
                        {"id": "base", "label": "Base"},
                        {"id": "downside", "label": "Downside"},
                        {"id": "upside", "label": "Upside"},
                    ],
                    "metrics": [
                        {
                            "id": "primary_result",
                            "label": "Primary result",
                            "values": {"base": primary_result, "downside": round(primary_result * 0.8, 2), "upside": round(primary_result * 1.2, 2)},
                        }
                    ],
                },
            },
        ],
        "dashboard_spec": {"intent": "Show KPI, model rows, time series, and scenario comparison blocks."},
        "metadata": {"openai_called": False},
    }
""".strip()


def stub_checks_py() -> str:
    return """

def run_checks(inputs, outputs):
    blocks = outputs.get("output_blocks") or []
    block_ids = {block.get("id") for block in blocks if isinstance(block, dict)}
    return {
        "checks": [
            {
                "id": "output_blocks_present",
                "passed": "primary_result" in block_ids and "model_rows" in block_ids,
                "message": "Required output blocks are present.",
                "evidence": {"output_block_count": len(blocks)},
            }
        ]
    }
""".strip()


def stub_main_py_with_marker(marker: str) -> str:
    return stub_main_py() + f"\n# {marker}\n"


def stub_package_files(main_py: str | None = None, checks_py: str | None = None) -> list[dict[str, str]]:
    return [
        {"path": "model/main.py", "content": main_py or stub_main_py()},
        {"path": "model/assumptions.py", "content": stub_assumptions_py()},
        {"path": "model/schedules/__init__.py", "content": stub_schedules_init_py()},
        {"path": "model/schedules/core.py", "content": stub_schedule_py()},
        {"path": "model/outputs.py", "content": stub_outputs_py()},
        {"path": "model/checks.py", "content": checks_py or stub_checks_py()},
    ]


def stub_tuple_output_main_py() -> str:
    return """
from model.assumptions import load_inputs
from model.schedules import run_all
from model.outputs import build_output


def run_model(inputs):
    clean_inputs = load_inputs(inputs)
    schedules = run_all(clean_inputs)
    return build_output(clean_inputs, schedules),
""".strip()


def stub_base_inputs() -> dict:
    return {
        "periods": [1, 2, 3, 4, 5],
        "drivers": {"primary_value": 100.0, "change_rate": 0.1},
        "settings": {"opening_value": 25.0},
    }


def stub_input_schema() -> dict:
    return {
        "type": "object",
        "groups": [{"id": "drivers", "label": "Drivers"}, {"id": "settings", "label": "Settings"}],
        "fields": [
            {"path": "drivers.primary_value", "label": "Primary value", "group": "drivers", "type": "number", "editable": True, "read_only": False, "value_number": 100.0},
            {"path": "drivers.change_rate", "label": "Change rate", "group": "drivers", "type": "number", "editable": True, "read_only": False, "value_number": 0.1},
            {"path": "settings.opening_value", "label": "Opening value", "group": "settings", "type": "number", "editable": True, "read_only": False, "value_number": 25.0},
        ],
        "compiler": {"strategy": "model_package", "review_required": True},
    }


def stub_scenario_cases() -> list[dict]:
    return [
        {"id": "base", "label": "Base", "description": "Base package inputs.", "input_overrides": {}},
        {
            "id": "downside",
            "label": "Downside",
            "description": "Lower primary driver case covering all editable inputs.",
            "input_overrides": {
                "drivers.primary_value": 80.0,
                "drivers.change_rate": 0.05,
                "settings.opening_value": 15.0,
            },
        },
        {
            "id": "upside",
            "label": "Upside",
            "description": "Higher primary driver case covering all editable inputs.",
            "input_overrides": {
                "drivers.primary_value": 120.0,
                "drivers.change_rate": 0.15,
                "settings.opening_value": 35.0,
            },
        },
    ]


def stub_modeler_self_check() -> dict:
    return {
        "passed": True,
        "summary": "Generated package was checked with the python tool against base inputs and an edited driver.",
        "checks": [
            {"id": "base_inputs_execute", "passed": True},
            {"id": "editable_path_exists", "passed": True, "path": "drivers.primary_value"},
            {"id": "edited_input_moves_output", "passed": True},
            {"id": "output_data_contract_valid", "passed": True},
            {"id": "model_spec_output_alignment", "passed": True},
            {"id": "model_thesis_alignment", "passed": True},
            {"id": "equation_graph_alignment", "passed": True},
            {"id": "dashboard_spec_present", "passed": True},
            {"id": "editable_inputs_match_spec", "passed": True},
            {"id": "scenario_cases_match_spec", "passed": True},
            {"id": "scenario_covers_editable_inputs", "passed": True},
            {"id": "model_tests_declared", "passed": True},
            {"id": "model_tests_executed", "passed": True},
            {"id": "model_tests_all_passed", "passed": True},
            {"id": "json_shapes_strict", "passed": True},
        ],
        "issues": [],
        "code_interpreter_required": True,
        "code_interpreter_call_count": 1,
        "code_interpreter_calls": [{"id": "ci_1", "status": "completed", "code": "print('checked')", "outputs": [{"type": "logs", "logs": "checked"}]}],
    }


def stub_workspace_package_result(main_py: str | None = None):
    self_check = {
        **stub_modeler_self_check(),
        "transport": "workspace_tool_loop",
        "code_interpreter_required": False,
        "code_interpreter_call_count": 0,
        "tool_call_count": 9,
        "api_turn_count": 4,
    }
    usage = {
        "stage": "modeler_package_build",
        "model": "gpt-5.6-terra",
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        "openai_called": True,
        "transport": "workspace_tool_loop",
    }
    return stub_package_files(main_py=main_py), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), self_check, usage


def stub_review_report(*, approved: bool = True, repair_required: bool = False, summary: str = "Review passed.", failure_reasons: list[str] | None = None) -> dict:
    required_amendments = [] if not repair_required else [
        {
            "issue_id": "primary_result_does_not_decrease",
            "severity": "high",
            "category": "model_logic",
            "artifacts": ["model_package/model/main.py"],
            "verification_probe": {
                "input_path": "drivers.primary_value",
                "changed_value": 80.0,
                "output_path": "output_blocks.primary_result.data.value",
                "expected_behavior": "decrease",
            },
            "observed": "Primary result did not decrease enough under the probe.",
            "required_change": "Connect drivers.primary_value to the primary_result output.",
            "acceptance_criteria": ["Primary result decreases when primary value decreases."],
            "human_decision_required": False,
        }
    ]
    return {
        "approved": approved,
        "repair_required": repair_required,
        "summary": summary,
        "findings": []
        if approved
        else [
            {
                "severity": "high",
                "area": "package",
                "claim_tested": "Package quality should satisfy the review prompt.",
                "symptom": summary,
                "root_cause": "Stub package quality issue.",
                "message": summary,
                "evidence": {"artifact": "model_package/outputs/output.json", "note": "Stub review finding."},
                "repair_instruction": "Repair the package and rerun checks.",
                "requires_human_decision": False,
            }
        ],
        "required_amendments": required_amendments,
        "repair_instructions": [] if not repair_required else ["Repair the package and rerun checks."],
        "human_questions": [],
        "failure_reasons": failure_reasons or ([] if approved else [summary]),
        "attempt": "stub",
    }


def stub_model_spec() -> dict:
    return {
        "spec_version": "2026-05-23",
        "title": "Custom model package",
        "purpose": "Build a model package with editable drivers and inspectable outputs.",
        "scope_summary": "The package should model a primary driver over periods, expose editable inputs, and produce tables and KPIs.",
        "modeled_objects": [{"id": "core", "label": "Core object", "description": "Primary modeled object."}],
        "editable_inputs": [{"id": "primary_value", "label": "Primary value", "path_hint": "drivers.primary_value"}],
        "assumptions": [{"id": "change_rate", "label": "Change rate", "source": "user scope"}],
        "scenario_design": [
            {"id": "base", "label": "Base"},
            {"id": "downside", "label": "Downside"},
            {"id": "upside", "label": "Upside"},
        ],
        "outputs": [{"id": "model_rows", "label": "Model rows"}],
        "dashboard_intent": [{"id": "summary", "label": "Summary"}],
        "known_limitations": [],
        "unresolved_questions": [],
        "build_readiness": {"ready_to_build": True, "blockers": []},
    }


def stub_model_theory() -> dict:
    return {
        "model_thesis": {
            "thesis_version": "2026-05-31",
            "purpose": "Build a model package with editable drivers and inspectable outputs.",
            "modeled_objects": [{"id": "core", "label": "Core object", "description": "The generated model object."}],
            "assumptions": [{"id": "primary_value", "label": "Primary value", "description": "Editable primary driver used by the package."}],
            "policy_choices": [],
            "outputs": [{"id": "primary_result", "label": "Primary result", "description": "Primary KPI output block."}],
            "exclusions": [],
            "limitations": [],
        },
        "equation_graph": {
            "graph_version": "2026-05-31",
            "nodes": [{"id": "primary_result", "label": "Primary result", "description": "Primary calculation node."}],
            "edges": [],
            "calculation_order": ["load inputs", "calculate rows", "build output blocks"],
            "key_tie_outs": [{"id": "output_blocks_present", "label": "Output blocks present", "description": "Required output blocks are returned."}],
            "output_dependencies": [{"id": "primary_result", "label": "Primary result", "description": "Primary result output depends on core schedule rows."}],
        },
        "model_tests": [
            {
                "id": "output_blocks_present",
                "label": "Output blocks present",
                "test_type": "run_check",
                "execution_scope": "case",
                "purpose": "Confirm required output blocks exist.",
                "logic_description": "Check primary KPI and model rows output blocks are returned.",
                "evidence_expected": "Output block count and ids.",
                "repair_guidance": "Add missing output blocks or fix output block ids.",
            }
        ],
    }


def write_stub_model_theory(root: Path) -> None:
    from backend.app import model_builder

    theory = stub_model_theory()
    model_builder._write_json(root / "model_thesis.json", {"status": "ready", "path": "model_thesis.json", "model_thesis": theory["model_thesis"]})
    model_builder._write_json(root / "equation_graph.json", {"status": "ready", "path": "equation_graph.json", "equation_graph": theory["equation_graph"]})
    model_builder._write_json(root / "model_tests.json", {"status": "ready", "path": "model_tests.json", "model_tests": theory["model_tests"]})


def approve_stub_spec(model_loop, model_id: str, prompt: str = "Build a custom model package.") -> None:
    from backend.app import model_builder, model_spec

    usage = {"stage": "modeler_model_spec", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
    with patch.object(model_spec, "request_model_spec", return_value=(stub_model_spec(), usage)):
        model_loop.generate_model_spec_record(model_id, prompt)
    model_loop.approve_model_spec_record(model_id)
    manifest = model_loop.open_model_workspace(model_id)["model_manifest"]
    root = model_builder.version_dir(model_id, manifest["current_version_id"])
    write_stub_model_theory(root)


def output_block_value(output: dict, block_id: str) -> float:
    for block in output.get("output_blocks", []):
        if block.get("id") == block_id:
            return float((block.get("data") or {}).get("value"))
    raise AssertionError(f"Output block not found: {block_id}")


def raw_openai_package_response(main_py: str | None = None) -> dict:
    parsed = {
        "package_files": stub_package_files(main_py=main_py),
        "base_inputs": stub_base_inputs(),
        "input_schema": stub_input_schema(),
        "scenario_cases": stub_scenario_cases(),
        "modeler_self_check": stub_modeler_self_check(),
    }
    return {
        "output": [
            {
                "id": "ci_1",
                "type": "code_interpreter_call",
                "status": "completed",
                "code": "print('checked')",
                "outputs": [{"type": "logs", "logs": "checked"}],
            },
            {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(parsed)}]},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    }


def raw_openai_model_theory_response() -> dict:
    return {
        "output": [
            {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(stub_model_theory())}]}
        ],
        "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
    }


def raw_openai_amendment_response(main_py: str | None = None, model_spec: dict | None = None, change_summary: dict | None = None) -> dict:
    parsed = {
        "model_spec": model_spec or {**stub_model_spec(), "title": "Amended custom model package"},
        "package_files": stub_package_files(main_py=main_py or stub_main_py_with_marker("amended package")),
        "base_inputs": stub_base_inputs(),
        "input_schema": stub_input_schema(),
        "scenario_cases": stub_scenario_cases(),
        "modeler_self_check": stub_modeler_self_check(),
        "change_summary": change_summary or {"summary": "Updated package per user amendment.", "changed_outputs": ["Results table"]},
    }
    return {
        "output": [
            {
                "id": "ci_amend_1",
                "type": "code_interpreter_call",
                "status": "completed",
                "code": "print('amendment checked')",
                "outputs": [{"type": "logs", "logs": "amendment checked"}],
            },
            {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(parsed)}]},
        ],
        "usage": {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33},
    }


def raw_review_response(report: dict) -> dict:
    raw = {
        "output": [
            {
                "id": "ci_review_1",
                "type": "code_interpreter_call",
                "status": "completed",
                "code": "print('review checked output_blocks validation_report mechanical_stress_report input_schema scenario model_tests')",
                "outputs": [{"type": "logs", "logs": "review checked output_blocks validation_report mechanical_stress_report input_schema scenario model_tests"}],
            },
            {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(report)}]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
    }
    raw["_function_tool_calls"] = [
        {"tool_name": "list_package_artifacts", "ok": True, "arguments": {}, "result": {"ok": True, "artifacts": []}},
        {
            "tool_name": "read_package_artifact",
            "ok": True,
            "arguments": {"artifact_path": "model_package/model/main.py"},
            "result": {"ok": True, "artifact_path": "model_package/model/main.py"},
        },
        {
            "tool_name": "read_package_artifact",
            "ok": True,
            "arguments": {"artifact_path": "model_package/outputs/output.json"},
            "result": {"ok": True, "artifact_path": "model_package/outputs/output.json"},
        },
        {
            "stage": "model_package_review",
            "attempt": "initial",
            "tool_name": "execute_input_probe",
            "ok": True,
            "arguments": {"issue_id": "primary_result_probe"},
            "result": {"ok": True, "input_path": "drivers.primary_value", "base_value": 100.0, "changed_value": 80.0, "observed_behavior": "decrease"},
        },
    ]
    return raw


class MinimalProductPathTest(unittest.TestCase):
    def setUp(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def tearDown(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def test_build_requires_approved_model_spec(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Spec gate test", "")
            model_id = created["model_manifest"]["model_id"]

            with self.assertRaisesRegex(RuntimeError, "approve a model specification"):
                model_loop.build_model_package_record(model_id, "Build without an approved spec.")

    def test_prompt_to_package_publish_and_no_openai_rerun(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Minimal product test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }

            approve_stub_spec(model_loop, model_id, "Build a custom model package with editable drivers.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)) as call:
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report()) as review_call:
                    with patch.object(model_builder, "request_repaired_package") as repair_call:
                        built = model_loop.build_model_package_record(
                            model_id,
                            "Build a custom model package with editable drivers.",
                        )
            self.assertEqual(call.call_count, 1)
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(repair_call.call_count, 0)
            pipe = built["workspace"]["package_state"]
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(pipe["build_source"], "modeler_package_files")
            self.assertTrue(pipe["validation_report"]["passed"])
            check_ids = {check["id"]: check["passed"] for check in pipe["validation_report"]["checks"]}
            self.assertTrue(check_ids["package_imports"])
            self.assertTrue(check_ids["run_model_callable"])
            self.assertTrue(check_ids["output_contract_valid"])
            self.assertNotIn("editable_input_changes_output", check_ids)
            self.assertNotIn("published_rerun_no_openai", check_ids)
            self.assertTrue(pipe["modeler_self_check"]["passed"])
            self.assertEqual(pipe["modeler_self_check"]["code_interpreter_call_count"], 1)
            self.assertTrue(pipe["mechanical_stress_report"]["passed"])
            self.assertTrue(pipe["review_report"]["approved"])
            self.assertFalse(pipe["review_report"]["repair_required"])
            pre_publish = pipe["pre_publish_summary"]
            self.assertEqual(pre_publish["status"], "ready")
            self.assertTrue(pre_publish["can_publish"])
            self.assertTrue(pre_publish["all_sections_present"])
            for section in ("approved_spec", "inputs", "outputs", "validation", "mechanical_stress", "review", "technical_evidence"):
                self.assertTrue(pre_publish["sections_present"][section])
            stress_checks = {check["id"]: check["passed"] for check in pipe["mechanical_stress_report"]["checks"]}
            self.assertTrue(stress_checks["required_scenarios_present"])
            self.assertTrue(stress_checks["scenario_paths_valid"])
            self.assertTrue(stress_checks["scenario_covers_editable_inputs"])
            self.assertTrue(stress_checks["scenario_execution"])
            self.assertTrue(stress_checks["scenario_outputs_comparable"])
            self.assertTrue(stress_checks["non_base_scenarios_change_outputs"])
            for key in ("output_version", "output_blocks", "dashboard_spec", "metadata"):
                self.assertIn(key, pipe["latest_output"])
            self.assertNotIn("results_table", pipe["latest_output"])

            published = model_loop.publish_model_record(model_id)
            self.assertEqual(published["model_manifest"]["status"], "published")

            inputs = published["workspace"]["canonical_inputs"]
            base_total = output_block_value(published["workspace"]["package_state"]["latest_output"], "primary_result")
            edited = {**inputs, "drivers": {**inputs["drivers"], "primary_value": inputs["drivers"]["primary_value"] * 1.5}}
            rerun = model_loop.execute_run(edited, model_id=model_id)
            after_total = output_block_value(rerun["result"], "primary_result")

            self.assertGreater(after_total, base_total)
            self.assertEqual(rerun["input_params"]["drivers"]["primary_value"], edited["drivers"]["primary_value"])
            self.assertEqual(rerun["package_state"]["resolved_input_params"]["drivers"]["primary_value"], edited["drivers"]["primary_value"])
            self.assertFalse(rerun["metadata"]["openai_called"])
            self.assertTrue(rerun["package_state"]["published_rerun_uses_saved_package"])
            evidence = rerun["package_state"]["rerun_execution_evidence"]
            self.assertEqual(evidence["openai_call_delta"], 0)
            self.assertFalse(evidence["openai_called"])
            self.assertTrue(evidence["inputs_changed"])
            self.assertTrue(evidence["output_changed"])
            self.assertTrue(evidence["validation_passed"])
            self.assertTrue(evidence["model_tests_passed"])
            rerun_checks = {
                check["id"]: check["passed"]
                for check in rerun["package_state"]["validation_report"]["checks"]
            }
            self.assertTrue(rerun_checks["published_rerun_no_openai"])

    def test_backend_only_build_fails_before_review_when_scenarios_do_not_cover_editable_inputs(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Scenario coverage gate test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }
            sparse_scenarios = stub_scenario_cases()
            sparse_scenarios[1] = {**sparse_scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
            sparse_scenarios[2] = {**sparse_scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}

            approve_stub_spec(model_loop, model_id, "Build a custom model package with incomplete scenarios.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), sparse_scenarios, stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report") as review_call:
                    built = model_loop.build_model_package_record(
                        model_id,
                        "Build a custom model package with incomplete scenarios.",
                        run_review=False,
                    )

            pipe = built["workspace"]["package_state"]
            self.assertEqual(pipe["status"], "failed_checks")
            self.assertEqual(review_call.call_count, 0)
            checks = {check["id"]: check for check in pipe["mechanical_stress_report"]["checks"]}
            self.assertFalse(checks["scenario_covers_editable_inputs"]["passed"])
            self.assertEqual(set(checks["scenario_covers_editable_inputs"]["missing_paths"]), {"drivers.change_rate", "settings.opening_value"})
            self.assertEqual(pipe["failure_code"], "mechanical_stress_failed")
            self.assertEqual(pipe["failure_stage"], "backend_mechanical_stress")
            self.assertTrue(pipe["failure_report"])
            self.assertIn("scenario_covers_editable_inputs", pipe["failure_reasons"])
            self.assertFalse(pipe["publish_eligible"])

    def test_authoritative_workspace_blocks_invalid_initial_package_before_review(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Backend repair validation test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approve_stub_spec(model_loop, model_id, "Build a package that initially returns the wrong Python type.")
            with patch.object(model_builder, "request_model_package", side_effect=RuntimeError("Modeler returned a completion response before submitting a passing authoritative workspace.")), patch.object(model_builder, "request_review_report") as review_call:
                with self.assertRaisesRegex(RuntimeError, "authoritative workspace"):
                    model_loop.build_model_package_record(model_id, "Build a package that initially returns the wrong Python type.")

            root = sorted((model_builder.versions_root() / model_id).iterdir())[-1]
            self.assertEqual(review_call.call_count, 0)
            self.assertFalse((root / "model_package").exists())
            self.assertEqual(model_builder._read_json(root / "failure_report.json")["failure_stage"], "modeler_package_build")

    def test_mechanical_stress_failure_repairs_once_before_review(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Backend repair stress test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_backend_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            sparse_scenarios = stub_scenario_cases()
            sparse_scenarios[1] = {**sparse_scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
            sparse_scenarios[2] = {**sparse_scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}

            approve_stub_spec(model_loop, model_id, "Build a package with incomplete scenario coverage.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), sparse_scenarios, stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_backend_repaired_package", return_value=(stub_package_files(main_py=stub_main_py_with_marker("backend stress repaired")), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage)) as backend_repair_call:
                    with patch.object(model_builder, "request_review_report", return_value=stub_review_report()) as review_call:
                        built = model_loop.build_model_package_record(model_id, "Build a package with incomplete scenario coverage.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(backend_repair_call.call_count, 1)
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertTrue(pipe["mechanical_stress_report"]["passed"])

    def test_backend_repair_exhausts_three_failed_attempts_and_skips_review(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Backend repair fail test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_backend_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            sparse_scenarios = stub_scenario_cases()
            sparse_scenarios[1] = {**sparse_scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
            sparse_scenarios[2] = {**sparse_scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}

            approve_stub_spec(model_loop, model_id, "Build a package that backend repair cannot fix.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), sparse_scenarios, stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_backend_repaired_package", return_value=(stub_package_files(main_py=stub_main_py_with_marker("still incomplete")), stub_base_inputs(), stub_input_schema(), sparse_scenarios, stub_modeler_self_check(), repair_usage)) as backend_repair_call:
                    with patch.object(model_builder, "request_review_report") as review_call:
                        built = model_loop.build_model_package_record(model_id, "Build a package that backend repair cannot fix.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(backend_repair_call.call_count, 3)
            self.assertEqual(review_call.call_count, 0)
            self.assertEqual(pipe["status"], "failed_checks")
            self.assertEqual(pipe["failure_code"], "mechanical_stress_failed")
            self.assertEqual(pipe["backend_repair_attempts_used"], 3)
            self.assertEqual(pipe["backend_repair_status"], "exhausted")
            self.assertFalse(pipe["publish_eligible"])

    def test_backend_repair_passing_still_allows_review_repair_round(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Backend plus review repair test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            backend_repair_usage = {"stage": "modeler_package_backend_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            review_repair_usage = {"stage": "modeler_package_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            sparse_scenarios = stub_scenario_cases()
            sparse_scenarios[1] = {**sparse_scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
            sparse_scenarios[2] = {**sparse_scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Review needs repair.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Review repair passed.")

            approve_stub_spec(model_loop, model_id, "Build a package with backend and review repairs.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), sparse_scenarios, stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_backend_repaired_package", return_value=(stub_package_files(main_py=stub_main_py_with_marker("backend repaired")), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), backend_repair_usage)) as backend_repair_call:
                    with patch.object(model_builder, "request_review_report", side_effect=[first_review, final_review]) as review_call:
                        with patch.object(model_builder, "request_repaired_package", return_value=(stub_package_files(main_py=stub_main_py_with_marker("review repaired")), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), review_repair_usage)) as review_repair_call:
                            built = model_loop.build_model_package_record(model_id, "Build a package with backend and review repairs.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(backend_repair_call.call_count, 1)
            self.assertEqual(review_call.call_count, 2)
            self.assertEqual(review_repair_call.call_count, 1)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertTrue(pipe["repair_plan"]["repair_attempted"])

    def test_backend_only_build_skips_review_agent_and_publish_gate(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Backend only build test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }

            approve_stub_spec(model_loop, model_id, "Build a backend-only package.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report") as review_call:
                    built = model_loop.build_model_package_record(
                        model_id,
                        "Build a backend-only package.",
                        run_review=False,
                    )

            pipe = built["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 0)
            self.assertEqual(pipe["status"], "checks_passed")
            self.assertTrue(pipe["validation_report"]["passed"])
            self.assertTrue(pipe["mechanical_stress_report"]["passed"])
            self.assertEqual(pipe["review_report"], {})
            self.assertEqual(pipe["review_execution_evidence"], {})
            self.assertFalse(pipe["repair_plan"])
            self.assertFalse(pipe["publish_eligible"])

            with self.assertRaisesRegex(RuntimeError, "Review Agent must approve"):
                model_loop.publish_model_record(model_id)

    def test_build_parser_failure_writes_failure_report(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Parser failure report test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approve_stub_spec(model_loop, model_id, "Build a malformed package.")
            with patch.object(model_builder, "request_model_package", side_effect=RuntimeError("OpenAI package build did not return base_inputs.")):
                with self.assertRaisesRegex(RuntimeError, "base_inputs"):
                    model_loop.build_model_package_record(model_id, "Build a malformed package.")

            workspace = model_loop.open_model_workspace(model_id)["workspace"]
            pipe = workspace["package_state"]
            self.assertEqual(pipe["status"], "build_failed")
            self.assertEqual(pipe["failure_code"], "parser_failed")
            self.assertEqual(pipe["failure_stage"], "modeler_package_build")
            self.assertEqual(pipe["failure_reasons"], ["OpenAI package build did not return base_inputs."])
            self.assertIn("retry_generation_or_revise_spec", pipe["next_actions"])
            root = model_builder.version_dir(model_id, pipe["version_id"])
            self.assertTrue((root / "failure_report.json").exists())

    def test_openai_backed_package_build_uses_returned_files_then_reruns_without_openai(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("OpenAI package product test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }

            approve_stub_spec(model_loop, model_id, "Build a custom operating model with an OpenAI-generated package.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)) as call:
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report()):
                    built = model_loop.build_model_package_record(
                        model_id,
                        "Build a custom operating model with an OpenAI-generated package.",
                    )

            self.assertEqual(call.call_count, 1)
            pipe = built["workspace"]["package_state"]
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(pipe["build_source"], "modeler_package_files")
            self.assertTrue(pipe["validation_report"]["passed"])

            version_id = built["model_manifest"]["current_version_id"]
            root = model_builder.version_dir(model_id, version_id)
            source = model_builder._read_json(root / "source_provenance.json")
            version = model_builder._read_json(root / "version_manifest.json")
            self.assertTrue(source["openai_called"])
            self.assertIn("model_package/model/main.py", source["generated_files"])
            self.assertEqual(source["model_spec"], "model_spec.json")
            self.assertTrue(source["model_spec_approved"])
            self.assertEqual(source["package_model_spec"], "model_package/spec/model_spec.json")
            self.assertEqual(source["self_check_report"], "model_package/reports/modeler_self_check.json")
            self.assertEqual(source["scenario_cases"], "model_package/inputs/scenarios.json")
            self.assertEqual(source["mechanical_stress_report"], "model_package/reports/mechanical_stress_report.json")
            self.assertTrue(source["code_interpreter_required"])
            self.assertGreaterEqual(len(version.get("openai_calls") or []), 1)
            output_files = sorted(
                str(path.relative_to(root / "model_package" / "outputs")).replace("\\", "/")
                for path in (root / "model_package" / "outputs").rglob("*")
                if path.is_file()
            )
            self.assertEqual(output_files, ["output.json"])
            report_files = sorted(
                str(path.relative_to(root / "model_package" / "reports")).replace("\\", "/")
                for path in (root / "model_package" / "reports").rglob("*")
                if path.is_file()
            )
            self.assertTrue({"mechanical_stress_report.json", "model_tests_report.json", "modeler_self_check.json", "review_report.json", "review_history.json", "repair_plan.json", "validation_report.json"}.issubset(set(report_files)))
            self.assertTrue(model_builder._read_json(root / "model_package" / "reports" / "modeler_self_check.json")["passed"])
            self.assertTrue(model_builder._read_json(root / "model_package" / "reports" / "mechanical_stress_report.json")["passed"])
            input_files = sorted(
                str(path.relative_to(root / "model_package" / "inputs")).replace("\\", "/")
                for path in (root / "model_package" / "inputs").rglob("*")
                if path.is_file()
            )
            self.assertEqual(input_files, ["base_case.json", "input_schema.json", "scenarios.json"])
            self.assertTrue((root / "model_package" / "spec" / "model_spec.json").exists())
            root_files = {
                str(path.relative_to(root)).replace("\\", "/")
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertNotIn("latest_output", version)

            published = model_loop.publish_model_record(model_id)
            inputs = published["workspace"]["canonical_inputs"]
            edited = {**inputs, "drivers": {**inputs["drivers"], "primary_value": inputs["drivers"]["primary_value"] * 1.25}}
            rerun = model_loop.execute_run(edited, model_id=model_id)
            self.assertFalse(rerun["metadata"]["openai_called"])
            self.assertTrue(rerun["package_state"]["published_rerun_uses_saved_package"])

    def test_regular_rerun_requires_submitted_inputs(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Input required rerun test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.4-mini",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }

            approve_stub_spec(model_loop, model_id, "Build a custom operating model.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report()):
                    model_loop.build_model_package_record(model_id, "Build a custom operating model.")
            model_loop.publish_model_record(model_id)

            with self.assertRaisesRegex(RuntimeError, "Inputs are required for regular rerun"):
                model_loop.execute_run(None, model_id=model_id)

    def test_review_repair_success_uses_one_modeler_repair_round(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Repair success test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Needs repair.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Repair passed.")

            approve_stub_spec(model_loop, model_id, "Build a model package that needs one repair.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", side_effect=[first_review, final_review]) as review_call:
                    with patch.object(model_builder, "request_repaired_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage)) as repair_call:
                        built = model_loop.build_model_package_record(model_id, "Build a model package that needs one repair.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 2)
            self.assertEqual(repair_call.call_count, 1)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertTrue(pipe["review_report"]["approved"])
            self.assertTrue(pipe["repair_plan"]["repair_attempted"])
            self.assertEqual(pipe["repair_plan"]["max_repair_attempts"], 3)
            root = model_builder.version_dir(model_id, pipe["version_id"])
            amendments_report = model_builder._read_json(root / "model_package" / "reports" / "required_amendments_report.json")
            self.assertEqual(amendments_report["executable_probe_count"], 1)
            self.assertEqual(amendments_report["amendments"][0]["issue_id"], "primary_result_does_not_decrease")
            self.assertEqual(pipe["review_history"]["rounds"][0]["required_amendments"][0]["issue_id"], "primary_result_does_not_decrease")

    def test_authoritative_review_repair_passes_gates_within_one_financial_round(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Mechanical correction inside review round", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            usage = {"stage": "test", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Finance repair required.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Finance repair approved.")
            approve_stub_spec(model_loop, model_id, "Build a package whose finance repair is admitted through the authoritative gate.")
            with patch.object(
                model_builder,
                "request_model_package",
                return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), usage),
            ), patch.object(
                model_builder, "request_review_report", side_effect=[first_review, final_review]
            ) as review_call, patch.object(
                model_builder,
                "request_repaired_package",
                return_value=stub_workspace_package_result(),
            ) as finance_repair_call, patch.object(
                model_builder,
                "request_backend_repaired_package",
                return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), usage),
            ) as mechanical_repair_call:
                built = model_loop.build_model_package_record(
                    model_id, "Build a package whose finance repair is admitted through the authoritative gate."
                )

            pipe = built["workspace"]["package_state"]
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(review_call.call_count, 2)
            self.assertEqual(finance_repair_call.call_count, 1)
            self.assertEqual(mechanical_repair_call.call_count, 0)
            self.assertEqual(pipe["review_history"]["repairs_used"], 1)
            self.assertEqual(len(pipe["review_history"]["rounds"]), 2)
            self.assertFalse(any(item.get("actor") == "deterministic_backend" for item in pipe["review_history"]["rounds"]))

    def test_budget_interrupted_review_resumes_from_persisted_next_repair(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Interrupted review resume test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_repair", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="First repair required.")
            second_review = stub_review_report(approved=False, repair_required=True, summary="Second repair required.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Second repair approved.")

            approve_stub_spec(model_loop, model_id, "Build a package whose review is interrupted by budget.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", side_effect=[first_review, second_review]):
                    with patch.object(
                        model_builder,
                        "request_repaired_package",
                        side_effect=[
                            (stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage),
                            RuntimeError("OpenAI budget blocked: test interruption"),
                        ],
                    ):
                        with self.assertRaisesRegex(RuntimeError, "budget blocked"):
                            model_loop.build_model_package_record(model_id, "Build a package whose review is interrupted by budget.")

            manifest = _model_registry.read_model(model_id)
            version_id = manifest["current_version_id"]
            root = model_builder.version_dir(model_id, version_id)
            interrupted_history = model_builder._read_json(root / "review_history.json")
            self.assertEqual(interrupted_history["repairs_used"], 1)
            self.assertEqual(len(interrupted_history["rounds"]), 2)
            self.assertEqual(model_builder._read_json(root / "failure_report.json")["failure_code"], "budget_blocked")

            with patch.object(
                model_builder,
                "request_repaired_package",
                return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage),
            ) as repair_call, patch.object(model_builder, "request_review_report", return_value=final_review) as review_call:
                resumed = model_loop.resume_interrupted_review_record(model_id)

            pipe = resumed["workspace"]["package_state"]
            self.assertEqual(repair_call.call_count, 1)
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertTrue(pipe["review_report"]["approved"])
            self.assertEqual(pipe["review_history"]["repairs_used"], 2)
            self.assertEqual(len(pipe["review_history"]["rounds"]), 3)
            self.assertEqual(pipe["version_id"], version_id)
            self.assertTrue((root / "pre_review_repair_package_round_2" / "model" / "main.py").exists())

    def test_reviewer_convergence_failure_retries_initial_review_without_modeler_repair(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Reviewer convergence retry test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            approved = stub_review_report(approved=True, repair_required=False, summary="Retry approved.")
            approve_stub_spec(model_loop, model_id, "Build a package whose reviewer needs a verdict-only turn.")
            with patch.object(
                model_builder,
                "request_model_package",
                return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage),
            ), patch.object(
                model_builder,
                "request_review_report",
                side_effect=RuntimeError("OpenAI function-tool loop ended before the model returned final JSON."),
            ):
                with self.assertRaisesRegex(RuntimeError, "function-tool loop ended"):
                    model_loop.build_model_package_record(model_id, "Build a package whose reviewer needs a verdict-only turn.")

            with patch.object(model_builder, "request_review_report", return_value=approved) as review_call, patch.object(
                model_builder, "request_repaired_package"
            ) as repair_call:
                resumed = model_loop.resume_interrupted_review_record(model_id)

            pipe = resumed["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(review_call.call_args.kwargs["attempt"], "initial_retry_1")
            self.assertEqual(repair_call.call_count, 0)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(pipe["review_history"]["repairs_used"], 0)

    def test_structural_review_failure_retries_reviewer_without_repair(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Structural review retry test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_repair", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Repair required.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Retry approved.")

            approve_stub_spec(model_loop, model_id, "Build a package whose reviewer misses structural evidence.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(
                    model_builder,
                    "request_review_report",
                    side_effect=[first_review, RuntimeError("Review Agent audit structural evidence failed: missing output read")],
                ), patch.object(
                    model_builder,
                    "request_repaired_package",
                    return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage),
                ):
                    with self.assertRaisesRegex(RuntimeError, "structural evidence failed"):
                        model_loop.build_model_package_record(model_id, "Build a package whose reviewer misses structural evidence.")

            with patch.object(model_builder, "request_review_report", return_value=final_review) as review_call, patch.object(model_builder, "request_repaired_package") as repair_call:
                resumed = model_loop.resume_interrupted_review_record(model_id)

            pipe = resumed["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(review_call.call_args.kwargs["attempt"], "after_repair_1_retry_1")
            self.assertEqual(repair_call.call_count, 0)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(pipe["review_history"]["repairs_used"], 1)
            self.assertEqual(len(pipe["review_history"]["rounds"]), 2)

    def test_complementary_saved_review_retries_are_admitted_without_another_call(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Cumulative structural evidence test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approved = stub_review_report(approved=True, repair_required=False, summary="Approved from complementary evidence.")
            first_raw = raw_review_response(approved)
            first_raw["_function_tool_calls"] = [
                call
                for call in first_raw["_function_tool_calls"]
                if call["tool_name"] != "read_package_artifact"
                or call["arguments"]["artifact_path"].startswith("model_package/model/")
            ]
            second_raw = raw_review_response(approved)
            second_raw["_function_tool_calls"] = [
                call
                for call in second_raw["_function_tool_calls"]
                if call["tool_name"] in {"execute_input_probe"}
                or (
                    call["tool_name"] == "read_package_artifact"
                    and call["arguments"]["artifact_path"].startswith("model_package/outputs/")
                )
            ]

            approve_stub_spec(model_loop, model_id, "Build a package with complementary review receipts.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result()), patch.object(
                    model_builder, "_post_openai", return_value=first_raw
                ):
                    with self.assertRaisesRegex(RuntimeError, "structural evidence failed"):
                        model_loop.build_model_package_record(model_id, "Build a package with complementary review receipts.")

                manifest = _model_registry.read_model(model_id)
                root = model_builder.version_dir(model_id, manifest["current_version_id"])
                with patch.object(model_builder, "_post_openai", return_value=second_raw):
                    with self.assertRaisesRegex(RuntimeError, "structural evidence failed"):
                        model_builder.request_review_report(
                            "Build a package with complementary review receipts.",
                            root,
                            attempt="initial_retry_1",
                        )

                with patch.object(model_builder, "request_review_report") as review_call:
                    resumed = model_loop.resume_interrupted_review_record(model_id)

            pipe = resumed["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 0)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertTrue(pipe["review_report"]["approved"])
            evidence = model_builder._read_json(root / "review_execution_evidence_initial_cumulative.json")
            self.assertTrue(evidence["structural_execution"]["passed"])
            self.assertFalse(evidence["openai_called_for_admission"])
            self.assertEqual(evidence["source_attempts"], ["initial", "initial_retry_1"])

    def test_review_repair_invalid_optional_probe_is_recorded_without_blocking_amendment(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Invalid repair target test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Needs repair.")
            first_review["required_amendments"][0]["verification_probe"]["input_path"] = "drivers.missing_value"
            approved_review = stub_review_report(approved=True, repair_required=False, summary="Approved after repair.")

            approve_stub_spec(model_loop, model_id, "Build a model package with invalid repair target.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", side_effect=[first_review, approved_review]):
                    with patch.object(model_builder, "request_repaired_package", return_value=stub_workspace_package_result()) as repair_call:
                        result = model_loop.build_model_package_record(model_id, "Build a model package with invalid repair target.")

            self.assertEqual(repair_call.call_count, 1)
            self.assertEqual(result["workspace"]["package_state"]["status"], "review_ready")
            evidence = first_review["required_amendments_report"]["report"]
            self.assertFalse(evidence["passed"])
            self.assertFalse(evidence["amendments"][0]["probe_valid"])
            self.assertIn("not in input_schema", evidence["amendments"][0]["probe_error"])

    def test_human_only_review_does_not_trigger_automatic_repair(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Human review target test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            review = stub_review_report(approved=False, repair_required=False, summary="Human decision needed.")
            review["findings"][0]["requires_human_decision"] = True
            review["human_questions"] = ["Confirm whether this assumption should be modeled."]
            review["required_amendments"] = [
                {
                    "issue_id": "confirm_assumption_scope",
                    "severity": "high",
                    "category": "spec_alignment",
                    "artifacts": ["model_package/spec/model_spec.json"],
                    "observed": "The assumption scope is unclear.",
                    "required_change": "Ask the human before changing the package.",
                    "acceptance_criteria": ["The human confirms the intended scope."],
                    "human_decision_required": True,
                }
            ]

            approve_stub_spec(model_loop, model_id, "Build a package requiring a human decision.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", return_value=review):
                    with patch.object(model_builder, "request_repaired_package") as repair_call:
                        built = model_loop.build_model_package_record(model_id, "Build a package requiring a human decision.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(repair_call.call_count, 0)
            self.assertEqual(pipe["status"], "review_failed")
            self.assertIn("human_decision_required", pipe["next_actions"])
            self.assertFalse(pipe["publish_eligible"])

    def test_modeler_amendment_creates_new_version_and_preserves_previous_package(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Amendment version test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approve_stub_spec(model_loop, model_id, "Build a package before amendment.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result(stub_main_py_with_marker("original package"))), patch.object(
                    model_builder, "request_amended_package", return_value=(
                        stub_model_spec(),
                        *stub_workspace_package_result(stub_main_py_with_marker("amended package"))[:5],
                        {"summary": "Updated package per user amendment.", "transport": "workspace_tool_loop"},
                        stub_workspace_package_result()[5],
                    )
                ), patch.object(model_builder, "request_review_report", side_effect=[stub_review_report(), stub_review_report(summary="Amended package approved.")]):
                    built = model_loop.build_model_package_record(model_id, "Build a package before amendment.")
                    previous_version_id = built["package_state"]["version_id"]
                    previous_root = model_builder.version_dir(model_id, previous_version_id)
                    previous_main_before = (previous_root / "model_package" / "model" / "main.py").read_text(encoding="utf-8")

                    amended = model_loop.amend_model_package_record(model_id, "Add a clearer output table.")

            pipe = amended["workspace"]["package_state"]
            new_version_id = pipe["version_id"]
            self.assertNotEqual(new_version_id, previous_version_id)
            self.assertEqual(pipe["previous_version_id"], previous_version_id)
            self.assertEqual(pipe["amendment_count"], 1)
            self.assertEqual(pipe["status"], "review_ready")
            self.assertEqual(pipe["change_summary"]["summary"], "Updated package per user amendment.")
            manifest = model_registry.read_model(model_id)
            self.assertEqual(manifest["current_version_id"], new_version_id)
            self.assertIn(previous_version_id, manifest["version_ids"])
            self.assertIn(new_version_id, manifest["version_ids"])

            previous_root = model_builder.version_dir(model_id, previous_version_id)
            new_root = model_builder.version_dir(model_id, new_version_id)
            self.assertEqual((previous_root / "model_package" / "model" / "main.py").read_text(encoding="utf-8"), previous_main_before)
            self.assertIn("original package", previous_main_before)
            self.assertIn("amended package", (new_root / "model_package" / "model" / "main.py").read_text(encoding="utf-8"))
            self.assertTrue((new_root / "previous_version_reference.json").exists())
            self.assertTrue((new_root / "change_summary.json").exists())
            previous_reference = model_builder._read_json(new_root / "previous_version_reference.json")
            self.assertEqual(previous_reference["previous_version_id"], previous_version_id)
            self.assertEqual(model_builder._read_json(new_root / "compiler_manifest.json")["compile_strategy"], "workspace_tool_loop")

            published = model_loop.publish_model_record(model_id)
            self.assertEqual(published["model_manifest"]["canonical_version_id"], new_version_id)
            inputs = published["workspace"]["canonical_inputs"]
            edited = {**inputs, "drivers": {**inputs["drivers"], "primary_value": inputs["drivers"]["primary_value"] * 1.1}}
            rerun = model_loop.execute_run(edited, model_id=model_id)
            self.assertFalse(rerun["metadata"]["openai_called"])
            self.assertTrue(rerun["package_state"]["published_rerun_uses_saved_package"])

    def test_modeler_amendment_reruns_scenario_coverage_gate_on_new_version(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Amendment scenario coverage test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            amend_usage = {"stage": "modeler_package_amendment", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            sparse_scenarios = stub_scenario_cases()
            sparse_scenarios[1] = {**sparse_scenarios[1], "input_overrides": {"drivers.primary_value": 80.0}}
            sparse_scenarios[2] = {**sparse_scenarios[2], "input_overrides": {"drivers.primary_value": 120.0}}

            approve_stub_spec(model_loop, model_id, "Build a package before amendment.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report()) as review_call:
                    built = model_loop.build_model_package_record(model_id, "Build a package before amendment.")
            previous_version_id = built["package_state"]["version_id"]

            with patch.object(
                model_builder,
                "request_amended_package",
                return_value=(
                    {**stub_model_spec(), "title": "Amended scenario coverage package"},
                    stub_package_files(main_py=stub_main_py_with_marker("amended incomplete scenario coverage")),
                    stub_base_inputs(),
                    stub_input_schema(),
                    sparse_scenarios,
                    stub_modeler_self_check(),
                    {"summary": "Changed package with incomplete scenario coverage."},
                    amend_usage,
                ),
            ):
                amended = model_loop.amend_model_package_record(model_id, "Change scenario design.")

            pipe = amended["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 1)
            self.assertEqual(pipe["status"], "review_failed")
            self.assertNotEqual(pipe["version_id"], previous_version_id)
            self.assertEqual(pipe["previous_version_id"], previous_version_id)
            manifest = model_registry.read_model(model_id)
            self.assertIn(previous_version_id, manifest["version_ids"])
            self.assertIn(pipe["version_id"], manifest["version_ids"])
            checks = {check["id"]: check for check in pipe["mechanical_stress_report"]["checks"]}
            self.assertFalse(checks["scenario_covers_editable_inputs"]["passed"])
            self.assertEqual(set(checks["scenario_covers_editable_inputs"]["missing_paths"]), {"drivers.change_rate", "settings.opening_value"})

    def test_failed_amendment_remains_attached_for_recovery(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Recoverable amendment failure", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approve_stub_spec(model_loop, model_id, "Build before a recoverable amendment failure.")
            amended_result = (
                stub_model_spec(),
                *stub_workspace_package_result(stub_main_py_with_marker("recoverable amendment"))[:5],
                {"summary": "Prepared a recoverable amendment.", "transport": "workspace_tool_loop"},
                stub_workspace_package_result()[5],
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch.object(
                model_builder, "request_model_package", return_value=stub_workspace_package_result()
            ), patch.object(
                model_builder, "request_amended_package", return_value=amended_result
            ), patch.object(
                model_builder,
                "request_review_report",
                side_effect=[stub_review_report(), RuntimeError("Review Agent finding is missing required fields: repair_instruction")],
            ):
                built = model_loop.build_model_package_record(model_id, "Build before a recoverable amendment failure.")
                previous_version_id = built["package_state"]["version_id"]
                with self.assertRaisesRegex(RuntimeError, "missing required fields"):
                    model_loop.amend_model_package_record(model_id, "Create a recoverable failed amendment.")

            manifest = model_registry.read_model(model_id)
            self.assertNotEqual(manifest["current_version_id"], previous_version_id)
            self.assertIn(manifest["current_version_id"], manifest["version_ids"])
            failed_root = model_builder.version_dir(model_id, manifest["current_version_id"])
            self.assertEqual(model_builder._read_json(failed_root / "failure_report.json")["failure_stage"], "review_agent_audit")

    def test_modeler_amendment_is_blocked_after_publish(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Amendment blocked after publish", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            approve_stub_spec(model_loop, model_id, "Build a package before publish.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report()):
                    model_loop.build_model_package_record(model_id, "Build a package before publish.")
            model_loop.publish_model_record(model_id)

            with self.assertRaisesRegex(RuntimeError, "Published models cannot be amended"):
                model_loop.amend_model_package_record(model_id, "Change the output.")

    def test_review_repair_denial_stops_after_three_rounds(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Repair denial test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            repair_usage = {"stage": "modeler_package_repair", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            first_review = stub_review_report(approved=False, repair_required=True, summary="Needs repair.")
            final_review = stub_review_report(approved=False, repair_required=True, summary="Still blocked.", failure_reasons=["Still blocked after repair."])

            approve_stub_spec(model_loop, model_id, "Build a model package with a blocker.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)):
                with patch.object(model_builder, "request_review_report", side_effect=[first_review, final_review, final_review, final_review]) as review_call:
                    with patch.object(model_builder, "request_repaired_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), repair_usage)) as repair_call:
                        built = model_loop.build_model_package_record(model_id, "Build a model package with a blocker.")

            pipe = built["workspace"]["package_state"]
            self.assertEqual(review_call.call_count, 4)
            self.assertEqual(repair_call.call_count, 3)
            self.assertEqual(pipe["status"], "review_failed")
            self.assertFalse(pipe["publish_eligible"])
            self.assertEqual(pipe["pre_publish_summary"]["status"], "failed")
            self.assertFalse(pipe["pre_publish_summary"]["can_publish"])
            self.assertEqual(pipe["review_failure_reasons"], ["Still blocked after repair."])
            self.assertEqual(pipe["failure_code"], "review_failed")
            self.assertEqual(pipe["failure_stage"], "review_agent_audit")
            self.assertEqual(pipe["failure_reasons"], ["Still blocked after repair."])
            self.assertIn("amend_or_stop", pipe["next_actions"])
            with self.assertRaisesRegex(RuntimeError, "Review Agent must approve"):
                model_loop.publish_model_record(model_id)

            amend_usage = {"stage": "modeler_package_amendment", "model": "gpt-5.4-mini", "usage": {}, "openai_called": True}
            with patch.object(
                model_builder,
                "request_amended_package",
                return_value=(
                    {**stub_model_spec(), "title": "Amended after review failure"},
                    stub_package_files(main_py=stub_main_py_with_marker("amended after review failure")),
                    stub_base_inputs(),
                    stub_input_schema(),
                    stub_scenario_cases(),
                    stub_modeler_self_check(),
                    {"summary": "Resolved final review failure."},
                    amend_usage,
                ),
            ):
                with patch.object(model_builder, "request_review_report", return_value=stub_review_report(summary="Amended package approved.")):
                    amended = model_loop.amend_model_package_record(model_id, "Resolve the Review Agent failure.")

            self.assertEqual(amended["workspace"]["package_state"]["status"], "review_ready")

    def test_agent_trace_records_no_repair_build_and_review_path(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Trace no repair test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            approve_stub_spec(model_loop, model_id, "Build a traced package.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result()), patch.object(
                    model_builder, "_post_openai", return_value=raw_review_response(stub_review_report())
                ):
                    built = model_loop.build_model_package_record(model_id, "Build a traced package.")

            pipe = built["workspace"]["package_state"]
            root = model_builder.version_dir(model_id, pipe["version_id"])
            trace = model_builder._read_json(root / "agent_trace.json")
            event_types = [event["event_type"] for event in trace["events"]]

            self.assertIn("backend_validation_result", event_types)
            self.assertIn("backend_mechanical_stress_result", event_types)
            self.assertIn("review_agent_audit_request", event_types)
            self.assertIn("review_agent_audit_raw_response", event_types)
            self.assertIn("review_agent_execution_evidence", event_types)
            self.assertIn("review_agent_audit_parsed_report", event_types)
            self.assertIn("final_review_status", event_types)
            self.assertTrue((root / "model_package" / "reports" / "review_execution_evidence.json").exists())
            self.assertEqual(pipe["review_execution_evidence"]["code_interpreter_call_count"], 1)
            self.assertFalse((root / "repair_context_round_1.json").exists())
            self.assertFalse((root / "raw_modeler_repair_response_round_1.json").exists())
            self.assertFalse((root / "pre_review_repair_package_round_1").exists())

    def test_agent_trace_records_repair_diagnostics_and_pre_repair_snapshot(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Trace repair test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            first_review = stub_review_report(approved=False, repair_required=True, summary="Needs repair.")
            final_review = stub_review_report(approved=True, repair_required=False, summary="Repair passed.")
            approve_stub_spec(model_loop, model_id, "Build a traced package needing repair.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result(stub_main_py_with_marker("original package"))), patch.object(
                    model_builder, "request_repaired_package", return_value=stub_workspace_package_result(stub_main_py_with_marker("repaired package"))
                ), patch.object(model_builder, "request_review_report", side_effect=[first_review, final_review]):
                    built = model_loop.build_model_package_record(model_id, "Build a traced package needing repair.")

            pipe = built["workspace"]["package_state"]
            root = model_builder.version_dir(model_id, pipe["version_id"])
            trace = model_builder._read_json(root / "agent_trace.json")
            event_types = [event["event_type"] for event in trace["events"]]

            self.assertTrue((root / "pre_review_repair_package_round_1" / "model" / "main.py").exists())
            self.assertTrue((root / "model_package" / "reports" / "review_history.json").exists())
            self.assertIn("original package", (root / "pre_review_repair_package_round_1" / "model" / "main.py").read_text(encoding="utf-8"))
            self.assertIn("repaired package", (root / "model_package" / "model" / "main.py").read_text(encoding="utf-8"))
            self.assertIn("pre_repair_package_snapshot", event_types)
            self.assertIn("review_required_amendments_report", event_types)

    def test_review_agent_requires_execution_evidence(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Trace missing review evidence test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            report_without_evidence = {
                "output": [{"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(stub_review_report())}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            approve_stub_spec(model_loop, model_id, "Build a package with missing review evidence.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result()), patch.object(
                    model_builder, "_post_openai", return_value=report_without_evidence
                ):
                    with self.assertRaisesRegex(RuntimeError, "structural evidence failed"):
                        model_loop.build_model_package_record(model_id, "Build a package with missing review evidence.")

            roots = sorted((model_builder.versions_root() / model_id).iterdir())
            root = roots[-1]
            evidence = model_builder._read_json(root / "model_package" / "reports" / "review_execution_evidence.json")
            self.assertEqual(evidence["code_interpreter_call_count"], 0)

    def test_review_agent_rejects_trivial_execution_evidence(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Trace weak review evidence test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            weak_review_response = {
                "output": [
                    {
                        "id": "ci_review_weak",
                        "type": "code_interpreter_call",
                        "status": "completed",
                        "code": "print('ready')",
                        "outputs": [{"type": "logs", "logs": "ready\n"}],
                    },
                    {"id": "msg_1", "type": "message", "content": [{"type": "output_text", "text": json.dumps(stub_review_report())}]},
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            }
            approve_stub_spec(model_loop, model_id, "Build a package with weak review evidence.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result()), patch.object(
                    model_builder, "_post_openai", return_value=weak_review_response
                ):
                    with self.assertRaisesRegex(RuntimeError, "structural evidence failed"):
                        model_loop.build_model_package_record(model_id, "Build a package with weak review evidence.")

            roots = sorted((model_builder.versions_root() / model_id).iterdir())
            root = roots[-1]
            evidence = model_builder._read_json(root / "model_package" / "reports" / "review_execution_evidence.json")
            self.assertFalse(evidence["structural_execution"]["passed"])
            candidate = model_builder._read_json(root / "model_package" / "reports" / "review_report_candidate_initial.json")
            self.assertEqual(candidate["summary"], "Review passed.")

    def test_workspace_repair_failure_preserves_pre_repair_snapshot(self) -> None:
        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _model_registry, _package_state = reload_app_runtime_modules()
            created = model_loop.create_model_record("Trace malformed repair test", "")
            model_id = created["model_manifest"]["model_id"]
            from backend.app import model_builder

            first_review = stub_review_report(approved=False, repair_required=True, summary="Needs repair.")
            approve_stub_spec(model_loop, model_id, "Build a malformed repair trace package.")
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch.object(model_builder, "request_model_package", return_value=stub_workspace_package_result(stub_main_py_with_marker("original package"))), patch.object(
                    model_builder, "request_review_report", return_value=first_review
                ), patch.object(model_builder, "request_repaired_package", side_effect=RuntimeError("Authoritative Modeler workspace exhausted 12 API turns")):
                    with self.assertRaisesRegex(RuntimeError, "workspace exhausted"):
                        model_loop.build_model_package_record(model_id, "Build a malformed repair trace package.")

            roots = sorted((model_builder.versions_root() / model_id).iterdir())
            root = roots[-1]
            self.assertTrue((root / "pre_review_repair_package_round_1" / "model" / "main.py").exists())
            trace = model_builder._read_json(root / "agent_trace.json")
            self.assertIn("pre_repair_package_snapshot", [event["event_type"] for event in trace["events"]])


if __name__ == "__main__":
    unittest.main()




