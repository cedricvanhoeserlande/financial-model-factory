from __future__ import annotations

import ast
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from backend.ai import budget as openai_budget, prompts, usage as openai_usage
from backend.app import model_config, model_trace, modeler_workspace, package_runtime
from backend.output import OUTPUT_VERSION, validate_output_contract
from backend.output.dashboard_contract import DASHBOARD_SPEC_VERSION, validate_dashboard_spec
from backend.output.dashboard_templates import DASHBOARD_TEMPLATE_CATALOG

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
OUTPUT_KEYS = [
    "output_version",
    "output_blocks",
    "dashboard_spec",
    "metadata",
]
PASS_MESSAGE = "Technical checks passed; business review required."
MODELER_COMPLETION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "changed_paths", "resolved_issue_ids", "gate_receipt"],
    "properties": {
        "summary": {"type": "string"},
        "changed_paths": {"type": "array", "items": {"type": "string"}},
        "resolved_issue_ids": {"type": "array", "items": {"type": "string"}},
        "gate_receipt": {"type": "string"},
    },
}
REQUIRED_PACKAGE_FILE_PATHS = {
    "model/main.py",
    "model/assumptions.py",
    "model/schedules/__init__.py",
    "model/outputs.py",
    "model/checks.py",
}
ALLOWED_MODEL_FILE_RE = re.compile(r"^model/(main|assumptions|outputs|checks)\.py$|^model/schedules/[A-Za-z_][A-Za-z0-9_]*\.py$")
PACKAGE_FILE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "content"],
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
}
OPENAI_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["package_files", "base_inputs", "input_schema", "scenario_cases", "modeler_self_check"],
    "properties": {
        "package_files": {
            "type": "array",
            "items": PACKAGE_FILE_SCHEMA,
            "description": "Complete generated package files under model/. Required paths are model/main.py, model/assumptions.py, model/schedules/__init__.py, model/outputs.py, and model/checks.py plus at least one model/schedules/<name>.py file.",
        },
        "base_inputs": {"type": "object", "description": "Top-level package inputs object. This must be a sibling of package_files, not embedded in Python source."},
        "input_schema": {"type": "object", "description": "Top-level input schema object with a fields array. This must be a sibling of package_files, not embedded in Python source."},
        "scenario_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "label", "description", "input_overrides"],
                "properties": {
                    "id": {"type": "string", "enum": ["base", "downside", "upside"]},
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                    "input_overrides": {"type": "object", "additionalProperties": True},
                },
            },
        },
        "modeler_self_check": {
            "type": "object",
            "additionalProperties": True,
            "required": ["passed", "summary", "checks"],
            "properties": {
                "passed": {"type": "boolean"},
                "summary": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}
DRAFT_PACKAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["package_files", "base_inputs", "input_schema", "scenario_cases"],
    "properties": {
        "package_files": OPENAI_SCHEMA["properties"]["package_files"],
        "base_inputs": OPENAI_SCHEMA["properties"]["base_inputs"],
        "input_schema": OPENAI_SCHEMA["properties"]["input_schema"],
        "scenario_cases": OPENAI_SCHEMA["properties"]["scenario_cases"],
    },
}
MODEL_TEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "label", "test_type", "execution_scope", "purpose", "logic_description", "evidence_expected", "repair_guidance"],
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "test_type": {"type": "string", "enum": ["run_check", "input_probe", "output_presence"]},
        "execution_scope": {"type": "string", "enum": ["case", "scenario_suite"]},
        "purpose": {"type": "string"},
        "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low", "advisory"]},
        "logic_description": {"type": "string"},
        "evidence_expected": {"type": "string"},
        "repair_guidance": {"type": "string"},
    },
}
MODEL_THESIS_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "label", "description"],
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "description": {"type": "string"},
    },
}
MODEL_THESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["thesis_version", "purpose", "modeled_objects", "assumptions", "outputs", "limitations"],
    "properties": {
        "thesis_version": {"type": "string"},
        "purpose": {"type": "string"},
        "modeled_objects": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
        "assumptions": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
        "policy_choices": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
        "outputs": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
        "exclusions": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
        "limitations": {"type": "array", "items": MODEL_THESIS_ITEM_SCHEMA},
    },
}
EQUATION_GRAPH_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "label", "description"],
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "description": {"type": "string"},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "formula": {"type": "string"},
    },
}
EQUATION_GRAPH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["graph_version", "nodes", "edges", "calculation_order", "key_tie_outs", "output_dependencies"],
    "properties": {
        "graph_version": {"type": "string"},
        "nodes": {"type": "array", "items": EQUATION_GRAPH_ITEM_SCHEMA},
        "edges": {"type": "array", "items": EQUATION_GRAPH_ITEM_SCHEMA},
        "calculation_order": {"type": "array", "items": {"type": "string"}},
        "key_tie_outs": {"type": "array", "items": EQUATION_GRAPH_ITEM_SCHEMA},
        "output_dependencies": {"type": "array", "items": EQUATION_GRAPH_ITEM_SCHEMA},
    },
}
MODEL_THEORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "model_thesis",
        "equation_graph",
        "model_tests",
    ],
    "properties": {
        "model_thesis": MODEL_THESIS_SCHEMA,
        "equation_graph": EQUATION_GRAPH_SCHEMA,
        "model_tests": {"type": "array", "items": MODEL_TEST_SCHEMA},
    },
}
AMENDMENT_PROBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["input_path", "changed_value", "output_path", "expected_behavior"],
    "properties": {
        "input_path": {"type": "string"},
        "changed_value": {"type": ["number", "string", "boolean"]},
        "output_path": {"type": "string"},
        "expected_behavior": {"type": "string", "enum": ["change", "increase", "decrease", "same", "not_null"]},
    },
}
REQUIRED_AMENDMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "issue_id",
        "severity",
        "category",
        "artifacts",
        "observed",
        "required_change",
        "acceptance_criteria",
        "human_decision_required",
    ],
    "properties": {
        "issue_id": {"type": "string"},
        "severity": {"type": "string", "enum": ["blocker", "high", "medium", "low", "advisory"]},
        "category": {"type": "string", "enum": ["model_logic", "test_coverage", "scenario_behavior", "output_definition", "presentation_data", "dashboard_layout", "assumption_contract", "spec_alignment", "label_or_explanation", "package_structure"]},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "observed": {"type": "string"},
        "required_change": {"type": "string"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "human_decision_required": {"type": "boolean"},
        "verification_probe": AMENDMENT_PROBE_SCHEMA,
    },
}
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "approved",
        "repair_required",
        "summary",
        "findings",
        "required_amendments",
        "repair_instructions",
        "human_questions",
        "failure_reasons",
    ],
    "properties": {
        "approved": {"type": "boolean"},
        "repair_required": {"type": "boolean"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "severity",
                    "area",
                    "claim_tested",
                    "symptom",
                    "root_cause",
                    "message",
                    "evidence",
                    "repair_instruction",
                    "requires_human_decision",
                ],
                "properties": {
                    "severity": {"type": "string"},
                    "area": {"type": "string"},
                    "claim_tested": {"type": "string"},
                    "symptom": {"type": "string"},
                    "root_cause": {"type": "string"},
                    "message": {"type": "string"},
                    "evidence": {"type": "object", "additionalProperties": True},
                    "repair_instruction": {"type": "string"},
                    "requires_human_decision": {"type": "boolean"},
                },
            },
        },
        "required_amendments": {"type": "array", "items": REQUIRED_AMENDMENT_SCHEMA},
        "repair_instructions": {"type": "array", "items": {"type": "string"}},
        "human_questions": {"type": "array", "items": {"type": "string"}},
        "failure_reasons": {"type": "array", "items": {"type": "string"}},
    },
}
REVIEW_ARTIFACT_READ_MAX_BYTES = 65_536
FAILURE_NEXT_ACTIONS = {
    "spec_failed": ["revise_scope_or_retry_spec_generation"],
    "build_failed": ["retry_generation_or_revise_spec"],
    "parser_failed": ["retry_generation_or_revise_spec"],
    "backend_validation_failed": ["amend_latest_valid_version_or_retry_generation"],
    "mechanical_stress_failed": ["amend_latest_valid_version_or_retry_generation"],
    "model_tests_failed": ["amend_latest_valid_version_or_retry_generation"],
    "review_failed": ["amend_or_stop"],
    "amendment_failed": ["retry_amendment_or_continue_from_previous_version"],
    "openai_transport_failed": ["retry_after_openai_service_recovers"],
    "budget_blocked": ["increase_budget_or_reduce_live_run_scope"],
    "quota_blocked": ["restore_api_billing_or_project_quota_then_resume"],
}
AMENDMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["model_spec", "package_files", "base_inputs", "input_schema", "scenario_cases", "modeler_self_check", "change_summary"],
    "properties": {
        "model_spec": {"type": "object", "additionalProperties": True},
        "package_files": OPENAI_SCHEMA["properties"]["package_files"],
        "base_inputs": {"type": "object"},
        "input_schema": OPENAI_SCHEMA["properties"]["input_schema"],
        "scenario_cases": OPENAI_SCHEMA["properties"]["scenario_cases"],
        "modeler_self_check": OPENAI_SCHEMA["properties"]["modeler_self_check"],
        "change_summary": {"type": "object", "additionalProperties": True},
    },
}

PRESENTATION_AGENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outputs_py", "dashboard_spec", "presentation_agent_report"],
    "properties": {
        "outputs_py": {"type": "string"},
        "dashboard_spec": {"type": "object", "additionalProperties": True},
        "presentation_agent_report": {
            "type": "object",
            "additionalProperties": False,
            "required": ["passed", "summary", "template_id", "checks", "issues", "data_lineage"],
            "properties": {
                "passed": {"type": "boolean"},
                "summary": {"type": "string"},
                "template_id": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "issues": {"type": "array", "items": {"type": "string"}},
                "data_lineage": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
        },
    },
}


def runtime_dir() -> Path:
    return Path(os.environ.get("MODEL_FACTORY_RUNTIME_DIR", DATA_DIR)).resolve()


def versions_root() -> Path:
    return runtime_dir() / "artifacts" / "model_versions"


def version_dir(model_id: str, version_id: str) -> Path:
    return versions_root() / model_id / version_id


def usage_ledger_path() -> Path:
    return runtime_dir() / "usage" / ("runtime_openai_usage.jsonl" if runtime_dir() == DATA_DIR.resolve() else "openai_usage.jsonl")


def budget_call_ledger_path() -> Path:
    return runtime_dir() / "usage" / "openai_budget_calls.jsonl"


def budget_suite_ledger_path() -> Path | None:
    value = os.environ.get("MODEL_FACTORY_BUDGET_SUITE_LEDGER_PATH", "").strip()
    return Path(value).resolve() if value else None


def is_model_package_version(manifest: dict[str, Any]) -> bool:
    version_id = str(manifest.get("current_version_id") or manifest.get("canonical_version_id") or "")
    if not version_id:
        return False
    compiler = _read_json(version_dir(str(manifest["model_id"]), version_id) / "compiler_manifest.json")
    return bool(compiler.get("model_package"))


def backend_check_repair_max_attempts() -> int:
    return model_config.attempt_policy_int("backend_check_repair_max_attempts", 1)


def mechanical_preflight_repair_max_attempts() -> int:
    """Mechanical repair calls allowed before deterministic/business review."""
    return model_config.attempt_policy_int("mechanical_preflight_repair_max_attempts", 2)


def build(manifest: dict[str, Any], prompt: str, *, approved_spec: dict[str, Any], run_review: bool = True) -> dict[str, Any]:
    clean_prompt = prompt.strip() or manifest.get("description") or manifest.get("name") or "Build a custom model package."
    version_id, root = ensure_version(manifest)
    try:
        package_files, inputs, schema, scenarios, self_check, usage_report = request_model_package(clean_prompt, root, approved_spec=approved_spec)
        write_package(root, manifest, clean_prompt, inputs, schema, scenarios, package_files, self_check, usage_report, approved_spec=approved_spec)
    except Exception as exc:
        code = _classify_generation_failure(exc, default="parser_failed")
        _write_failure_report(
            root,
            code=code,
            stage="modeler_package_build",
            message=str(exc),
            reasons=[str(exc)],
            status="build_failed",
            next_actions=FAILURE_NEXT_ACTIONS.get(code),
            failure_subcode=_classify_generation_failure_subcode(exc),
        )
        raise
    state = run_minimal(manifest, version_id, inputs, published=False)
    _record_workflow_stage(root, "post_self_check")
    if state.get("status") != "review_ready" and run_review and backend_check_repair_max_attempts() > 0:
        state = run_backend_check_repair_cycle(
            {**manifest, "current_version_id": version_id},
            clean_prompt,
            max_attempts=backend_check_repair_max_attempts(),
        )
    if state.get("status") == "review_ready" and not run_review:
        _append_final_trace(root, "checks_passed", "Backend deterministic checks and mechanical stress passed; Review Agent was not run.")
        state = _update_version_manifest(root, "checks_passed", latest_run_status="backend_checks_passed")
    elif state.get("status") == "review_ready":
        state = run_review_cycle({**manifest, "current_version_id": version_id}, clean_prompt)
    return read_state({**manifest, "current_version_id": version_id}, state_override=state)


def amend(manifest: dict[str, Any], message: str) -> dict[str, Any]:
    amendment_message = message.strip()
    if not amendment_message:
        raise RuntimeError("Amendment message is required.")
    if manifest.get("status") == "published":
        raise RuntimeError("Published models cannot be amended in place. Create a draft revision first.")
    previous_version_id = str(manifest.get("current_version_id") or "")
    if not previous_version_id:
        raise RuntimeError("Build a package before requesting a Modeler amendment.")
    previous_root = version_dir(str(manifest["model_id"]), previous_version_id)
    previous_state = _read_json(previous_root / "version_manifest.json")
    previous_status = str(previous_state.get("status") or "")
    if previous_status not in {"review_ready", "review_failed"}:
        raise RuntimeError("Modeler amendments are available only from the pre-publish workbench.")
    if not (previous_root / "model_package" / "model" / "main.py").exists():
        raise RuntimeError("Current package is missing generated code.")

    new_version_id = f"version_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    new_manifest = {**manifest, "current_version_id": new_version_id}
    _version_id, new_root = ensure_version(new_manifest)
    previous_context = _package_context(previous_root, str((_read_json(previous_root / "source_provenance.json").get("prompt") or manifest.get("description") or manifest.get("name") or "")))
    previous_context["previous_version_id"] = previous_version_id
    previous_context["previous_version_status"] = previous_status
    amendment_count = int(previous_state.get("amendment_count") or 0) + 1
    previous_reference = {
        "created_utc": _utc_now(),
        "previous_version_id": previous_version_id,
        "previous_version_status": previous_status,
        "amendment_count": amendment_count,
        "previous_artifacts": {
            "model_spec": f"../{previous_version_id}/model_spec.json",
            "package": f"../{previous_version_id}/model_package",
            "review_report": f"../{previous_version_id}/model_package/reports/review_report.json",
            "output": f"../{previous_version_id}/model_package/outputs/output.json",
        },
    }
    _write_json(new_root / "previous_version_reference.json", previous_reference)
    for artifact_name in ("model_thesis.json", "equation_graph.json", "model_tests.json"):
        previous_artifact = _read_json(previous_root / artifact_name)
        if previous_artifact:
            _write_json(new_root / artifact_name, previous_artifact)
    model_trace.append_event(
        new_root,
        "previous_version_reference",
        actor="backend",
        recipient="trace",
        stage="modeler_package_amendment",
        status="recorded",
        payload=previous_reference,
        artifacts={"previous_version_reference": "previous_version_reference.json"},
    )

    try:
        model_spec_payload, package_files, inputs, schema, scenarios, self_check, change_summary, usage_report = request_amended_package(
            amendment_message,
            new_root,
            previous_context,
        )
    except Exception as exc:
        code = _classify_generation_failure(exc, default="amendment_failed")
        _write_failure_report(
            new_root,
            code="amendment_failed" if code == "parser_failed" else code,
            stage="modeler_package_amendment",
            message=str(exc),
            reasons=[str(exc)],
            status="amendment_failed",
            next_actions=FAILURE_NEXT_ACTIONS.get(code, FAILURE_NEXT_ACTIONS.get("amendment_failed")),
            failure_subcode=_classify_generation_failure_subcode(exc),
        )
        raise
    approved_spec = {
        "status": "approved",
        "path": "model_spec.json",
        "source_prompt": amendment_message,
        "created_utc": _utc_now(),
        "updated_utc": _utc_now(),
        "model_spec": model_spec_payload,
        "approval": {"approved_utc": _utc_now(), "approved_by": "user_amendment_publish_gate"},
    }
    _write_json(new_root / "model_spec.json", approved_spec)
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        amendment_message,
        new_root,
        package_files,
        inputs,
        schema,
        scenarios,
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    usage_report = dict(usage_report)
    usage_report["presentation_agent_usage"] = presentation_usage
    _write_json(new_root / "change_summary.json", {"created_utc": _utc_now(), "amendment_message": amendment_message, **change_summary})
    write_package(new_root, new_manifest, amendment_message, inputs, schema, scenarios, package_files, self_check, usage_report, approved_spec=approved_spec)
    source = _read_json(new_root / "source_provenance.json")
    source["previous_version_id"] = previous_version_id
    source["amendment_request"] = amendment_message
    source["change_summary"] = "change_summary.json"
    _write_json(new_root / "source_provenance.json", source)
    state = _read_json(new_root / "version_manifest.json")
    state["previous_version_id"] = previous_version_id
    state["amendment_count"] = amendment_count
    state["amendment_status"] = "package_written"
    _write_json(new_root / "version_manifest.json", state)

    check_state = run_minimal(new_manifest, new_version_id, inputs, published=False)
    if check_state.get("status") == "review_ready":
        check_state = run_review_cycle(new_manifest, amendment_message)
    else:
        failed_report = {
            "approved": False,
            "repair_required": False,
            "summary": "Amended package failed backend checks before Review Agent audit.",
            "findings": [
                {
                    "severity": "blocker",
                    "area": "backend_checks",
                    "claim_tested": "Amended package must pass backend validation and mechanical stress before review.",
                    "message": "Amended package failed backend validation or mechanical stress.",
                    "evidence": {
                        "artifact": "model_package/reports/validation_report.json",
                        "note": "See validation_report.json and mechanical_stress_report.json for failed backend checks.",
                    },
                    "repair_instruction": "Request another Modeler amendment or stop before publish.",
                    "requires_human_decision": False,
                }
            ],
            "repair_instructions": [],
            "human_questions": [],
            "failure_reasons": ["Amended package failed backend checks before Review Agent audit."],
            "attempt": "amendment_backend_checks",
        }
        _write_json(new_root / "model_package" / "reports" / "review_report.json", failed_report)
        amendment_validation = _read_json(new_root / "model_package" / "reports" / "validation_report.json")
        _write_failure_report(
            new_root,
            code="backend_validation_failed" if amendment_validation.get("passed") is not True else "mechanical_stress_failed",
            stage="amendment_backend_checks",
            message="Amended package failed backend checks before Review Agent audit.",
            reasons=["Amended package failed backend checks before Review Agent audit."],
            status="review_failed",
            next_actions=["amend_or_stop"],
        )
        _append_final_trace(new_root, "review_failed", "Amended package failed backend checks before Review Agent audit.")
        check_state = _update_version_manifest(new_root, "review_failed", latest_run_status="amendment_checks_failed")
    final_state = _read_json(new_root / "version_manifest.json")
    final_state["previous_version_id"] = previous_version_id
    final_state["amendment_count"] = amendment_count
    final_state["amendment_status"] = "review_complete" if final_state.get("status") in {"review_ready", "review_failed"} else str(final_state.get("status") or "")
    _write_json(new_root / "version_manifest.json", final_state)
    return read_state(new_manifest, state_override=final_state)


def rerun(manifest: dict[str, Any], input_params: dict[str, Any]) -> dict[str, Any]:
    version_id = str(manifest.get("canonical_version_id") or manifest.get("current_version_id") or "")
    if not version_id:
        raise RuntimeError("Regular rerun requires a published generated package.")
    root = version_dir(str(manifest["model_id"]), version_id)
    if not root.exists():
        raise RuntimeError(f"Model version not found: {version_id}")
    ledger = usage_ledger_path()
    usage_count_before = _jsonl_record_count(ledger)
    package_dir = root / "model_package"
    previous_output = _read_json(package_dir / "outputs" / "output.json")
    base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
    inputs = resolve_inputs(root, input_params, allow_defaults=False)
    state = run_minimal({**manifest, "current_version_id": version_id}, version_id, inputs, published=True)
    state["resolved_input_params"] = inputs
    usage_count_after = _jsonl_record_count(ledger)
    latest_output = _read_json(package_dir / "outputs" / "output.json")
    validation = _read_json(package_dir / "reports" / "validation_report.json")
    model_tests = _read_json(package_dir / "reports" / "model_tests_report.json")
    inputs_changed = _stable_fingerprint(inputs) != _stable_fingerprint(base_inputs)
    output_changed = _stable_fingerprint(latest_output) != _stable_fingerprint(previous_output)
    call_delta = usage_count_after - usage_count_before
    output_openai_called = bool((latest_output.get("metadata") or {}).get("openai_called"))
    evidence = {
        "created_utc": _utc_now(),
        "canonical_version_id": version_id,
        "saved_entrypoint": "model_package/model/main.py",
        "usage_ledger_count_before": usage_count_before,
        "usage_ledger_count_after": usage_count_after,
        "openai_call_delta": call_delta,
        "openai_called": bool(call_delta or output_openai_called),
        "inputs_changed": inputs_changed,
        "output_changed": output_changed,
        "validation_passed": validation.get("passed") is True,
        "model_tests_passed": model_tests.get("passed") is True,
    }
    evidence["passed"] = bool(
        evidence["openai_called"] is False
        and evidence["validation_passed"]
        and evidence["model_tests_passed"]
        and (not inputs_changed or output_changed)
    )
    rerun_check = {"id": "published_rerun_no_openai", "passed": evidence["passed"], "evidence": evidence}
    validation["checks"] = [
        check for check in validation.get("checks") or [] if isinstance(check, dict) and check.get("id") != rerun_check["id"]
    ] + [rerun_check]
    validation["passed"] = bool(validation.get("passed") and evidence["passed"])
    _write_json(package_dir / "reports" / "validation_report.json", validation)
    _write_json(package_dir / "reports" / "rerun_execution_evidence.json", evidence)
    state["rerun_execution_evidence"] = evidence
    state["latest_run_status"] = "passed" if validation["passed"] else "backend_checks_failed"
    _write_json(root / "version_manifest.json", state)
    model_trace.append_event(
        root,
        "regular_rerun_execution_evidence",
        actor="backend",
        recipient="trace",
        stage="regular_rerun",
        status="passed" if evidence["passed"] else "failed",
        payload=evidence,
        artifacts={"rerun_execution_evidence": "model_package/reports/rerun_execution_evidence.json"},
    )
    return read_state({**manifest, "current_version_id": version_id}, state_override=state)


def mark_published(manifest: dict[str, Any]) -> dict[str, Any]:
    version_id = str(manifest.get("canonical_version_id") or manifest.get("current_version_id") or "")
    if not version_id:
        return {}
    root = version_dir(str(manifest["model_id"]), version_id)
    state = _update_version_manifest(root, "published")
    return read_state({**manifest, "current_version_id": version_id}, state_override=state)


def ensure_version(manifest: dict[str, Any]) -> tuple[str, Path]:
    version_id = str(manifest.get("current_version_id") or "")
    if not version_id:
        version_id = f"version_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    root = version_dir(str(manifest["model_id"]), version_id)
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "version_manifest.json").exists():
        _write_json(
            root / "version_manifest.json",
            {
                "version_id": version_id,
                "model_id": manifest["model_id"],
                "status": "draft",
                "created_utc": _utc_now(),
                "updated_utc": _utc_now(),
                "openai_calls": [],
                "artifacts": [],
            },
        )
    return version_id, root


def default_inputs() -> dict[str, Any]:
    return {
        "periods": [1, 2, 3, 4, 5],
        "drivers": {"primary_value": 100.0, "change_rate": 0.1},
        "settings": {"opening_value": 25.0},
    }


def input_schema() -> dict[str, Any]:
    fields = [
        _field("drivers.primary_value", "Primary value", "drivers", 100.0, "number"),
        _field("drivers.change_rate", "Change rate", "drivers", 0.1, "percent"),
        _field("settings.opening_value", "Opening value", "settings", 25.0, "number"),
    ]
    return {
        "type": "object",
        "groups": [
            {"id": "drivers", "label": "Drivers"},
            {"id": "settings", "label": "Settings"},
        ],
        "fields": fields,
        "compiler": {"strategy": "model_package", "review_required": True},
    }


def request_model_package(
    prompt: str,
    root: Path,
    *,
    approved_spec: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    model_thesis, equation_graph, model_tests, theory_usage = request_model_theory(prompt, root, approved_spec=approved_spec)
    package_files, base_inputs, schema, scenarios, self_check, workspace_usage = _request_workspace_package(
        prompt,
        root,
        stage="modeler_package_build",
        attempt="initial",
        prompt_id="model_package_build",
        seed_package=False,
        approved_spec=approved_spec,
        extra_context={
            "model_thesis": model_thesis,
            "equation_graph": equation_graph,
            "model_tests": model_tests,
            "output_contract": {"output_version": OUTPUT_VERSION, "required_keys": OUTPUT_KEYS},
            "review_language": PASS_MESSAGE,
        },
    )
    final_modeler_evidence = _evaluate_candidate_package(
        root,
        package_files=package_files,
        base_inputs=base_inputs,
        schema=schema,
        scenarios=scenarios,
        folder_name="pre_presentation_package",
    )
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt,
        root,
        package_files,
        base_inputs,
        schema,
        scenarios,
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    usage_report = {
        **workspace_usage,
        "staged_generation": True,
        "transport": "workspace_tool_loop",
        "staged_reports": [theory_usage, workspace_usage, presentation_usage],
        "model_theory_usage": theory_usage,
        "workspace_modeler_usage": workspace_usage,
        "presentation_agent_usage": presentation_usage,
        "presentation_agent_report": presentation_report,
    }
    return package_files, base_inputs, schema, scenarios, self_check, usage_report


def request_presentation_package(
    prompt: str,
    root: Path,
    *,
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    approved_spec: dict[str, Any] | None,
    model_thesis: dict[str, Any],
    equation_graph: dict[str, Any],
    model_tests: list[dict[str, Any]],
    deterministic_evidence: dict[str, Any],
    review_report: dict[str, Any] | None = None,
    repair_round: int = 0,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    if os.environ.get("MODEL_FACTORY_TEST_DISABLE_PRESENTATION_AGENT") == "1":
        runtime_dir = Path(os.environ.get("MODEL_FACTORY_RUNTIME_DIR") or "").resolve()
        expected_test_root = (ROOT_DIR / "tests" / ".tmp").resolve()
        if expected_test_root not in runtime_dir.parents and runtime_dir != expected_test_root:
            raise RuntimeError("Presentation Agent test bypass is restricted to isolated tests/.tmp runtimes.")
        return package_files, {"passed": True, "test_fixture_bypass": True}, {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "test_fixture_bypass": True,
        }
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for Presentation Agent assembly.")
    max_repairs = model_config.attempt_policy_int("presentation_agent_repair_max_attempts", 2)
    candidate_files = package_files
    failure_context: dict[str, Any] = {}
    usage_reports: list[dict[str, Any]] = []
    last_error = ""
    for attempt_index in range(max_repairs + 1):
        is_repair = attempt_index > 0 or bool(review_report)
        stage = "presentation_agent_repair" if is_repair else "presentation_agent_assembly"
        model = model_config.model_for_stage(stage)
        attempt = f"review_{repair_round}_presentation_{attempt_index}" if review_report else f"presentation_{attempt_index}"
        context = {
            "user_prompt": prompt,
            "approved_model_spec": approved_spec or {},
            "model_thesis": model_thesis,
            "equation_graph": equation_graph,
            "model_tests": model_tests,
            "package_files": candidate_files,
            "base_inputs": base_inputs,
            "input_schema": schema,
            "scenario_cases": scenarios,
            "deterministic_evidence": deterministic_evidence,
            "presentation_amendments": (review_report or {}).get("required_amendments") or [],
            "prior_presentation_failure": failure_context,
            "dashboard_contract": {
                "version": DASHBOARD_SPEC_VERSION,
                "templates": DASHBOARD_TEMPLATE_CATALOG,
                "data_rule": "All numerical values must come from output_blocks built from supplied schedules; widgets contain bindings only.",
            },
        }
        system_prompt = prompts.load_prompt("presentation_agent")
        body = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
            ],
            "text": {"format": {"type": "json_schema", "name": stage, "schema": PRESENTATION_AGENT_SCHEMA, "strict": False}},
            "reasoning": {"effort": "medium"},
            "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}],
            "tool_choice": "required",
            "include": ["code_interpreter_call.outputs"],
            "store": False,
            "metadata": {"model_id": root.parent.name, "version_id": root.name, "stage": stage, "run_id": f"{root.name}_{stage}_{attempt}"},
        }
        _write_json(root / f"presentation_context_{attempt}.json", {"system_prompt_id": "presentation_agent", "user_context": context, "request_body": body})
        model_trace.append_event(root, "presentation_agent_request", actor="backend", recipient="presentation_agent", stage=stage, attempt=attempt, status="sent", payload={"user_context": context})
        raw = _post_openai(api_key, body)
        _write_json(root / f"raw_presentation_agent_response_{attempt}.json", raw)
        usage = _record_usage(root, model, raw.get("usage") or {}, stage=stage, code_interpreter_call_count=len(_extract_code_interpreter_calls(raw)))
        usage_reports.append(usage)
        attempt_evidence: dict[str, Any] = {}
        try:
            outputs_py, returned_spec, report = _parse_presentation_response(raw)
            candidate_files = _replace_package_file(candidate_files, "model/outputs.py", outputs_py)
            evidence = _evaluate_candidate_package(
                root,
                package_files=candidate_files,
                base_inputs=base_inputs,
                schema=schema,
                scenarios=scenarios,
                folder_name=f"presentation_candidate_{attempt}",
            )
            attempt_evidence = evidence
            actual_spec = ((evidence.get("output") or {}).get("dashboard_spec") if isinstance(evidence.get("output"), dict) else None)
            if evidence.get("passed") is not True:
                raise RuntimeError("Presented package failed deterministic checks: " + str(evidence.get("failure_reasons") or evidence.get("error") or "unknown failure"))
            if actual_spec != returned_spec:
                raise RuntimeError("Presentation Agent returned dashboard_spec does not match executed outputs.py.")
            report = dict(report)
            report.update({"attempt": attempt, "repairs_used": attempt_index, "dashboard_validation": validate_dashboard_spec(actual_spec, (evidence.get("output") or {}).get("output_blocks"))})
            _write_json(root / "presentation_agent_report.json", report)
            model_trace.append_event(root, "presentation_agent_accepted", actor="backend", recipient="trace", stage=stage, attempt=attempt, status="passed", payload={"template_id": report.get("template_id"), "repairs_used": attempt_index})
            aggregate = dict(usage_reports[-1])
            aggregate.update({"staged_reports": usage_reports, "presentation_repairs_used": attempt_index})
            return candidate_files, report, aggregate
        except Exception as exc:
            last_error = str(exc)
            failure_context = {
                "attempt": attempt,
                "error": last_error,
                "deterministic_failure": _compact_mechanical_preflight_for_prompt(attempt_evidence),
            }
            model_trace.append_event(root, "presentation_agent_rejected", actor="backend", recipient="presentation_agent", stage=stage, attempt=attempt, status="failed", error=last_error)
            if attempt_index >= max_repairs:
                break
    raise RuntimeError(f"Presentation Agent failed after {max_repairs} repair attempt(s): {last_error}")


def _parse_presentation_response(raw: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    parsed = json.loads(_extract_response_text(raw))
    if not isinstance(parsed, dict):
        raise RuntimeError("Presentation Agent response must be an object.")
    outputs_py = parsed.get("outputs_py")
    dashboard_spec = parsed.get("dashboard_spec")
    report = parsed.get("presentation_agent_report")
    if not isinstance(outputs_py, str) or not outputs_py.strip() or "```" in outputs_py:
        raise RuntimeError("Presentation Agent outputs_py must be plain non-empty Python source.")
    if not isinstance(dashboard_spec, dict):
        raise RuntimeError("Presentation Agent dashboard_spec must be an object.")
    if not isinstance(report, dict) or report.get("passed") is not True:
        raise RuntimeError("Presentation Agent self-check did not pass.")
    if not _extract_code_interpreter_calls(raw):
        raise RuntimeError("Presentation Agent did not include Code Interpreter evidence.")
    return outputs_py.strip() + "\n", dashboard_spec, report


def _replace_package_file(package_files: list[dict[str, str]], path: str, content: str) -> list[dict[str, str]]:
    replaced = [{"path": item["path"], "content": content if item["path"] == path else item["content"]} for item in package_files]
    if not any(item["path"] == path for item in package_files):
        raise RuntimeError(f"Presentation Agent cannot replace missing package file: {path}")
    return _validate_package_files(replaced, source="Presentation Agent package_files")


def _evaluate_candidate_package(
    root: Path,
    *,
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    folder_name: str,
) -> dict[str, Any]:
    package_dir = root / folder_name
    try:
        if package_dir.exists():
            shutil.rmtree(package_dir)
        clean_files = _validate_package_files(package_files, source=f"{folder_name} package_files")
        _write_text(package_dir / "model" / "__init__.py", "")
        for file_record in clean_files:
            _write_text(package_dir / file_record["path"], file_record["content"])
        _write_json(package_dir / "inputs" / "input_schema.json", _validate_input_schema(schema, base_inputs, source=f"{folder_name} input_schema"))
        _write_json(package_dir / "inputs" / "base_case.json", base_inputs)
        _write_json(package_dir / "inputs" / "scenarios.json", {"scenario_cases": _parse_scenario_cases(scenarios, source=f"{folder_name} scenario_cases")})
        validation, output = validate_package(package_dir, base_inputs)
        stress = run_mechanical_stress(package_dir)
        tests = run_model_tests(package_dir, output, stress, active_inputs=base_inputs)
        reasons = _backend_failure_reasons(validation, stress, tests)
        return {"passed": validation.get("passed") is True and stress.get("passed") is True and tests.get("passed") is True, "validation_report": validation, "mechanical_stress_report": stress, "model_tests_report": tests, "output": output, "failure_reasons": reasons}
    except Exception as exc:
        return {"passed": False, "error": str(exc), "failure_reasons": [str(exc)]}


def request_model_theory(
    prompt: str,
    root: Path,
    *,
    approved_spec: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for model theory planning.")
    model = model_config.model_for_stage("modeler_model_theory")
    stage = "modeler_model_theory"
    run_id = f"{root.name}_{stage}"
    system_prompt = prompts.load_prompt("model_theory")
    context = {
        "user_prompt": prompt,
        "approved_model_spec": approved_spec or {},
        "output_instruction": "Return model_thesis, equation_graph, and model_tests only. Do not create Python code in this step.",
    }
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": MODEL_THEORY_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": run_id,
        },
    }
    model_trace.append_event(
        root,
        "modeler_model_theory_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        status="sent",
        payload={"system_prompt_id": "model_theory", "user_context": context, "request_body": body},
    )
    try:
        raw = _post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            root,
            "modeler_model_theory_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            status="error",
            error=str(exc),
        )
        raise
    model_trace.append_event(
        root,
        "modeler_model_theory_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        status="received",
        payload=raw,
    )
    _write_json(root / "raw_modeler_model_theory_response.json", raw)
    model_thesis, equation_graph, model_tests = parse_model_theory(json.loads(_extract_response_text(raw)))
    _write_model_theory_artifacts(root, model_thesis, equation_graph, model_tests)
    model_trace.append_event(
        root,
        "modeler_model_theory_parsed",
        actor="backend",
        recipient="trace",
        stage=stage,
        status="parsed",
        payload={"model_test_ids": [test["id"] for test in model_tests]},
        artifacts={"model_thesis": "model_thesis.json", "equation_graph": "equation_graph.json", "model_tests": "model_tests.json"},
    )
    usage_report = _record_usage(root, model, raw.get("usage") or {}, stage=stage)
    return model_thesis, equation_graph, model_tests, usage_report


def request_draft_package(
    prompt: str,
    root: Path,
    *,
    approved_spec: dict[str, Any] | None,
    model_thesis: dict[str, Any],
    equation_graph: dict[str, Any],
    model_tests: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for package builds.")
    model = model_config.model_for_stage("modeler_package_build")
    stage = "modeler_package_build"
    run_id = f"{root.name}_{stage}"
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": prompts.load_prompt("model_package_build"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_prompt": prompt,
                        "approved_model_spec": approved_spec or {},
                        "model_thesis": model_thesis,
                        "equation_graph": equation_graph,
                        "model_tests": model_tests,
                        "example_input_shape": default_inputs(),
                        "output_contract": {
                            "output_version": OUTPUT_VERSION,
                            "required_keys": OUTPUT_KEYS,
                            "required_blocks": "output_blocks must be a non-empty array of generic output data-library blocks.",
                            "dashboard_spec": "display intent object, not strict widget/data wiring",
                        },
                        "review_language": PASS_MESSAGE,
                    },
                    separators=(",", ":"),
                ),
            },
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": DRAFT_PACKAGE_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": run_id,
        },
    }
    model_trace.append_event(
        root,
        "modeler_build_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        status="sent",
        payload={
            "request_body": body,
            "approved_model_spec_path": "model_spec.json" if approved_spec else "",
            "model_thesis_path": "model_thesis.json",
            "equation_graph_path": "equation_graph.json",
            "model_tests_path": "model_tests.json",
        },
    )
    try:
        raw = _post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            root,
            "modeler_build_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            status="error",
            error=str(exc),
        )
        raise
    model_trace.append_event(
        root,
        "modeler_build_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        status="received",
        payload=raw,
    )
    package_files, base_inputs, schema, scenarios = _parse_openai_draft_package_response(raw)
    usage_report = _record_usage(root, model, raw.get("usage") or {}, stage=stage)
    return package_files, base_inputs, schema, scenarios, usage_report


def request_self_checked_package(
    prompt: str,
    root: Path,
    *,
    approved_spec: dict[str, Any] | None,
    model_thesis: dict[str, Any],
    equation_graph: dict[str, Any],
    model_tests: list[dict[str, Any]],
    draft_package: dict[str, Any],
    initial_preflight: dict[str, Any] | None = None,
    artifact_namespace: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for package self-check.")
    system_prompt = prompts.load_prompt("model_package_self_check")
    candidate_package = draft_package
    preflight = dict(initial_preflight or {})
    max_repairs = mechanical_preflight_repair_max_attempts()
    history: list[dict[str, Any]] = []
    usage_reports: list[dict[str, Any]] = []

    for attempt_index in range(max_repairs + 1):
        is_repair = attempt_index > 0
        stage = "modeler_package_preflight_repair" if is_repair else "modeler_package_self_check"
        model = model_config.model_for_stage(stage)
        attempt_label = f"preflight_repair_{attempt_index}" if is_repair else "self_check"
        context = {
            "user_prompt": prompt,
            "approved_model_spec": approved_spec or {},
            "model_thesis": model_thesis,
            "equation_graph": equation_graph,
            "model_tests": model_tests,
            "draft_package": candidate_package,
            "mechanical_preflight": _compact_mechanical_preflight_for_prompt(preflight),
            "mechanical_repair_history": history,
            "mechanical_repairs_used": attempt_index,
            "mechanical_repairs_allowed": max_repairs,
            "output_contract": {
                "output_version": OUTPUT_VERSION,
                "required_keys": OUTPUT_KEYS,
                "required_blocks": "output_blocks must be a non-empty array of generic output data-library blocks.",
                "dashboard_spec": "display intent object, not strict widget/data wiring",
            },
            "output_instruction": "Return the final full package after executing it and correcting every mechanical preflight error.",
        }
        body = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
            ],
            "text": {"format": {"type": "json_schema", "name": stage, "schema": OPENAI_SCHEMA, "strict": False}},
            "reasoning": {"effort": "medium"},
            "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}],
            "tool_choice": "required",
            "include": ["code_interpreter_call.outputs"],
            "store": False,
            "metadata": {
                "model_id": root.parent.name,
                "version_id": root.name,
                "stage": stage,
                "run_id": f"{root.name}_{stage}_{attempt_index}",
            },
        }
        namespace_suffix = f"_{artifact_namespace}" if artifact_namespace else ""
        suffix = namespace_suffix if not is_repair else f"{namespace_suffix}_preflight_repair_{attempt_index}"
        context_name = f"modeler_self_check_context{suffix}.json"
        raw_name = f"raw_modeler_self_check_response{suffix}.json"
        _write_json(root / context_name, {"system_prompt_id": "model_package_self_check", "system_prompt": system_prompt, "user_context": context, "request_body": body})
        model_trace.append_event(
            root,
            "modeler_self_check_request",
            actor="backend",
            recipient="modeler",
            stage=stage,
            attempt=attempt_label,
            status="sent",
            payload={"system_prompt_id": "model_package_self_check", "user_context": context, "request_body": body},
            artifacts={"self_check_context": context_name},
        )
        try:
            raw = _post_openai(api_key, body)
        except Exception as exc:
            model_trace.append_event(root, "modeler_self_check_raw_response", actor="modeler", recipient="backend", stage=stage, attempt=attempt_label, status="error", error=str(exc))
            raise
        _write_json(root / raw_name, raw)
        model_trace.append_event(
            root,
            "modeler_self_check_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            attempt=attempt_label,
            status="received",
            payload=raw,
            artifacts={"raw_modeler_self_check_response": raw_name},
        )
        code_calls = _extract_code_interpreter_calls(raw)
        usage_reports.append(_record_usage(root, model, raw.get("usage") or {}, stage=stage, code_interpreter_call_count=len(code_calls)))
        try:
            package_files, base_inputs, schema, scenarios, self_check = _parse_openai_build_response(raw)
        except Exception as exc:
            candidate_package, diagnostic = _repairable_package_candidate(raw, fallback=candidate_package, parser_error=exc)
            history.append({"attempt": attempt_label, "passed": False, "diagnostic": diagnostic})
            history_name = f"mechanical_preflight_history{namespace_suffix}.json"
            _write_json(root / history_name, {"max_repair_attempts": max_repairs, "attempts": history})
            model_trace.append_event(root, "mechanical_preflight_failed", actor="backend", recipient="modeler", stage=stage, attempt=attempt_label, status="failed", payload=diagnostic)
            if attempt_index >= max_repairs:
                raise RuntimeError(f"Mechanical preflight repair exhausted after {max_repairs} repair attempts: {diagnostic['error']}") from exc
            preflight = diagnostic
            continue

        history.append({"attempt": attempt_label, "passed": True, "diagnostic": {"error": ""}})
        history_name = f"mechanical_preflight_history{namespace_suffix}.json"
        _write_json(root / history_name, {"max_repair_attempts": max_repairs, "repairs_used": attempt_index, "passed": True, "attempts": history})
        model_trace.append_event(root, "modeler_self_check_parsed_package", actor="backend", recipient="trace", stage=stage, attempt=attempt_label, status="parsed", payload=_package_summary(package_files, base_inputs, schema, scenarios, self_check))
        usage_report = dict(usage_reports[-1])
        usage_report.update({"mechanical_preflight_repairs_used": attempt_index, "mechanical_preflight_history": history, "mechanical_preflight_history_path": history_name, "mechanical_preflight_usage": usage_reports})
        return package_files, base_inputs, schema, scenarios, self_check, usage_report

    raise RuntimeError("Mechanical preflight repair loop ended unexpectedly.")


def _compact_mechanical_preflight_for_prompt(preflight: dict[str, Any]) -> dict[str, Any]:
    """Keep actionable failures while excluding bulky successful run payloads from AI context."""
    if not isinstance(preflight, dict):
        return {}
    compact = {
        key: preflight.get(key)
        for key in (
            "available",
            "validation_passed",
            "mechanical_stress_passed",
            "model_tests_passed",
            "gate_pass_count",
            "passed",
            "error",
            "failure_code",
            "failure_reasons",
        )
        if key in preflight
    }
    for report_key in ("validation_report", "mechanical_stress_report", "model_tests_report"):
        report = preflight.get(report_key)
        if not isinstance(report, dict):
            continue
        checks = report.get("checks") if isinstance(report.get("checks"), list) else []
        compact_checks = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            if check.get("passed") is True:
                compact_checks.append({"id": check.get("id"), "passed": True})
            else:
                compact_checks.append(check)
        compact[report_key] = {
            key: report.get(key)
            for key in ("passed", "message", "error", "failure_reasons")
            if key in report
        }
        compact[report_key]["checks"] = compact_checks
    return compact


def request_repaired_package(
    prompt: str,
    root: Path,
    review_report: dict[str, Any],
    *,
    repair_round: int,
    review_history: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for package repair.")
    modeler_review_report = _modeler_scope_review_report(review_report)
    active_repair_prompt = (
        "The current task is to resolve every non-human Review Agent required amendment below. "
        "The original user prompt is background context only and must not displace these amendments. "
        "Do not spend a repair round on an issue that the current review says is already resolved.\n\n"
        + json.dumps(modeler_review_report, separators=(",", ":"), default=str)
    )
    extra_context = {
        "active_task": "review_required_amendments",
        "active_task_priority": "Resolve every listed required_amendment before any background user request.",
        "original_user_prompt": prompt,
        "review_report": modeler_review_report,
        "required_amendments": modeler_review_report.get("required_amendments") or [],
        "required_amendments_report": review_report.get("required_amendments_report") or {},
        "review_history": review_history,
        "repair_round": repair_round,
        "max_repair_rounds": _review_repair_max_attempts(),
    }
    base_attempt = f"repair_{repair_round}"
    attempt = base_attempt
    seed_dir: Path | None = None
    continuation_limit = model_config.ai_runtime_int("modeler_workspace_stage_continuation_max_attempts", 1)
    continuation_index = 0
    base_workspace = root / "modeler_workspaces" / f"modeler_package_repair_{base_attempt}"
    prior_failure = _read_json(root / "failure_report.json")
    if (
        base_workspace.is_dir()
        and str(prior_failure.get("failure_stage") or "") == "modeler_package_repair"
        and "exhausted" in str(prior_failure.get("message") or "").lower()
        and "api turns" in str(prior_failure.get("message") or "").lower()
    ):
        continuation_index = 1
        attempt = f"{base_attempt}_continuation_{continuation_index}"
        seed_dir = base_workspace

    while True:
        try:
            package_files, base_inputs, schema, scenarios, self_check, repair_usage = _request_workspace_package(
                active_repair_prompt,
                root,
                stage="modeler_package_repair",
                attempt=attempt,
                prompt_id="model_package_repair",
                seed_package=True,
                seed_package_dir=seed_dir,
                extra_context={
                    **extra_context,
                    "workspace_continuation_index": continuation_index,
                    "workspace_continuation_reason": "stage_turn_limit" if continuation_index else "",
                },
            )
            break
        except RuntimeError as exc:
            if (
                continuation_index >= continuation_limit
                or "exhausted" not in str(exc).lower()
                or "api turns" not in str(exc).lower()
            ):
                raise
            current_workspace = root / "modeler_workspaces" / f"modeler_package_repair_{attempt}"
            if not current_workspace.is_dir():
                raise
            continuation_index += 1
            seed_dir = current_workspace
            attempt = f"{base_attempt}_continuation_{continuation_index}"
    package_files, base_inputs, schema, scenarios, scope_report = _scope_modeler_review_repair(
        root,
        package_files=package_files,
        base_inputs=base_inputs,
        schema=schema,
        scenarios=scenarios,
        review_report=modeler_review_report,
        repair_round=repair_round,
    )
    self_check = dict(self_check)
    self_check["repair_scope_report"] = scope_report
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt, root, package_files, base_inputs, schema, scenarios, review_report=review_report, repair_round=repair_round
    )
    self_check["presentation_agent_report"] = presentation_report
    usage_report = dict(repair_usage)
    usage_report["presentation_agent_usage"] = presentation_usage
    usage_report["staged_reports"] = [repair_usage, presentation_usage]
    return package_files, base_inputs, schema, scenarios, self_check, usage_report

    # Historical whole-package transport remains below only for reading/replaying
    # legacy runtime records; new Modeler repair calls return above.
    model = model_config.model_for_stage("modeler_package_repair")
    stage = "modeler_package_repair"
    run_id = f"{root.name}_{stage}"
    context = _package_context(root, prompt)
    modeler_review_report = _modeler_scope_review_report(review_report)
    context["review_report"] = modeler_review_report
    context["required_amendments"] = modeler_review_report.get("required_amendments") or []
    context["required_amendments_report"] = review_report.get("required_amendments_report") or {}
    context["review_history"] = review_history
    context["repair_round"] = repair_round
    context["max_repair_rounds"] = _review_repair_max_attempts()
    system_prompt = prompts.load_prompt("model_package_repair")
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": OPENAI_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}],
        "tool_choice": "required",
        "include": ["code_interpreter_call.outputs"],
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": run_id,
        },
    }
    repair_context = {
        "system_prompt_id": "model_package_repair",
        "system_prompt": system_prompt,
        "user_context": context,
        "request_body": body,
    }
    _write_json(root / f"repair_context_round_{repair_round}.json", repair_context)
    model_trace.append_event(
        root,
        "modeler_repair_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        attempt=f"repair_{repair_round}",
        status="sent",
        payload=repair_context,
        artifacts={"repair_context": f"repair_context_round_{repair_round}.json"},
    )
    try:
        raw = _post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            root,
            "modeler_repair_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            attempt=f"repair_{repair_round}",
            status="error",
            error=str(exc),
        )
        raise
    _write_json(root / f"raw_modeler_repair_response_round_{repair_round}.json", raw)
    model_trace.append_event(
        root,
        "modeler_repair_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        attempt=f"repair_{repair_round}",
        status="received",
        payload=raw,
        artifacts={"raw_modeler_repair_response": f"raw_modeler_repair_response_round_{repair_round}.json"},
    )
    repair_usage = _record_usage(
        root,
        model,
        raw.get("usage") or {},
        stage=stage,
        code_interpreter_call_count=len(_extract_code_interpreter_calls(raw)),
    )
    mechanical_usage: dict[str, Any] | None = None
    try:
        package_files, base_inputs, schema, scenarios, self_check = _parse_openai_build_response(raw)
    except Exception as exc:
        fallback = {
            "package_files": context.get("package_files") or [],
            "base_inputs": context.get("base_inputs") or {},
            "input_schema": context.get("input_schema") or {},
            "scenario_cases": context.get("scenario_cases") or [],
        }
        candidate, diagnostic = _repairable_package_candidate(raw, fallback=fallback, parser_error=exc)
        model_trace.append_event(
            root,
            "modeler_repair_mechanical_recovery_required",
            actor="backend",
            recipient="modeler",
            stage=stage,
            attempt=f"repair_{repair_round}",
            status="failed",
            payload=diagnostic,
        )
        package_files, base_inputs, schema, scenarios, self_check, mechanical_usage = request_self_checked_package(
            prompt,
            root,
            approved_spec=context.get("approved_model_spec") or {},
            model_thesis=context.get("model_thesis") or {},
            equation_graph=context.get("equation_graph") or {},
            model_tests=context.get("model_tests") or [],
            draft_package=candidate,
            initial_preflight=diagnostic,
            artifact_namespace=f"review_repair_{repair_round}",
        )
    package_files, base_inputs, schema, scenarios, scope_report = _scope_modeler_review_repair(
        root,
        package_files=package_files,
        base_inputs=base_inputs,
        schema=schema,
        scenarios=scenarios,
        review_report=modeler_review_report,
        repair_round=repair_round,
    )
    self_check = dict(self_check)
    self_check["repair_scope_report"] = scope_report
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt,
        root,
        package_files,
        base_inputs,
        schema,
        scenarios,
        review_report=review_report,
        repair_round=repair_round,
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    model_trace.append_event(
        root,
        "modeler_repair_parsed_package",
        actor="backend",
        recipient="trace",
        stage=stage,
        attempt=f"repair_{repair_round}",
        status="parsed",
        payload=_package_summary(package_files, base_inputs, schema, scenarios, self_check),
    )
    usage_report = dict(repair_usage)
    if mechanical_usage is not None:
        usage_report["mechanical_recovery_usage"] = mechanical_usage
    usage_report["presentation_agent_usage"] = presentation_usage
    staged_reports = [repair_usage]
    if mechanical_usage is not None:
        staged_reports.extend(mechanical_usage.get("mechanical_preflight_usage") or [mechanical_usage])
    staged_reports.append(presentation_usage)
    usage_report["staged_reports"] = staged_reports
    return package_files, base_inputs, schema, scenarios, self_check, usage_report


def _present_replacement_package(
    prompt: str,
    root: Path,
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    *,
    review_report: dict[str, Any] | None = None,
    repair_round: int = 0,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    if not model_config.role_enabled("presentation_agent"):
        report = {
            "passed": False,
            "blocking": False,
            "status": "wip_disabled",
            "summary": "Presentation Agent is disabled while underlying model correctness is validated.",
            "review_scope": "out_of_scope",
        }
        usage = {
            "stage": "presentation_agent_disabled",
            "openai_called": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        }
        _write_json(root / "presentation_agent_report.json", report)
        model_trace.append_event(
            root,
            "presentation_agent_disabled",
            actor="backend",
            recipient="trace",
            stage="presentation_agent_assembly",
            status="wip_disabled",
            payload=report,
        )
        return package_files, report, usage
    thesis_artifact = _read_json(root / "model_thesis.json")
    graph_artifact = _read_json(root / "equation_graph.json")
    tests_artifact = _read_json(root / "model_tests.json")
    evidence = _evaluate_candidate_package(
        root,
        package_files=package_files,
        base_inputs=base_inputs,
        schema=schema,
        scenarios=scenarios,
        folder_name=f"pre_presentation_repair_{repair_round}",
    )
    if evidence.get("passed") is not True:
        return package_files, {
            "passed": False,
            "status": "deferred_until_backend_repair",
            "failure_reasons": evidence.get("failure_reasons") or [evidence.get("error") or "Deterministic checks failed."],
        }, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
    presentation_review_report = _presentation_scope_review_report(review_report)
    return request_presentation_package(
        prompt,
        root,
        package_files=package_files,
        base_inputs=base_inputs,
        schema=schema,
        scenarios=scenarios,
        approved_spec=_read_json(root / "model_spec.json"),
        model_thesis=thesis_artifact.get("model_thesis") if isinstance(thesis_artifact.get("model_thesis"), dict) else thesis_artifact,
        equation_graph=graph_artifact.get("equation_graph") if isinstance(graph_artifact.get("equation_graph"), dict) else graph_artifact,
        model_tests=tests_artifact.get("model_tests") if isinstance(tests_artifact.get("model_tests"), list) else [],
        deterministic_evidence=evidence,
        review_report=presentation_review_report,
        repair_round=repair_round,
    )


def _presentation_scope_review_report(review_report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(review_report, dict) or not review_report:
        return None
    presentation_categories = {"presentation_data", "dashboard_layout"}
    amendments = [
        dict(item)
        for item in review_report.get("required_amendments") or []
        if isinstance(item, dict) and item.get("category") in presentation_categories
    ]
    return {
        "attempt": review_report.get("attempt"),
        "summary": review_report.get("summary") or "",
        "required_amendments": amendments,
        "repair_instructions": [
            str(item.get("required_change") or "") for item in amendments if str(item.get("required_change") or "").strip()
        ],
        "presentation_scope_only": True,
    }


def _modeler_loop_limits() -> dict[str, int]:
    return {
        "stage_turns": model_config.ai_runtime_int("modeler_workspace_max_turns_per_stage", 24),
        "total_turns": model_config.ai_runtime_int("modeler_workspace_max_total_turns", 160),
        "total_tools": model_config.ai_runtime_int("modeler_workspace_max_total_tool_calls", 200),
        "wall_seconds": model_config.ai_runtime_int("modeler_workspace_max_wall_seconds", 2700),
    }


def _modeler_loop_budget(root: Path) -> dict[str, Any]:
    path = root / "modeler_workspace_budget.json"
    value = _read_json(path)
    if not value:
        value = {
            "transport": "workspace_tool_loop",
            "started_epoch": time.time(),
            "api_turns": 1 if (root / "raw_modeler_model_theory_response.json").exists() else 0,
            "tool_calls": 0,
            "stages": {"modeler_model_theory": 1} if (root / "raw_modeler_model_theory_response.json").exists() else {},
        }
        _write_json(path, value)
    return value


def _save_modeler_loop_budget(root: Path, value: dict[str, Any]) -> None:
    value["updated_utc"] = _utc_now()
    _write_json(root / "modeler_workspace_budget.json", value)


def _workspace_session(root: Path, stage: str, attempt: str, *, seed_package: bool, seed_package_dir: Path | None = None) -> modeler_workspace.WorkspaceSession:
    safe_attempt = re.sub(r"[^A-Za-z0-9_.-]+", "_", attempt or "initial")
    workspace = root / "modeler_workspaces" / f"{stage}_{safe_attempt}"
    session = modeler_workspace.WorkspaceSession(
        workspace,
        validate_source=package_runtime._validate_generated_source,
        validate_input_schema=lambda value, inputs: _validate_input_schema(value, inputs, source="Modeler workspace input_schema"),
        parse_scenarios=lambda value: _parse_scenario_cases(value, source="Modeler workspace scenario_cases"),
        validate_package=validate_package,
        run_stress=run_mechanical_stress,
        run_tests=lambda package_dir, output, stress, inputs: run_model_tests(package_dir, output, stress, active_inputs=inputs),
        execute_package=package_runtime.execute_package,
        set_path=_set_path,
    )
    if seed_package:
        session.initialize_from_package(seed_package_dir or (root / "model_package"))
    else:
        session.initialize_fresh()
        spec_dir = session.workspace / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        for source_name, target_name in (("model_spec.json", "model_spec.json"), ("model_thesis.json", "model_thesis.json"), ("equation_graph.json", "equation_graph.json"), ("model_tests.json", "model_tests.json")):
            value = _read_json(root / source_name)
            if value:
                _write_json(spec_dir / target_name, value)
    declared_tests = _read_json(root / "model_tests.json")
    if declared_tests:
        _write_json(session.workspace.parent / "model_tests.json", declared_tests)
    return session


def _modeler_workspace_context(
    root: Path,
    prompt: str,
    *,
    stage: str,
    approved_spec: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "transport": "workspace_tool_loop",
        "stage": stage,
        "user_prompt": prompt,
        "approved_model_spec": approved_spec or _read_json(root / "model_spec.json"),
        "model_thesis": _read_json(root / "model_thesis.json"),
        "equation_graph": _read_json(root / "equation_graph.json"),
        "model_tests": _read_json(root / "model_tests.json"),
        "workspace_rules": {
            "authority": "Only files saved and executed by the provided workspace tools are authoritative.",
            "model_logic_ownership": "You design and implement all model-specific business logic; the backend supplies technical contracts only.",
            "required_finish": "Run the full gate, submit its current receipt, then return the small completion object without source code.",
            "scenario_ownership": "The backend applies saved Base/Downside/Upside overrides. checks.py uses run_checks for case tests and run_suite_checks for cross-scenario tests and must not recreate overrides.",
        },
        **(extra_context or {}),
    }


def _request_workspace_package(
    prompt: str,
    root: Path,
    *,
    stage: str,
    attempt: str,
    prompt_id: str,
    seed_package: bool,
    seed_package_dir: Path | None = None,
    approved_spec: dict[str, Any] | None = None,
    extra_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the authoritative Modeler workspace.")
    limits = _modeler_loop_limits()
    budget = _modeler_loop_budget(root)
    if time.time() - float(budget.get("started_epoch") or time.time()) >= limits["wall_seconds"]:
        raise RuntimeError("Authoritative Modeler workspace exceeded the 45-minute wall-time limit.")
    session = _workspace_session(root, stage, attempt, seed_package=seed_package, seed_package_dir=seed_package_dir)
    context = _modeler_workspace_context(
        root,
        prompt,
        stage=stage,
        approved_spec=approved_spec,
        extra_context=extra_context,
    )
    system_prompt = prompts.load_prompt("modeler_workspace") + "\n\nStage-specific requirements:\n" + prompts.load_prompt(prompt_id)
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
    ]
    model = model_config.model_for_stage(stage)
    base_body = {
        "model": model,
        "text": {"format": {"type": "json_schema", "name": f"{stage}_completion", "schema": MODELER_COMPLETION_SCHEMA, "strict": True}},
        "reasoning": {"effort": "medium"},
        "tools": modeler_workspace.workspace_tool_definitions(),
        "tool_choice": "required",
        "include": ["reasoning.encrypted_content"],
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": f"{root.name}_{stage}_{attempt}",
            "transport": "workspace_tool_loop",
        },
    }
    context_name = f"modeler_workspace_context_{stage}_{attempt}.json"
    _write_json(root / context_name, {"system_prompt_id": "modeler_workspace", "stage_prompt_id": prompt_id, "user_context": context, "workspace": str(session.workspace.relative_to(root))})
    all_output: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    usage: dict[str, Any] = {}
    completion_raw: dict[str, Any] | None = None
    stage_turns = 0
    while stage_turns < limits["stage_turns"]:
        if int(budget.get("api_turns") or 0) >= limits["total_turns"]:
            raise RuntimeError(f"Authoritative Modeler workspace exhausted the {limits['total_turns']}-turn model limit.")
        if int(budget.get("tool_calls") or 0) >= limits["total_tools"]:
            raise RuntimeError(f"Authoritative Modeler workspace exhausted the {limits['total_tools']}-tool-call model limit.")
        if time.time() - float(budget.get("started_epoch") or time.time()) >= limits["wall_seconds"]:
            raise RuntimeError("Authoritative Modeler workspace exceeded the 45-minute wall-time limit.")
        body = {**base_body, "input": conversation}
        if stage_turns > 0:
            body["tool_choice"] = "auto"
        raw = _post_openai(api_key, body)
        stage_turns += 1
        budget["api_turns"] = int(budget.get("api_turns") or 0) + 1
        stages = budget.setdefault("stages", {})
        stages[stage] = int(stages.get(stage) or 0) + 1
        _save_modeler_loop_budget(root, budget)
        _write_json(root / f"raw_modeler_workspace_turn_{stage}_{attempt}_{stage_turns}.json", raw)
        usage = _combine_openai_usage(usage, raw.get("usage") or {})
        output_items = [item for item in raw.get("output") or [] if isinstance(item, dict)]
        all_output.extend(output_items)
        function_calls = _extract_function_calls(raw)
        if not function_calls:
            completion_raw = raw
            break
        outputs: list[dict[str, Any]] = []
        for call in function_calls:
            if int(budget.get("tool_calls") or 0) >= limits["total_tools"]:
                raise RuntimeError(f"Authoritative Modeler workspace exhausted the {limits['total_tools']}-tool-call model limit.")
            started = time.perf_counter()
            args: dict[str, Any] = {}
            try:
                args = json.loads(str(call.get("arguments") or "{}"))
                if not isinstance(args, dict):
                    raise RuntimeError("Tool arguments must decode to an object.")
                result = session.run(str(call.get("name") or ""), args)
                ok = True
                error_text = ""
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
                ok = False
                error_text = str(exc)
            record = {
                "created_utc": _utc_now(),
                "stage": stage,
                "attempt": attempt,
                "round_index": stage_turns - 1,
                "call_id": call.get("call_id"),
                "tool_name": call.get("name"),
                "arguments": {"path": args.get("path")} if "path" in args else {key: value for key, value in args.items() if key != "content"},
                "ok": ok,
                "result": result,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
            if error_text:
                record["error"] = error_text
            records.append(record)
            budget["tool_calls"] = int(budget.get("tool_calls") or 0) + 1
            _save_modeler_loop_budget(root, budget)
            outputs.append({"type": "function_call_output", "call_id": call.get("call_id"), "output": json.dumps(result, separators=(",", ":"), default=str)})
            model_trace.append_event(root, "modeler_workspace_tool_call", actor="modeler", recipient="backend_tool", stage=stage, attempt=attempt, status="completed" if ok else "error", payload=record, error=error_text)
            if "same deterministic failure was repeated twice" in error_text:
                raise RuntimeError(error_text)
        conversation.extend(_response_output_input_items(output_items))
        conversation.extend(outputs)
        if not session.submitted:
            remaining_stage_turns = limits["stage_turns"] - stage_turns
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        f"{remaining_stage_turns} API turn(s) remain in this stage. "
                        "Batch independent tool calls where safe, preserve enough turns for a fresh full gate and submission, "
                        "and do not spend the remaining budget polishing narrative artifacts before executable admission."
                    ),
                }
            )
        if session.submitted:
            if stage_turns >= limits["stage_turns"]:
                raise RuntimeError(f"Authoritative Modeler workspace submitted too late to complete within {limits['stage_turns']} API turns.")
            if int(budget.get("api_turns") or 0) >= limits["total_turns"]:
                raise RuntimeError(f"Authoritative Modeler workspace exhausted the {limits['total_turns']}-turn model limit before finalization.")
            conversation.append({"role": "user", "content": "The authoritative candidate is submitted. Do not call another tool. Return only the required completion object and use the accepted receipt."})
            final_body = {**base_body, "input": conversation, "tool_choice": "none"}
            raw = _post_openai(api_key, final_body)
            stage_turns += 1
            budget["api_turns"] = int(budget.get("api_turns") or 0) + 1
            stages[stage] = int(stages.get(stage) or 0) + 1
            _save_modeler_loop_budget(root, budget)
            _write_json(root / f"raw_modeler_workspace_turn_{stage}_{attempt}_{stage_turns}.json", raw)
            usage = _combine_openai_usage(usage, raw.get("usage") or {})
            all_output.extend(item for item in raw.get("output") or [] if isinstance(item, dict))
            completion_raw = raw
            break
    if completion_raw is None:
        raise RuntimeError(f"Authoritative Modeler workspace exhausted {limits['stage_turns']} API turns in {stage}.")
    if not session.submitted:
        raise RuntimeError("Modeler returned a completion response before submitting a passing authoritative workspace.")
    completion = json.loads(_extract_response_text(completion_raw))
    if not isinstance(completion, dict) or set(completion) != set(MODELER_COMPLETION_SCHEMA["required"]):
        raise RuntimeError("Modeler completion object did not match the authoritative workspace completion contract.")
    if completion.get("gate_receipt") != session.last_receipt:
        raise RuntimeError("Modeler completion receipt does not match the accepted authoritative workspace receipt.")
    if any(key in json.dumps(completion, default=str) for key in ('"package_files"', '"content"')):
        raise RuntimeError("Modeler completion must not contain package source.")
    package_files, base_inputs, schema, scenarios = session.export()
    promoted_spec_paths = _promote_workspace_spec_artifacts(
        root,
        session.export_spec_artifacts(),
        changed_paths=session.changed_paths,
        approved_spec=approved_spec,
    )
    clean_files = _validate_package_files(package_files, source="authoritative Modeler workspace")
    schema = _validate_input_schema(schema, base_inputs, source="authoritative Modeler workspace input_schema")
    scenarios = _parse_scenario_cases(scenarios, source="authoritative Modeler workspace scenario_cases")
    self_check = {
        "passed": True,
        "summary": completion.get("summary") or "Authoritative workspace passed all deterministic gates.",
        "checks": [
            {"id": "authoritative_workspace_submitted", "passed": True},
            {"id": "production_full_gate_passed", "passed": True},
            {"id": "workspace_fingerprint_matched", "passed": True},
        ],
        "issues": [],
        "transport": "workspace_tool_loop",
        "gate_receipt": session.last_receipt,
        "workspace_fingerprint": session.last_gate.get("workspace_fingerprint"),
        "changed_paths": sorted(session.changed_paths),
        "promoted_spec_paths": promoted_spec_paths,
        "resolved_issue_ids": completion.get("resolved_issue_ids") or [],
        "api_turn_count": stage_turns,
        "tool_call_count": len(records),
        "code_interpreter_required": False,
        "code_interpreter_call_count": 0,
    }
    raw_record = {
        "transport": "workspace_tool_loop",
        "completion": completion,
        "output": all_output,
        "usage": usage,
        "_function_tool_calls": records,
    }
    raw_name = f"raw_modeler_workspace_response_{stage}_{attempt}.json"
    _write_json(root / raw_name, raw_record)
    _write_json(root / f"modeler_workspace_tool_report_{stage}_{attempt}.json", {"transport": "workspace_tool_loop", "stage": stage, "attempt": attempt, "api_turns": stage_turns, "tool_calls": records, "completion": completion, "final_gate": session.last_gate})
    usage_report = _record_usage(root, model, usage, stage=stage, code_interpreter_call_count=0)
    usage_report.update({"transport": "workspace_tool_loop", "api_turn_count": stage_turns, "tool_call_count": len(records), "workspace_fingerprint": session.last_gate.get("workspace_fingerprint")})
    return clean_files, base_inputs, schema, scenarios, self_check, usage_report


def _promote_workspace_spec_artifacts(
    root: Path,
    artifacts: dict[str, dict[str, Any]],
    *,
    changed_paths: set[str],
    approved_spec: dict[str, Any] | None,
) -> list[str]:
    from backend.app import model_spec as model_spec_module

    changed = sorted(path for path in changed_paths if path.startswith("spec/"))
    if not changed:
        return []
    for path in changed:
        payload = artifacts.get(path)
        if not isinstance(payload, dict) or not payload:
            raise RuntimeError(f"Authoritative workspace specification artifact is invalid: {path}")
        name = Path(path).name
        if name == "model_spec.json":
            parsed = model_spec_module.parse_model_spec(payload)
            blockers = model_spec_module._spec_blockers(parsed)
            if blockers:
                raise RuntimeError("Amended authoritative model_spec is not ready: " + "; ".join(blockers))
            wrapper = dict(approved_spec or _read_json(root / "model_spec.json"))
            wrapper.update({"status": "approved", "path": "model_spec.json", "model_spec": parsed, "updated_utc": _utc_now()})
            _write_json(root / "model_spec.json", wrapper)
        elif name == "model_thesis.json":
            if not isinstance(payload.get("model_thesis"), dict):
                raise RuntimeError("Amended model_thesis.json must contain model_thesis.")
            _write_json(root / "model_thesis.json", payload)
        elif name == "equation_graph.json":
            if not isinstance(payload.get("equation_graph"), dict):
                raise RuntimeError("Amended equation_graph.json must contain equation_graph.")
            _write_json(root / "equation_graph.json", payload)
        elif name == "model_tests.json":
            if not isinstance(payload.get("model_tests"), list) or not payload["model_tests"]:
                raise RuntimeError("Amended model_tests.json must contain a non-empty model_tests array.")
            _write_json(root / "model_tests.json", payload)
    return changed


def _modeler_scope_review_report(review_report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review_report, dict):
        return {"required_amendments": [], "repair_instructions": [], "modeler_scope_only": True}
    presentation_categories = {"presentation_data", "dashboard_layout"}
    amendments = [
        dict(item)
        for item in review_report.get("required_amendments") or []
        if isinstance(item, dict) and item.get("category") not in presentation_categories
    ]
    return {
        "attempt": review_report.get("attempt"),
        "summary": review_report.get("summary") or "",
        "required_amendments": amendments,
        "repair_instructions": [
            str(item.get("required_change") or "") for item in amendments if str(item.get("required_change") or "").strip()
        ],
        "modeler_scope_only": True,
    }


def _scope_modeler_review_repair(
    root: Path,
    *,
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    review_report: dict[str, Any],
    repair_round: int,
    report_suffix: str = "",
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Admit only artifacts owned by the assigned amendment categories."""
    package_dir = root / "model_package"
    current_files = _read_package_files(package_dir)
    current_by_path = {item["path"]: item["content"] for item in current_files}
    candidate_by_path = {item["path"]: item["content"] for item in package_files}
    categories = {
        str(item.get("category") or "")
        for item in review_report.get("required_amendments") or []
        if isinstance(item, dict)
    }
    # A coherent Modeler repair may need to update a dependency outside the
    # amendment's surface category (for example, a test-coverage amendment may
    # require the schedule that produces the tested sensitivity grid).  The
    # candidate has already passed the authoritative full gate, and the same
    # reviewer will check it again, so admit all generated Python files while
    # retaining the narrower input/schema/scenario ownership rules below.
    allow_all_files = True

    def file_allowed(path: str) -> bool:
        if allow_all_files:
            return True
        if "model_logic" in categories and (path == "model/main.py" or path.startswith("model/schedules/")):
            return True
        if "test_coverage" in categories and path == "model/checks.py":
            return True
        if "assumption_contract" in categories and path == "model/assumptions.py":
            return True
        if categories & {"output_definition", "label_or_explanation"} and path == "model/outputs.py":
            return True
        return False

    if allow_all_files:
        admitted_by_path = dict(candidate_by_path)
    else:
        admitted_by_path = {path: content for path, content in current_by_path.items() if not file_allowed(path)}
        admitted_by_path.update({path: content for path, content in candidate_by_path.items() if file_allowed(path)})

    rejected_file_changes = sorted(
        path
        for path, content in candidate_by_path.items()
        if not file_allowed(path) and current_by_path.get(path) != content
    )
    allow_base_inputs = not categories or bool(categories & {"assumption_contract", "spec_alignment", "package_structure"})
    allow_schema = allow_base_inputs
    allow_scenarios = not categories or bool(categories & {"scenario_behavior", "assumption_contract", "spec_alignment", "package_structure"})
    admitted_base_inputs = base_inputs if allow_base_inputs else _read_json(package_dir / "inputs" / "base_case.json")
    admitted_schema = schema if allow_schema else _read_json(package_dir / "inputs" / "input_schema.json")
    admitted_scenarios = scenarios if allow_scenarios else _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json")
    report = {
        "repair_round": repair_round,
        "categories": sorted(categories),
        "allowed_all_package_files": allow_all_files,
        "admitted_file_changes": sorted(
            path for path, content in admitted_by_path.items() if current_by_path.get(path) != content
        ),
        "rejected_unowned_file_changes": rejected_file_changes,
        "base_inputs_admitted": allow_base_inputs,
        "input_schema_admitted": allow_schema,
        "scenario_cases_admitted": allow_scenarios,
    }
    suffix = f"_{report_suffix}" if report_suffix else ""
    report_name = f"repair_scope_report_round_{repair_round}{suffix}.json"
    _write_json(root / report_name, report)
    model_trace.append_event(
        root,
        "modeler_repair_scope_admission",
        actor="backend",
        recipient="trace",
        stage="modeler_package_repair",
        attempt=f"repair_{repair_round}",
        status="admitted",
        payload=report,
        artifacts={"repair_scope_report": report_name},
    )
    admitted_files = [{"path": path, "content": admitted_by_path[path]} for path in sorted(admitted_by_path)]
    return admitted_files, admitted_base_inputs, admitted_schema, admitted_scenarios, report


def request_backend_repaired_package(
    prompt: str,
    root: Path,
    backend_failure_report: dict[str, Any],
    *,
    attempt_index: int = 1,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for backend-check package repair.")
    package_files, base_inputs, schema, scenarios, self_check, usage_report = _request_workspace_package(
        prompt,
        root,
        stage="modeler_package_backend_repair",
        attempt=f"backend_repair_{attempt_index}",
        prompt_id="model_package_backend_repair",
        seed_package=True,
        extra_context={"backend_failure_report": backend_failure_report, "backend_repair_attempt": attempt_index},
    )
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt, root, package_files, base_inputs, schema, scenarios
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    usage_report = dict(usage_report)
    usage_report["presentation_agent_usage"] = presentation_usage
    usage_report["staged_reports"] = [usage_report.copy(), presentation_usage]
    return package_files, base_inputs, schema, scenarios, self_check, usage_report

    # Legacy whole-package response parsing remains for historical replay only.
    model = model_config.model_for_stage("modeler_package_backend_repair")
    stage = "modeler_package_backend_repair"
    run_id = f"{root.name}_{stage}_{attempt_index}"
    context = _package_context(root, prompt)
    context["backend_failure_report"] = backend_failure_report
    context["backend_repair_attempt"] = attempt_index
    system_prompt = prompts.load_prompt("model_package_backend_repair")
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": OPENAI_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}],
        "tool_choice": "required",
        "include": ["code_interpreter_call.outputs"],
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": run_id,
        },
    }
    repair_context = {
        "system_prompt_id": "model_package_backend_repair",
        "system_prompt": system_prompt,
        "user_context": context,
        "request_body": body,
    }
    context_name = "backend_repair_context.json" if attempt_index == 1 else f"backend_repair_context_round_{attempt_index}.json"
    raw_name = "raw_modeler_backend_repair_response.json" if attempt_index == 1 else f"raw_modeler_backend_repair_response_round_{attempt_index}.json"
    _write_json(root / context_name, repair_context)
    model_trace.append_event(
        root,
        "modeler_backend_repair_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        attempt=f"backend_repair_{attempt_index}",
        status="sent",
        payload=repair_context,
        artifacts={"backend_repair_context": context_name},
    )
    try:
        raw = _post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            root,
            "modeler_backend_repair_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            attempt=f"backend_repair_{attempt_index}",
            status="error",
            error=str(exc),
        )
        raise
    _write_json(root / raw_name, raw)
    model_trace.append_event(
        root,
        "modeler_backend_repair_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        attempt=f"backend_repair_{attempt_index}",
        status="received",
        payload=raw,
        artifacts={"raw_modeler_backend_repair_response": raw_name},
    )
    package_files, base_inputs, schema, scenarios, self_check = _parse_openai_build_response(raw)
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt,
        root,
        package_files,
        base_inputs,
        schema,
        scenarios,
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    model_trace.append_event(
        root,
        "modeler_backend_repair_parsed_package",
        actor="backend",
        recipient="trace",
        stage=stage,
        attempt=f"backend_repair_{attempt_index}",
        status="parsed",
        payload=_package_summary(package_files, base_inputs, schema, scenarios, self_check),
    )
    usage_report = _record_usage(
        root,
        model,
        raw.get("usage") or {},
        stage=stage,
        code_interpreter_call_count=len(self_check.get("code_interpreter_calls") or []),
    )
    usage_report["presentation_agent_usage"] = presentation_usage
    return package_files, base_inputs, schema, scenarios, self_check, usage_report


def request_amended_package(
    amendment_message: str,
    new_root: Path,
    previous_context: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for package amendment.")
    previous_version_id = str(previous_context.get("previous_version_id") or "")
    previous_package_dir = new_root.parent / previous_version_id / "model_package"
    if not previous_version_id or not (previous_package_dir / "model" / "main.py").exists():
        raise RuntimeError("Authoritative amendment requires the referenced previous package.")
    previous_spec = previous_context.get("approved_model_spec") if isinstance(previous_context.get("approved_model_spec"), dict) else {}
    package_files, base_inputs, schema, scenarios, self_check, usage_report = _request_workspace_package(
        amendment_message,
        new_root,
        stage="modeler_package_amendment",
        attempt="amendment",
        prompt_id="model_package_amend",
        seed_package=True,
        seed_package_dir=previous_package_dir,
        approved_spec=previous_spec,
        extra_context={
            "amendment_request": amendment_message,
            "previous_version_id": previous_version_id,
            "previous_version_status": previous_context.get("previous_version_status"),
            "instruction": "Revise the seeded authoritative package to implement the amendment without returning source code.",
        },
    )
    promoted_spec = _read_json(new_root / "model_spec.json")
    model_spec_payload = promoted_spec.get("model_spec") if isinstance(promoted_spec.get("model_spec"), dict) else (
        previous_spec.get("model_spec") if isinstance(previous_spec.get("model_spec"), dict) else previous_spec
    )
    change_summary = {
        "summary": self_check.get("summary") or "Authoritative workspace amendment completed.",
        "changed_paths": self_check.get("changed_paths") or [],
        "transport": "workspace_tool_loop",
    }
    return model_spec_payload, package_files, base_inputs, schema, scenarios, self_check, change_summary, usage_report

    # Historical whole-package amendment parsing remains below for legacy records.
    model = model_config.model_for_stage("modeler_package_amendment")
    stage = "modeler_package_amendment"
    run_id = f"{new_root.name}_{stage}"
    system_prompt = prompts.load_prompt("model_package_amend")
    context = {
        "amendment_request": amendment_message,
        "previous_package": previous_context,
        "output_contract": {
            "output_version": OUTPUT_VERSION,
            "required_keys": OUTPUT_KEYS,
            "required_blocks": "output_blocks must be a non-empty array of generic output data-library blocks.",
            "dashboard_spec": "display intent object, not strict widget/data wiring",
        },
        "review_language": PASS_MESSAGE,
        "output_instruction": "Return a full replacement package for the new draft version.",
    }
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": AMENDMENT_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}],
        "tool_choice": "required",
        "include": ["code_interpreter_call.outputs"],
        "store": False,
        "metadata": {
            "model_id": new_root.parent.name,
            "version_id": new_root.name,
            "stage": stage,
            "run_id": run_id,
        },
    }
    amendment_context = {
        "system_prompt_id": "model_package_amend",
        "system_prompt": system_prompt,
        "user_context": context,
        "request_body": body,
    }
    _write_json(new_root / "amendment_context.json", amendment_context)
    model_trace.append_event(
        new_root,
        "modeler_amendment_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        status="sent",
        payload=amendment_context,
        artifacts={"amendment_context": "amendment_context.json"},
    )
    try:
        raw = _post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            new_root,
            "modeler_amendment_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            status="error",
            error=str(exc),
        )
        raise
    _write_json(new_root / "raw_modeler_amendment_response.json", raw)
    model_trace.append_event(
        new_root,
        "modeler_amendment_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        status="received",
        payload=raw,
        artifacts={"raw_modeler_amendment_response": "raw_modeler_amendment_response.json"},
    )
    model_spec, package_files, base_inputs, schema, scenarios, self_check, change_summary = _parse_openai_amendment_response(raw)
    model_trace.append_event(
        new_root,
        "modeler_amendment_parsed_package",
        actor="backend",
        recipient="trace",
        stage=stage,
        status="parsed",
        payload={
            "package": _package_summary(package_files, base_inputs, schema, scenarios, self_check),
            "change_summary": change_summary,
            "model_spec_title": model_spec.get("title"),
        },
    )
    usage_report = _record_usage(
        new_root,
        model,
        raw.get("usage") or {},
        stage=stage,
        code_interpreter_call_count=len(self_check.get("code_interpreter_calls") or []),
    )
    return model_spec, package_files, base_inputs, schema, scenarios, self_check, change_summary, usage_report


def request_review_report(prompt: str, root: Path, *, attempt: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for package review.")
    model = model_config.model_for_stage("review_agent_audit")
    stage = "review_agent_audit"
    run_id = f"{root.name}_{stage}_{attempt}"
    context = _package_context(root, prompt)
    package_fingerprint = _package_review_fingerprint(context)
    context["package_fingerprint"] = package_fingerprint
    context["attempt"] = attempt
    context["review_history"] = (_read_json(root / "review_history.json").get("rounds") or [])
    context["max_repair_rounds"] = _review_repair_max_attempts()
    system_prompt = prompts.load_prompt("model_package_review")
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": REVIEW_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "tools": [{"type": "code_interpreter", "container": {"type": "auto"}}, *_review_function_tool_definitions()],
        "tool_choice": "required",
        "include": ["code_interpreter_call.outputs", "reasoning.encrypted_content"],
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "attempt": attempt,
            "run_id": run_id,
        },
    }
    model_trace.append_event(
        root,
        "review_agent_audit_request",
        actor="backend",
        recipient="review_agent",
        stage=stage,
        attempt=attempt,
        status="sent",
        payload={"system_prompt_id": "model_package_review", "system_prompt": system_prompt, "user_context": context, "request_body": body},
    )
    try:
        raw = _post_openai_with_function_tools(api_key, body, root=root, stage=stage, attempt=attempt)
    except Exception as exc:
        model_trace.append_event(
            root,
            "review_agent_audit_raw_response",
            actor="review_agent",
            recipient="backend",
            stage=stage,
            attempt=attempt,
            status="error",
            error=str(exc),
        )
        raise
    model_trace.append_event(
        root,
        "review_agent_audit_raw_response",
        actor="review_agent",
        recipient="backend",
        stage=stage,
        attempt=attempt,
        status="received",
        payload=raw,
    )
    code_interpreter_calls = _extract_code_interpreter_calls(raw)
    function_tool_calls = raw.get("_function_tool_calls") or []
    raw["_package_fingerprint"] = package_fingerprint
    raw_path = root / f"raw_review_response_{attempt}.json"
    _write_json(raw_path, raw)
    usage_report = _record_usage(root, model, raw.get("usage") or {}, stage=stage, code_interpreter_call_count=len(code_interpreter_calls))
    current_state = _read_json(root / "version_manifest.json")
    _update_version_manifest(root, str(current_state.get("status") or "draft"), usage_report=usage_report)
    report = _normalize_review_artifact_aliases(root, _parse_review_response(raw))
    report["attempt"] = attempt
    candidate_path = root / "model_package" / "reports" / f"review_report_candidate_{attempt}.json"
    _write_json(candidate_path, report)
    _write_json(root / f"review_report_candidate_{attempt}.json", report)
    evidence = {
        "created_utc": _utc_now(),
        "stage": stage,
        "attempt": attempt,
        "code_interpreter_required": True,
        "code_interpreter_call_count": len(code_interpreter_calls),
        "code_interpreter_calls": code_interpreter_calls,
        "candidate_review_report": str(candidate_path.relative_to(root)).replace("\\", "/"),
    }
    evidence_quality = _review_structural_evidence_quality(root, report, code_interpreter_calls, function_tool_calls)
    evidence["structural_execution"] = evidence_quality
    _write_json(root / "model_package" / "reports" / "review_execution_evidence.json", evidence)
    _write_json(root / "model_package" / "reports" / f"review_execution_evidence_{attempt}.json", evidence)
    _write_json(root / f"review_execution_evidence_{attempt}.json", evidence)
    model_trace.append_event(
        root,
        "review_agent_execution_evidence",
        actor="review_agent",
        recipient="trace",
        stage=stage,
        attempt=attempt,
        status="captured" if evidence_quality.get("passed") else "weak",
        payload=evidence,
        artifacts={"review_execution_evidence": "model_package/reports/review_execution_evidence.json"},
    )
    if evidence_quality.get("passed") is not True:
        raise RuntimeError("Review Agent audit structural evidence failed: " + evidence_quality.get("message", "weak evidence"))
    if report.get("repair_required") is True and not function_tool_calls:
        raise RuntimeError("Review Agent repair_required=true requires function-tool evidence before required_amendments.")
    report["execution_evidence"] = {
        "path": "model_package/reports/review_execution_evidence.json",
        "code_interpreter_required": True,
        "code_interpreter_call_count": len(code_interpreter_calls),
    }
    report["function_tool_evidence"] = {
        "path": "model_package/reports/agent_tool_calls_report.json" if function_tool_calls else "",
        "function_tool_call_count": len(function_tool_calls),
        "tools_used": sorted({str(call.get("tool_name") or "") for call in function_tool_calls if call.get("tool_name")}),
    }
    report["usage_report"] = {
        "stage": usage_report.get("stage"),
        "model": usage_report.get("model"),
        "usage_summary": usage_report.get("usage_summary") or {},
        "cost_summary": usage_report.get("cost_summary") or {},
        "openai_called": True,
    }
    model_trace.append_event(
        root,
        "review_agent_audit_parsed_report",
        actor="backend",
        recipient="trace",
        stage=stage,
        attempt=attempt,
        status="parsed",
        payload=report,
        usage=report["usage_report"],
    )
    return report


def _failure_reasons_from_review(report: dict[str, Any]) -> list[str]:
    reasons = [str(item).strip() for item in report.get("failure_reasons") or [] if str(item).strip()]
    if reasons:
        return reasons
    return _fallback_failure_reasons(report)


def run_backend_check_repair_cycle(
    manifest: dict[str, Any],
    prompt: str,
    *,
    max_attempts: int,
    review_scope_report: dict[str, Any] | None = None,
    review_repair_round: int = 0,
) -> dict[str, Any]:
    version_id = str(manifest.get("current_version_id") or "")
    root = version_dir(str(manifest["model_id"]), version_id)
    current_state = _read_json(root / "version_manifest.json")
    if max_attempts <= 0 or current_state.get("status") == "review_ready":
        return current_state
    state = current_state
    for attempt_index in range(1, max_attempts + 1):
        failure_report = _read_json(root / "failure_report.json")
        if not failure_report:
            failure_report = {
                "failure_code": state.get("failure_code") or "backend_validation_failed",
                "failure_stage": state.get("failure_stage") or "backend_checks",
                "failure_reasons": state.get("failure_reasons") or ["Backend package checks failed."],
            }
        snapshot_name = "pre_backend_repair_package" if attempt_index == 1 else f"pre_backend_repair_package_round_{attempt_index}"
        snapshot = _snapshot_package(root, snapshot_name)
        model_trace.append_event(
            root,
            "pre_backend_repair_package_snapshot",
            actor="backend",
            recipient="trace",
            stage="modeler_package_backend_repair",
            attempt=f"backend_repair_{attempt_index}",
            status="saved",
            artifacts={"pre_backend_repair_package": snapshot},
        )
        try:
            package_files, inputs, schema, scenarios, self_check, usage_report = request_backend_repaired_package(
                prompt,
                root,
                failure_report,
                attempt_index=attempt_index,
            )
        except Exception as exc:
            code = _classify_generation_failure(exc, default="parser_failed")
            state = _write_failure_report(
                root,
                code=code,
                stage="modeler_package_backend_repair",
                message=str(exc),
                reasons=[str(exc)],
                status="failed_checks",
                next_actions=["retry_generation_or_revise_spec"],
                failure_subcode=_classify_generation_failure_subcode(exc),
            )
            model_trace.append_event(
                root,
                "backend_repair_status",
                actor="backend",
                recipient="trace",
                stage="modeler_package_backend_repair",
                attempt=f"backend_repair_{attempt_index}",
                status="failed",
                payload={"reason": "backend repair generation failed", "failure_code": code},
                error=str(exc),
            )
            return state
        if review_scope_report:
            package_files, inputs, schema, scenarios, scope_report = _scope_modeler_review_repair(
                root,
                package_files=package_files,
                base_inputs=inputs,
                schema=schema,
                scenarios=scenarios,
                review_report=review_scope_report,
                repair_round=review_repair_round,
                report_suffix=f"backend_{attempt_index}",
            )
            self_check = dict(self_check)
            self_check["repair_scope_report"] = scope_report
        approved_spec = _read_json(root / "model_spec.json")
        write_package(root, manifest, prompt, inputs, schema, scenarios, package_files, self_check, usage_report, approved_spec=approved_spec)
        state = run_minimal(manifest, version_id, inputs, published=False)
        _record_workflow_stage(root, "post_backend_repair" if attempt_index == 1 else f"post_backend_repair_{attempt_index}")
        repaired = state.get("status") == "review_ready"
        model_trace.append_event(
            root,
            "backend_repair_status",
            actor="backend",
            recipient="trace",
            stage="modeler_package_backend_repair",
            attempt=f"backend_repair_{attempt_index}",
            status="passed" if repaired else "failed",
            payload={
                "backend_repair_attempted": True,
                "backend_repair_attempt": attempt_index,
                "backend_repair_max_attempts": max_attempts,
                "result_status": state.get("status"),
                "failure_code": state.get("failure_code"),
                "failure_reasons": state.get("failure_reasons") or [],
            },
        )
        if repaired:
            state["backend_repair_attempted"] = True
            state["backend_repair_attempts_used"] = attempt_index
            state["backend_repair_status"] = "passed"
            state["backend_repair_max_attempts"] = max_attempts
            _write_json(root / "version_manifest.json", state)
            return state
    state["backend_repair_attempted"] = True
    state["backend_repair_attempts_used"] = max_attempts
    state["backend_repair_status"] = "exhausted"
    state["backend_repair_max_attempts"] = max_attempts
    _write_json(root / "version_manifest.json", state)
    return state


def _perform_modeler_review_repair(
    manifest: dict[str, Any],
    prompt: str,
    root: Path,
    review_report: dict[str, Any],
    review_history: list[dict[str, Any]],
    repair_round: int,
) -> dict[str, Any]:
    snapshot = _snapshot_package(root, f"pre_review_repair_package_round_{repair_round}")
    model_trace.append_event(root, "pre_repair_package_snapshot", actor="backend", recipient="trace", stage="modeler_package_repair", attempt=f"repair_{repair_round}", status="saved", artifacts={"pre_repair_package": snapshot})
    package_files, inputs, schema, scenarios, self_check, usage_report = request_repaired_package(
        prompt, root, review_report, repair_round=repair_round, review_history=review_history
    )
    approved_spec = _read_json(root / "model_spec.json")
    write_package(root, manifest, prompt, inputs, schema, scenarios, package_files, self_check, usage_report, approved_spec=approved_spec)
    _persist_review_history(root, review_history, repairs_used=repair_round, status="checking_repair")
    state = run_minimal(manifest, str(manifest.get("current_version_id") or ""), inputs, published=False)
    _record_workflow_stage(root, f"post_review_repair_{repair_round}")
    return state


def _perform_presentation_review_repair(
    manifest: dict[str, Any],
    prompt: str,
    root: Path,
    review_report: dict[str, Any],
    review_history: list[dict[str, Any]],
    repair_round: int,
) -> dict[str, Any]:
    snapshot = _snapshot_package(root, f"pre_presentation_repair_package_round_{repair_round}")
    model_trace.append_event(root, "pre_presentation_repair_package_snapshot", actor="backend", recipient="trace", stage="presentation_agent_repair", attempt=f"repair_{repair_round}", status="saved", artifacts={"pre_presentation_repair_package": snapshot})
    package_dir = root / "model_package"
    package_files = _read_package_files(package_dir)
    inputs = _read_json(package_dir / "inputs" / "base_case.json")
    schema = _read_json(package_dir / "inputs" / "input_schema.json")
    scenarios = _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json")
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt,
        root,
        package_files,
        inputs,
        schema,
        scenarios,
        review_report=review_report,
        repair_round=repair_round,
    )
    self_check = _read_json(package_dir / "reports" / "modeler_self_check.json")
    self_check["presentation_agent_report"] = presentation_report
    approved_spec = _read_json(root / "model_spec.json")
    write_package(root, manifest, prompt, inputs, schema, scenarios, package_files, self_check, presentation_usage, approved_spec=approved_spec)
    _persist_review_history(root, review_history, repairs_used=repair_round, status="checking_presentation_repair")
    state = run_minimal(manifest, str(manifest.get("current_version_id") or ""), inputs, published=False)
    _record_workflow_stage(root, f"post_presentation_repair_{repair_round}")
    return state


def _perform_review_repair(
    manifest: dict[str, Any],
    prompt: str,
    root: Path,
    review_report: dict[str, Any],
    review_history: list[dict[str, Any]],
    repair_round: int,
) -> dict[str, Any]:
    material = [
        item for item in review_report.get("required_amendments") or []
        if isinstance(item, dict) and item.get("severity") in {"blocker", "high", "medium"} and item.get("human_decision_required") is not True
    ]
    presentation_only = bool(material) and all(item.get("category") in {"presentation_data", "dashboard_layout"} for item in material)
    if presentation_only and model_config.role_enabled("presentation_agent"):
        return _perform_presentation_review_repair(manifest, prompt, root, review_report, review_history, repair_round)
    return _perform_modeler_review_repair(manifest, prompt, root, review_report, review_history, repair_round)


def _recover_backend_checks_within_review_round(
    manifest: dict[str, Any],
    prompt: str,
    root: Path,
    check_state: dict[str, Any],
    review_history: list[dict[str, Any]],
    *,
    repair_round: int,
    review_report: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Repair deterministic defects without spending another substantive review round."""
    if check_state.get("status") == "review_ready":
        return check_state, True
    recovered = run_backend_check_repair_cycle(
        manifest,
        prompt,
        max_attempts=backend_check_repair_max_attempts(),
        review_scope_report=_modeler_scope_review_report(review_report),
        review_repair_round=repair_round,
    )
    if recovered.get("status") == "review_ready":
        _persist_review_history(root, review_history, repairs_used=repair_round, status="reviewing")
        model_trace.append_event(
            root,
            "review_round_mechanical_recovery",
            actor="backend",
            recipient="trace",
            stage="modeler_package_repair_backend_checks",
            attempt=f"repair_{repair_round}",
            status="passed",
            payload={"substantive_repair_round": repair_round, "additional_substantive_round_consumed": False},
        )
        return recovered, True
    failure = _read_json(root / "failure_report.json") or {}
    reasons = failure.get("failure_reasons") or ["The Review-driven revision could not pass deterministic checks after mechanical recovery."]
    _persist_review_history(root, review_history, repairs_used=repair_round, status="mechanical_repair_exhausted")
    _write_failure_report(
        root,
        code=str(failure.get("failure_code") or "backend_validation_failed"),
        stage="modeler_package_repair_backend_checks",
        message="Review-driven revision exhausted mechanical backend recovery within the same substantive repair round.",
        reasons=reasons,
        status="review_failed",
        next_actions=["amend_or_stop"],
    )
    _append_final_trace(root, "review_failed", "Mechanical recovery exhausted inside a Review-driven substantive repair round.")
    return _update_version_manifest(root, "review_failed", latest_run_status="review_failed"), False


def run_review_cycle(
    manifest: dict[str, Any],
    prompt: str,
    *,
    initial_review_report: dict[str, Any] | None = None,
    resume_interrupted: bool = False,
    retry_structural_review: bool = False,
    retry_failed_review: bool = False,
    resume_existing_history: bool = False,
) -> dict[str, Any]:
    version_id = str(manifest.get("current_version_id") or "")
    root = version_dir(str(manifest["model_id"]), version_id)
    max_repairs = _review_repair_max_attempts()
    review_history: list[dict[str, Any]] = []
    repairs_used = 0
    pending_initial_report = dict(initial_review_report) if isinstance(initial_review_report, dict) else None
    pending_interrupted_report: dict[str, Any] | None = None
    retry_attempt = False

    if resume_interrupted or retry_structural_review or retry_failed_review or resume_existing_history:
        history_payload = _read_json(root / "review_history.json")
        failure = _read_json(root / "failure_report.json")
        history_rounds = history_payload.get("rounds") if isinstance(history_payload.get("rounds"), list) else []
        failure_code = str(failure.get("failure_code") or "")
        if not history_rounds and not retry_failed_review and not resume_existing_history:
            raise RuntimeError("Review resume requires persisted review history.")
        review_history = [dict(item) for item in history_rounds if isinstance(item, dict)]
        repairs_used = int(history_payload.get("repairs_used") or 0)
        if resume_existing_history:
            if pending_initial_report is None:
                raise RuntimeError("Existing-history review resume requires a saved review report.")
        elif resume_interrupted:
            if failure_code not in {"budget_blocked", "quota_blocked", "openai_transport_failed"}:
                raise RuntimeError("Review resume requires a persisted budget or transport interruption.")
            pending_interrupted_report = review_history[-1]
            if pending_interrupted_report.get("repair_required") is not True:
                raise RuntimeError("Review resume requires an unresolved automatic amendment.")
            if repairs_used >= max_repairs:
                raise RuntimeError("Review resume cannot exceed the configured repair limit.")
        elif retry_structural_review:
            failure_message = str(failure.get("message") or "")
            if str(failure.get("failure_stage") or "") != "review_agent_audit" or "structural evidence failed" not in failure_message.lower():
                raise RuntimeError("Review retry requires a persisted structural-evidence admission failure.")
            retry_attempt = True
        else:
            failure_message = str(failure.get("message") or "").lower()
            if str(failure.get("failure_stage") or "") != "review_agent_audit" or not any(
                marker in failure_message
                for marker in (
                    "function-tool loop ended",
                    "did not return final json after tool use was disabled",
                    "review agent finding is missing required fields",
                )
            ):
                raise RuntimeError("Review retry requires a persisted reviewer-convergence failure.")
            retry_attempt = True

    while True:
        if pending_interrupted_report is not None:
            repairs_used += 1
            report = pending_interrupted_report
            pending_interrupted_report = None
            try:
                check_state = _perform_review_repair(manifest, prompt, root, report, review_history, repairs_used)
            except Exception as exc:
                code = _classify_generation_failure(exc, default="parser_failed")
                _write_failure_report(root, code=code, stage="modeler_package_repair", message=str(exc), reasons=[str(exc)], status="review_failed", next_actions=["resume_review_or_stop"], failure_subcode=_classify_generation_failure_subcode(exc))
                raise
            if check_state.get("status") != "review_ready":
                check_state, recovered = _recover_backend_checks_within_review_round(
                    manifest, prompt, root, check_state, review_history, repair_round=repairs_used, review_report=report
                )
                if not recovered:
                    return check_state

        attempt = "initial" if repairs_used == 0 else f"after_repair_{repairs_used}"
        if retry_attempt:
            attempt = _next_review_retry_attempt(root, attempt)
            retry_attempt = False
        try:
            if pending_initial_report is not None:
                report = pending_initial_report
                pending_initial_report = None
            else:
                report = request_review_report(prompt, root, attempt=attempt)
            if report.get("required_amendments"):
                report["required_amendments_report"] = _write_required_amendments_report(
                    root, report, review_round=len(review_history)
                )
        except Exception as exc:
            code = _classify_generation_failure(exc, default="review_failed")
            _write_failure_report(
                root,
                code=code if code in {"openai_transport_failed", "budget_blocked"} else "review_failed",
                stage="review_agent_audit",
                message=str(exc),
                reasons=[str(exc)],
                status="review_failed",
                next_actions=["retry_review_or_amend"],
                failure_subcode=_classify_generation_failure_subcode(exc),
            )
            raise

        review_history.append(report)
        _persist_review_history(root, review_history, repairs_used=repairs_used, status="reviewing")
        if report.get("approved") is True and report.get("repair_required") is not True:
            _persist_review_history(root, review_history, repairs_used=repairs_used, status="approved")
            _append_final_trace(root, "review_ready", f"Review approved after {repairs_used} repair round(s).")
            return _update_version_manifest(root, "review_ready", latest_run_status="review_passed")

        human_stop = any(
            item.get("human_decision_required") is True and item.get("severity") in {"blocker", "high", "medium"}
            for item in report.get("required_amendments") or []
        )
        if report.get("repair_required") is not True or human_stop:
            report["failure_reasons"] = _failure_reasons_from_review(report)
            stop = "Review requires a human decision." if human_stop else "Review denied without an automatic repair path."
            _persist_review_history(root, review_history, repairs_used=repairs_used, status="human_decision" if human_stop else "denied")
            _write_failure_report(root, code="review_failed", stage="review_agent_audit", message=stop, reasons=report["failure_reasons"], status="review_failed", next_actions=["human_decision_required" if human_stop else "amend_or_stop"])
            _append_final_trace(root, "review_failed", stop)
            return _update_version_manifest(root, "review_failed", latest_run_status="review_failed")

        if repairs_used >= max_repairs:
            report["failure_reasons"] = _failure_reasons_from_review(report)
            _persist_review_history(root, review_history, repairs_used=repairs_used, status="repair_limit_exhausted")
            _write_failure_report(root, code="review_failed", stage="review_agent_audit", message=f"Review denied after {max_repairs} repair rounds.", reasons=report["failure_reasons"], status="review_failed", next_actions=["amend_or_stop"])
            _append_final_trace(root, "review_failed", f"Review denied after {max_repairs} repair rounds.")
            return _update_version_manifest(root, "review_failed", latest_run_status="review_failed")

        repairs_used += 1
        try:
            check_state = _perform_review_repair(manifest, prompt, root, report, review_history, repairs_used)
        except Exception as exc:
            code = _classify_generation_failure(exc, default="parser_failed")
            _write_failure_report(root, code=code, stage="modeler_package_repair", message=str(exc), reasons=[str(exc)], status="review_failed", next_actions=["amend_or_stop"], failure_subcode=_classify_generation_failure_subcode(exc))
            raise
        if check_state.get("status") != "review_ready":
            check_state, recovered = _recover_backend_checks_within_review_round(
                manifest, prompt, root, check_state, review_history, repair_round=repairs_used, review_report=report
            )
            if not recovered:
                return check_state


def resume_review_cycle_from_raw_response(
    manifest: dict[str, Any],
    prompt: str,
    raw: dict[str, Any],
    *,
    attempt: str = "initial",
    preserve_existing_history: bool = False,
) -> dict[str, Any]:
    """Resume after a locally fixed review-admission defect without repurchasing review."""
    version_id = str(manifest.get("current_version_id") or "")
    root = version_dir(str(manifest["model_id"]), version_id)
    report = _normalize_review_artifact_aliases(root, _parse_review_response(raw))
    code_calls = _extract_code_interpreter_calls(raw)
    function_calls = raw.get("_function_tool_calls") or []
    evidence_quality = _review_structural_evidence_quality(root, report, code_calls, function_calls)
    if evidence_quality.get("passed") is not True:
        raise RuntimeError("Saved Review Agent response does not have admissible structural evidence: " + evidence_quality.get("message", "weak evidence"))
    report["attempt"] = attempt
    report["execution_evidence"] = {
        "path": f"review_execution_evidence_{attempt}.json",
        "code_interpreter_required": True,
        "code_interpreter_call_count": len(code_calls),
        "replayed_without_openai": True,
        "structural_execution": evidence_quality,
    }
    report["function_tool_evidence"] = {
        "path": f"agent_tool_calls_report_{attempt}.json" if function_calls else "",
        "function_tool_call_count": len(function_calls),
        "tools_used": evidence_quality.get("tools_used") or [],
        "replayed_without_openai": True,
    }
    _write_json(root / f"review_report_candidate_{attempt}.json", report)
    model_trace.append_event(
        root,
        "review_agent_saved_response_readmitted",
        actor="backend",
        recipient="trace",
        stage="review_agent_audit",
        attempt=attempt,
        status="parsed",
        payload={
            "approved": report.get("approved"),
            "repair_required": report.get("repair_required"),
            "required_amendment_ids": [item.get("issue_id") for item in report.get("required_amendments") or []],
            "replayed_without_openai": True,
        },
    )
    if preserve_existing_history:
        history_payload = _read_json(root / "review_history.json")
        old_rounds = [dict(item) for item in history_payload.get("rounds") or [] if isinstance(item, dict)]
        mechanical_rounds = [item for item in old_rounds if item.get("actor") == "deterministic_backend"]
        substantive_rounds = [item for item in old_rounds if item.get("actor") != "deterministic_backend"]
        corrected_repairs_used = max(0, int(history_payload.get("repairs_used") or 0) - len(mechanical_rounds))
        _persist_review_history(
            root,
            substantive_rounds,
            repairs_used=corrected_repairs_used,
            status="reviewing_saved_response",
        )
        model_trace.append_event(
            root,
            "legacy_backend_round_accounting_corrected",
            actor="backend",
            recipient="trace",
            stage="review_agent_audit",
            attempt=attempt,
            status="corrected",
            payload={
                "removed_mechanical_history_entries": len(mechanical_rounds),
                "previous_repairs_used": int(history_payload.get("repairs_used") or 0),
                "substantive_repairs_used": corrected_repairs_used,
            },
        )
        return run_review_cycle(
            manifest,
            prompt,
            initial_review_report=report,
            resume_existing_history=True,
        )
    return run_review_cycle(manifest, prompt, initial_review_report=report)


def resume_review_cycle_from_saved_repair_response(
    manifest: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    """Mechanically recover a saved Modeler repair that failed package parsing.

    This resumes the same substantive repair round. It does not repurchase the
    Modeler's substantive revision and does not consume another Review round.
    """
    version_id = str(manifest.get("current_version_id") or "")
    root = version_dir(str(manifest["model_id"]), version_id)
    failure = _read_json(root / "failure_report.json")
    if str(failure.get("failure_stage") or "") != "modeler_package_repair" or str(failure.get("failure_code") or "") != "parser_failed":
        raise RuntimeError("Saved repair recovery requires a persisted Modeler repair parser failure.")
    history_payload = _read_json(root / "review_history.json")
    review_history = [dict(item) for item in history_payload.get("rounds") or [] if isinstance(item, dict)]
    repairs_used = int(history_payload.get("repairs_used") or 0)
    repair_round = repairs_used + 1
    max_repairs = _review_repair_max_attempts()
    if not review_history or repair_round > max_repairs:
        raise RuntimeError("Saved repair recovery cannot exceed the configured substantive repair limit.")
    review_report = review_history[-1]
    raw_path = root / f"raw_modeler_repair_response_round_{repair_round}.json"
    raw = _read_json(raw_path)
    if not raw:
        raise RuntimeError(f"Saved Modeler repair response is missing: {raw_path.name}")

    context = _package_context(root, prompt)
    fallback = {
        "package_files": context.get("package_files") or [],
        "base_inputs": context.get("base_inputs") or {},
        "input_schema": context.get("input_schema") or {},
        "scenario_cases": context.get("scenario_cases") or [],
    }
    try:
        _parse_openai_build_response(raw)
    except Exception as exc:
        candidate, diagnostic = _repairable_package_candidate(raw, fallback=fallback, parser_error=exc)
    else:
        raise RuntimeError("Saved Modeler repair response is already parseable; ordinary review resume should be used.")

    package_files, inputs, schema, scenarios, self_check, mechanical_usage = request_self_checked_package(
        prompt,
        root,
        approved_spec=context.get("approved_model_spec") or {},
        model_thesis=context.get("model_thesis") or {},
        equation_graph=context.get("equation_graph") or {},
        model_tests=context.get("model_tests") or [],
        draft_package=candidate,
        initial_preflight=diagnostic,
        artifact_namespace=f"review_repair_{repair_round}_resume",
    )
    package_files, presentation_report, presentation_usage = _present_replacement_package(
        prompt,
        root,
        package_files,
        inputs,
        schema,
        scenarios,
        review_report=review_report,
        repair_round=repair_round,
    )
    self_check = dict(self_check)
    self_check["presentation_agent_report"] = presentation_report
    model = model_config.model_for_stage("modeler_package_repair")
    repair_usage = _record_usage(
        root,
        model,
        raw.get("usage") or {},
        stage="modeler_package_repair_saved_response",
        code_interpreter_call_count=len(_extract_code_interpreter_calls(raw)),
    )
    usage_report = dict(repair_usage)
    usage_report["mechanical_recovery_usage"] = mechanical_usage
    usage_report["presentation_agent_usage"] = presentation_usage
    usage_report["staged_reports"] = [repair_usage, *(mechanical_usage.get("mechanical_preflight_usage") or [mechanical_usage]), presentation_usage]
    approved_spec = _read_json(root / "model_spec.json")
    write_package(root, manifest, prompt, inputs, schema, scenarios, package_files, self_check, usage_report, approved_spec=approved_spec)
    _persist_review_history(root, review_history, repairs_used=repair_round, status="checking_recovered_repair")
    state = run_minimal(manifest, version_id, inputs, published=False)
    _record_workflow_stage(root, f"post_review_repair_{repair_round}_mechanically_recovered")
    if state.get("status") != "review_ready":
        failure = _read_json(root / "failure_report.json")
        reasons = failure.get("failure_reasons") or ["Mechanically recovered repair failed deterministic backend checks."]
        _persist_review_history(root, review_history, repairs_used=repair_round, status="repair_limit_exhausted")
        _write_failure_report(root, code=str(failure.get("failure_code") or "backend_validation_failed"), stage="modeler_package_repair_backend_checks", message="Recovered final repair failed backend checks.", reasons=reasons, status="review_failed", next_actions=["amend_or_stop"])
        return _update_version_manifest(root, "review_failed", latest_run_status="review_failed")

    final_report = request_review_report(prompt, root, attempt=f"after_repair_{repair_round}")
    if final_report.get("required_amendments"):
        final_report["required_amendments_report"] = _write_required_amendments_report(
            root, final_report, review_round=len(review_history)
        )
    review_history.append(final_report)
    if final_report.get("approved") is True and final_report.get("repair_required") is not True:
        _persist_review_history(root, review_history, repairs_used=repair_round, status="approved")
        _append_final_trace(root, "review_ready", f"Review approved after {repair_round} repair round(s), with mechanical recovery inside the final round.")
        return _update_version_manifest(root, "review_ready", latest_run_status="review_passed")

    final_report["failure_reasons"] = _failure_reasons_from_review(final_report)
    _persist_review_history(root, review_history, repairs_used=repair_round, status="repair_limit_exhausted")
    _write_failure_report(root, code="review_failed", stage="review_agent_audit", message=f"Review denied after {repair_round} repair rounds.", reasons=final_report["failure_reasons"], status="review_failed", next_actions=["amend_or_stop"])
    _append_final_trace(root, "review_failed", f"Review denied after {repair_round} repair rounds.")
    return _update_version_manifest(root, "review_failed", latest_run_status="review_failed")


def resume_review_cycle_from_saved_attempts(
    manifest: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    """Admit cumulative receipts from retries of one unchanged review round."""
    version_id = str(manifest.get("current_version_id") or "")
    root = version_dir(str(manifest["model_id"]), version_id)
    history_payload = _read_json(root / "review_history.json")
    repairs_used = int(history_payload.get("repairs_used") or 0)
    attempt_base = "initial" if repairs_used == 0 else f"after_repair_{repairs_used}"
    raw_paths = sorted(
        root.glob(f"raw_review_response_{attempt_base}*.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    if len(raw_paths) < 2:
        raise RuntimeError("Cumulative review admission requires at least two saved attempts for the unchanged package.")

    raws = [_read_json(path) for path in raw_paths]
    fingerprints = [str(raw.get("_package_fingerprint") or "") for raw in raws]
    if not all(fingerprints) or len(set(fingerprints)) != 1:
        raise RuntimeError("Cumulative review admission requires matching saved package fingerprints.")
    report = _parse_review_response(raws[-1])
    code_calls = [call for raw in raws for call in _extract_code_interpreter_calls(raw)]
    function_calls = [
        dict(call)
        for raw in raws
        for call in (raw.get("_function_tool_calls") or [])
        if isinstance(call, dict)
    ]
    evidence_quality = _review_structural_evidence_quality(root, report, code_calls, function_calls)
    if evidence_quality.get("passed") is not True:
        raise RuntimeError(
            "Saved Review Agent retries do not have admissible cumulative structural evidence: "
            + evidence_quality.get("message", "weak evidence")
        )

    attempt = f"{attempt_base}_cumulative"
    report["attempt"] = attempt
    source_attempts = [path.stem.removeprefix("raw_review_response_") for path in raw_paths]
    evidence = {
        "created_utc": _utc_now(),
        "stage": "review_agent_audit",
        "attempt": attempt,
        "source_attempts": source_attempts,
        "package_unchanged_between_attempts": True,
        "package_fingerprint": fingerprints[0],
        "openai_called_for_admission": False,
        "code_interpreter_required": True,
        "code_interpreter_call_count": len(code_calls),
        "code_interpreter_calls": code_calls,
        "candidate_review_report": f"review_report_candidate_{attempt}.json",
        "structural_execution": evidence_quality,
    }
    _write_json(root / "model_package" / "reports" / "review_execution_evidence.json", evidence)
    _write_json(root / "model_package" / "reports" / f"review_execution_evidence_{attempt}.json", evidence)
    _write_json(root / f"review_execution_evidence_{attempt}.json", evidence)
    _write_agent_tool_calls_report(root, stage="review_agent_audit", attempt=attempt, records=function_calls)
    report["execution_evidence"] = {
        "path": "model_package/reports/review_execution_evidence.json",
        "code_interpreter_required": True,
        "code_interpreter_call_count": len(code_calls),
        "replayed_without_openai": True,
        "cumulative_retry_evidence": True,
        "structural_execution": evidence_quality,
    }
    report["function_tool_evidence"] = {
        "path": "model_package/reports/agent_tool_calls_report.json",
        "function_tool_call_count": len(function_calls),
        "tools_used": evidence_quality.get("tools_used") or [],
        "replayed_without_openai": True,
        "cumulative_retry_evidence": True,
    }
    _write_json(root / "model_package" / "reports" / f"review_report_candidate_{attempt}.json", report)
    _write_json(root / f"review_report_candidate_{attempt}.json", report)
    model_trace.append_event(
        root,
        "review_agent_saved_retries_readmitted",
        actor="backend",
        recipient="trace",
        stage="review_agent_audit",
        attempt=attempt,
        status="parsed",
        payload={
            "approved": report.get("approved"),
            "repair_required": report.get("repair_required"),
            "source_attempts": source_attempts,
            "replayed_without_openai": True,
        },
    )
    return run_review_cycle(manifest, prompt, initial_review_report=report)


def _package_review_fingerprint(context: dict[str, Any]) -> str:
    durable = {
        key: context.get(key)
        for key in (
            "source_prompt",
            "approved_model_spec",
            "model_thesis",
            "equation_graph",
            "model_tests",
            "package_files",
            "base_inputs",
            "input_schema",
            "scenario_cases",
            "latest_output",
        )
    }
    encoded = json.dumps(durable, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_openai_build_response(raw: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    parsed = json.loads(_extract_response_text(raw))
    package_files, base_inputs, schema, scenarios = _parse_package_payload(parsed, source="OpenAI package build")
    self_check = parsed.get("modeler_self_check")
    if not isinstance(self_check, dict) or not self_check:
        raise RuntimeError("OpenAI package build did not return modeler_self_check.")
    if self_check.get("passed") is not True:
        raise RuntimeError("OpenAI package build self-check did not pass.")
    code_interpreter_calls = _extract_code_interpreter_calls(raw)
    if not code_interpreter_calls:
        raise RuntimeError("OpenAI package build did not include Code Interpreter self-check evidence.")
    self_check = dict(self_check)
    self_check["code_interpreter_required"] = True
    self_check["code_interpreter_call_count"] = len(code_interpreter_calls)
    self_check["code_interpreter_calls"] = code_interpreter_calls
    return package_files, base_inputs, schema, scenarios, self_check


def _parse_openai_draft_package_response(raw: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    parsed = json.loads(_extract_response_text(raw))
    return _parse_repairable_draft_payload(parsed)


def _parse_repairable_draft_payload(parsed: Any) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Admit a safe draft even when final mechanical checks fail.

    Draft source is never accepted as a package here. It is passed to the
    Modeler's Code Interpreter self-check together with exact preflight errors.
    """
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI draft package response must be a JSON object.")
    raw_files = parsed.get("package_files")
    if not isinstance(raw_files, list) or not raw_files:
        raise RuntimeError("OpenAI draft package package_files must be a non-empty array.")
    package_files: list[dict[str, str]] = []
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise RuntimeError(f"OpenAI draft package package_files[{index}] must be an object.")
        path = str(item.get("path") or "").replace("\\", "/").strip()
        content = item.get("content")
        if not path or path.startswith("/") or ".." in Path(path).parts or not path.startswith("model/") or not path.endswith(".py"):
            raise RuntimeError(f"OpenAI draft package package_files[{index}].path is unsafe: {path}")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"OpenAI draft package package_files[{index}].content must be non-empty source.")
        package_files.append({"path": path, "content": content})
    base_inputs = parsed.get("base_inputs")
    schema = parsed.get("input_schema")
    scenarios = parsed.get("scenario_cases")
    if not isinstance(base_inputs, dict) or not isinstance(schema, dict) or not isinstance(scenarios, list):
        raise RuntimeError("OpenAI draft package must include object base_inputs/input_schema and array scenario_cases.")
    return package_files, base_inputs, schema, scenarios


def _repairable_package_candidate(raw: dict[str, Any], *, fallback: dict[str, Any], parser_error: Exception) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = fallback
    extraction_error = ""
    try:
        parsed = json.loads(_extract_response_text(raw))
        package_files, base_inputs, schema, scenarios = _parse_repairable_draft_payload(parsed)
        candidate = {"package_files": package_files, "base_inputs": base_inputs, "input_schema": schema, "scenario_cases": scenarios}
    except Exception as exc:
        extraction_error = str(exc)
    diagnostic = {
        "passed": False,
        "category": "mechanical_preflight",
        "error": str(parser_error),
        "candidate_extraction_error": extraction_error,
        "instruction": "Correct the exact syntax, file, import, schema, or startup defect; execute the complete returned package before marking self-check passed.",
    }
    return candidate, diagnostic


def _parse_package_payload(parsed: Any, *, source: str) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{source} response must be a JSON object.")
    package_files = _validate_package_files(parsed.get("package_files"), source=f"{source} package_files")
    base_inputs = parsed.get("base_inputs")
    schema = parsed.get("input_schema")
    if not isinstance(base_inputs, dict) or not base_inputs:
        raise RuntimeError(f"{source} did not return base_inputs.")
    schema = _validate_input_schema(schema, base_inputs, source=f"{source} input_schema")
    scenarios = _parse_scenario_cases(parsed.get("scenario_cases"), source=f"{source} scenario_cases")
    return package_files, base_inputs, schema, scenarios


def parse_model_theory(raw: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise RuntimeError("Model theory response must be a JSON object.")
    missing = [key for key in MODEL_THEORY_SCHEMA["required"] if key not in raw]
    if missing:
        raise RuntimeError("Model theory response is missing required fields: " + ", ".join(missing))
    thesis = _validate_model_thesis(raw.get("model_thesis"))
    equation_graph = _validate_equation_graph(raw.get("equation_graph"))
    model_tests = _validate_declared_model_tests(raw.get("model_tests"), source="model_tests")
    return thesis, equation_graph, model_tests


def _write_model_theory_artifacts(root: Path, model_thesis: dict[str, Any], equation_graph: dict[str, Any], model_tests: list[dict[str, Any]]) -> None:
    _write_json(root / "model_thesis.json", {"status": "ready", "path": "model_thesis.json", "model_thesis": model_thesis})
    _write_json(root / "equation_graph.json", {"status": "ready", "path": "equation_graph.json", "equation_graph": equation_graph})
    _write_json(root / "model_tests.json", {"status": "ready", "path": "model_tests.json", "model_tests": model_tests})


def _validate_model_thesis(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("model_thesis must be a non-empty object.")
    required = ["thesis_version", "purpose", "modeled_objects", "assumptions", "outputs", "limitations"]
    allowed = set(required) | {"policy_choices", "exclusions"}
    extra = sorted(set(raw.keys()) - allowed)
    if extra:
        raise RuntimeError("model_thesis has unexpected fields: " + ", ".join(extra))
    missing = [key for key in required if key not in raw]
    if missing:
        raise RuntimeError("model_thesis is missing required fields: " + ", ".join(missing))
    for key in ("modeled_objects", "assumptions", "outputs", "limitations", "policy_choices", "exclusions"):
        if key not in raw:
            continue
        if not isinstance(raw.get(key), list):
            raise RuntimeError(f"model_thesis.{key} must be a list.")
    if not isinstance(raw.get("purpose"), str) or not raw["purpose"].strip():
        raise RuntimeError("model_thesis.purpose must be a non-empty string.")
    return dict(raw)


def _validate_equation_graph(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("equation_graph must be a non-empty object.")
    required = ["graph_version", "nodes", "edges", "calculation_order", "key_tie_outs", "output_dependencies"]
    extra = sorted(set(raw.keys()) - set(required))
    if extra:
        raise RuntimeError("equation_graph has unexpected fields: " + ", ".join(extra))
    missing = [key for key in required if key not in raw]
    if missing:
        raise RuntimeError("equation_graph is missing required fields: " + ", ".join(missing))
    for key in ("nodes", "edges", "calculation_order", "key_tie_outs", "output_dependencies"):
        if not isinstance(raw.get(key), list):
            raise RuntimeError(f"equation_graph.{key} must be a list.")
    return dict(raw)


def _validate_package_files(raw: Any, *, source: str) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{source} must be a non-empty array.")
    by_path: dict[str, str] = {}
    invalid: list[str] = []
    for index, item in enumerate(raw):
        item_path = f"[{index}]"
        if not isinstance(item, dict):
            invalid.append(f"{item_path} must be an object")
            continue
        extra = sorted(set(item.keys()) - {"path", "content"})
        if extra:
            invalid.append(f"{item_path} has unexpected keys: {', '.join(extra)}")
        path = str(item.get("path") or "").replace("\\", "/").strip()
        content = item.get("content")
        if not path or path.startswith("/") or ".." in Path(path).parts:
            invalid.append(f"{item_path}.path is not an allowed relative path")
            continue
        if not ALLOWED_MODEL_FILE_RE.match(path):
            invalid.append(f"{item_path}.path is outside the allowed generated package tree: {path}")
            continue
        if path in by_path:
            invalid.append(f"{item_path}.path is duplicated: {path}")
            continue
        if not isinstance(content, str) or not content.strip() or "```" in content:
            invalid.append(f"{item_path}.content must be plain non-empty Python source")
            continue
        by_path[path] = content.strip() + "\n"
    missing_required = sorted(REQUIRED_PACKAGE_FILE_PATHS - set(by_path))
    if missing_required:
        invalid.append("missing required package files: " + ", ".join(missing_required))
    schedule_files = sorted(path for path in by_path if path.startswith("model/schedules/") and path != "model/schedules/__init__.py")
    if not schedule_files:
        invalid.append("at least one model/schedules/<name>.py file is required")
    if not invalid:
        invalid.extend(_package_file_interface_errors(by_path))
    if not invalid:
        invalid.extend(_package_file_import_graph_errors(by_path))
    if invalid:
        raise RuntimeError(f"{source} is invalid: " + "; ".join(invalid))
    return [{"path": path, "content": by_path[path]} for path in sorted(by_path)]


def _package_file_interface_errors(files: dict[str, str]) -> list[str]:
    required_functions = {
        "model/main.py": "run_model",
        "model/assumptions.py": "load_inputs",
        "model/schedules/__init__.py": "run_all",
        "model/outputs.py": "build_output",
        "model/checks.py": "run_checks",
    }
    errors: list[str] = []
    for file_path, source in files.items():
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            errors.append(f"{file_path} has invalid syntax: {exc}")
            continue
        errors.extend(_top_level_state_errors(tree, file_path))
        if any(isinstance(node, ast.ClassDef) for node in ast.walk(tree)):
            errors.append(f"{file_path} must not define classes")
    for path, function_name in required_functions.items():
        try:
            tree = ast.parse(files[path], filename=path)
        except SyntaxError as exc:
            errors.append(f"{path} has invalid syntax: {exc}")
            continue
        function_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        if function_name not in function_names:
            errors.append(f"{path} must define {function_name}")
        if path == "model/main.py" and "run_checks" in function_names:
            errors.append("model/main.py must not define run_checks; use model/checks.py")
    main_source = files.get("model/main.py", "")
    for required_name in ("load_inputs", "run_all", "build_output"):
        if required_name not in main_source:
            errors.append(f"model/main.py must orchestrate through {required_name}")
    return errors


def _top_level_state_errors(tree: ast.Module, path: str) -> list[str]:
    errors: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Global, ast.Nonlocal)):
            errors.append(f"{path} must not define hidden module-level state")
            continue
        if isinstance(node, ast.Pass):
            continue
        errors.append(f"{path} must not execute module-level code")
    return errors


def _package_file_import_graph_errors(files: dict[str, str]) -> list[str]:
    module_for_path = {path[:-3].replace("/", "."): path for path in files}
    graph: dict[str, set[str]] = {module: set() for module in module_for_path}
    errors: list[str] = []
    for module, path in module_for_path.items():
        try:
            tree = ast.parse(files[path], filename=path)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    errors.append(f"{path} must use absolute model.* imports, not relative imports")
                    continue
                imported = node.module or ""
                if imported.startswith("model") and imported in graph:
                    graph[module].add(imported)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    if imported.startswith("model") and imported in graph:
                        graph[module].add(imported)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str, trail: list[str]) -> None:
        if module in visiting:
            errors.append("circular generated package import detected: " + " -> ".join(trail + [module]))
            return
        if module in visited:
            return
        visiting.add(module)
        for child in sorted(graph.get(module) or []):
            visit(child, trail + [module])
        visiting.remove(module)
        visited.add(module)

    for module in sorted(graph):
        visit(module, [])
    return errors


def _parse_openai_amendment_response(raw: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    parsed = json.loads(_extract_response_text(raw))
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenAI amendment response must be a JSON object.")
    model_spec = parsed.get("model_spec")
    if not isinstance(model_spec, dict):
        raise RuntimeError("OpenAI amendment response did not return model_spec.")
    from backend.app import model_spec as model_spec_module

    parsed_spec = model_spec_module.parse_model_spec(model_spec)
    blockers = model_spec_module._spec_blockers(parsed_spec)
    if blockers:
        raise RuntimeError("OpenAI amendment model_spec is not ready to build: " + "; ".join(blockers))
    package_files, base_inputs, schema, scenarios, self_check = _parse_openai_build_response(raw)
    change_summary = parsed.get("change_summary")
    if not isinstance(change_summary, dict) or not change_summary:
        raise RuntimeError("OpenAI amendment response did not return change_summary.")
    return parsed_spec, package_files, base_inputs, schema, scenarios, self_check, change_summary


def _parse_review_response(raw: dict[str, Any]) -> dict[str, Any]:
    parsed = json.loads(_extract_response_text(raw))
    if not isinstance(parsed, dict):
        raise RuntimeError("Review Agent response must be a JSON object.")
    approved = parsed.get("approved")
    repair_required = parsed.get("repair_required")
    if not isinstance(approved, bool) or not isinstance(repair_required, bool):
        raise RuntimeError("Review Agent response must include approved and repair_required booleans.")
    if approved is True and repair_required is True:
        raise RuntimeError("Review Agent response cannot both approve and require repair.")
    summary = parsed.get("summary")
    findings = parsed.get("findings")
    required_amendments = parsed.get("required_amendments")
    repair_instructions = parsed.get("repair_instructions")
    human_questions = parsed.get("human_questions")
    failure_reasons = parsed.get("failure_reasons")
    if not isinstance(summary, str) or not isinstance(findings, list):
        raise RuntimeError("Review Agent response must include summary and findings.")
    if approved is not True and not findings:
        raise RuntimeError("Review Agent response must include evidence-backed findings when not approved.")
    if not isinstance(repair_instructions, list) or not isinstance(human_questions, list) or not isinstance(failure_reasons, list):
        raise RuntimeError("Review Agent response must include repair_instructions, human_questions, and failure_reasons arrays.")
    if not isinstance(required_amendments, list):
        raise RuntimeError("Review Agent response must include a required_amendments array.")
    clean_findings = []
    for finding in findings:
        clean_findings.append(_parse_review_finding(finding))
    clean_amendments = [_parse_required_amendment(item) for item in required_amendments]
    automatic_amendments = [
        item
        for item in clean_amendments
        if item.get("human_decision_required") is not True and item.get("severity") in {"blocker", "high", "medium"}
    ]
    if repair_required is True and not automatic_amendments:
        raise RuntimeError("Review Agent repair_required=true requires at least one non-human blocker, high, or medium required_amendment.")
    if approved is True and any(item.get("severity") in {"blocker", "high"} for item in clean_amendments):
        raise RuntimeError("Review Agent cannot approve with an unresolved blocker or high required_amendment.")
    return {
        "approved": approved,
        "repair_required": repair_required,
        "summary": summary,
        "findings": clean_findings,
        "required_amendments": clean_amendments,
        "repair_instructions": [str(item) for item in repair_instructions],
        "human_questions": [str(item) for item in human_questions],
        "failure_reasons": [str(item) for item in failure_reasons],
    }


_AMENDMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,80}$")
_AMENDMENT_SEVERITIES = {"blocker", "high", "medium", "low", "advisory"}
_AMENDMENT_CATEGORIES = {"model_logic", "test_coverage", "scenario_behavior", "output_definition", "presentation_data", "dashboard_layout", "assumption_contract", "spec_alignment", "label_or_explanation", "package_structure"}
_AMENDMENT_PROBE_BEHAVIORS = {"change", "increase", "decrease", "same", "not_null"}


def _parse_required_amendment(amendment: Any) -> dict[str, Any]:
    if not isinstance(amendment, dict):
        raise RuntimeError("Review Agent required_amendments must be objects.")
    required = ["issue_id", "severity", "category", "artifacts", "observed", "required_change", "acceptance_criteria", "human_decision_required"]
    missing = [key for key in required if key not in amendment]
    if missing:
        raise RuntimeError("Review Agent required_amendment is missing required fields: " + ", ".join(missing))
    parsed: dict[str, Any] = {}
    for key in ("issue_id", "severity", "category", "observed", "required_change"):
        value = amendment.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Review Agent required_amendment field {key} must be a non-empty string.")
        parsed[key] = value.strip()
    if not _AMENDMENT_ID_RE.match(parsed["issue_id"]):
        raise RuntimeError("Review Agent required_amendment issue_id must be snake_case with 3-81 lowercase letters, numbers, or underscores.")
    if parsed["severity"] not in _AMENDMENT_SEVERITIES:
        raise RuntimeError("Review Agent required_amendment severity is invalid.")
    if parsed["category"] not in _AMENDMENT_CATEGORIES:
        raise RuntimeError("Review Agent required_amendment category is invalid.")
    artifacts = amendment.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or any(not isinstance(item, str) or not item.strip() for item in artifacts):
        raise RuntimeError("Review Agent required_amendment artifacts must be a non-empty string array.")
    parsed["artifacts"] = [item.strip() for item in artifacts]
    criteria = amendment.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(item, str) or not item.strip() for item in criteria):
        raise RuntimeError("Review Agent required_amendment acceptance_criteria must be a non-empty string array.")
    parsed["acceptance_criteria"] = [item.strip() for item in criteria]
    if not isinstance(amendment.get("human_decision_required"), bool):
        raise RuntimeError("Review Agent required_amendment human_decision_required must be a boolean.")
    parsed["human_decision_required"] = amendment["human_decision_required"]
    probe = amendment.get("verification_probe")
    if probe is not None:
        if not isinstance(probe, dict):
            raise RuntimeError("Review Agent required_amendment verification_probe must be an object.")
        input_path = probe.get("input_path")
        output_path = probe.get("output_path")
        expected_behavior = probe.get("expected_behavior")
        changed_value = probe.get("changed_value")
        if not isinstance(input_path, str) or not input_path.strip():
            raise RuntimeError("Review Agent verification_probe.input_path must be a non-empty string.")
        if not isinstance(output_path, str) or not output_path.strip():
            raise RuntimeError("Review Agent verification_probe.output_path must be a non-empty string.")
        if not isinstance(expected_behavior, str) or expected_behavior.strip() not in _AMENDMENT_PROBE_BEHAVIORS:
            raise RuntimeError("Review Agent verification_probe.expected_behavior is invalid.")
        if isinstance(changed_value, (dict, list)) or changed_value is None:
            raise RuntimeError("Review Agent verification_probe.changed_value must be a scalar value.")
        parsed["verification_probe"] = {
            "input_path": input_path.strip(),
            "changed_value": changed_value,
            "output_path": output_path.strip(),
            "expected_behavior": expected_behavior.strip(),
        }
    return parsed


def _parse_review_finding(finding: Any) -> dict[str, Any]:
    if not isinstance(finding, dict):
        raise RuntimeError("Review Agent findings must be objects.")
    required = [
        "severity",
        "area",
        "claim_tested",
        "symptom",
        "root_cause",
        "message",
        "evidence",
        "repair_instruction",
    ]
    # Structured responses occasionally place the descriptive repair text
    # inside evidence even though the authoritative required_amendment remains
    # complete. Preserve that evidence-backed finding instead of discarding the
    # whole review for a redundant field-placement error.
    evidence_payload = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
    if "repair_instruction" not in finding and isinstance(evidence_payload.get("repair_instruction"), str):
        finding = {**finding, "repair_instruction": evidence_payload["repair_instruction"]}
    missing = [key for key in required if key not in finding]
    if missing:
        raise RuntimeError("Review Agent finding is missing required fields: " + ", ".join(missing))
    parsed: dict[str, Any] = {}
    for key in ("severity", "area", "claim_tested", "symptom", "root_cause", "message", "repair_instruction"):
        value = finding.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Review Agent finding field {key} must be a non-empty string.")
        parsed[key] = value.strip()
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise RuntimeError("Review Agent finding evidence must be a non-empty object.")
    artifact = evidence.get("artifact")
    artifacts = evidence.get("artifacts")
    cited: list[str] = []
    if isinstance(artifact, str) and artifact.strip():
        cited.append(artifact.strip())
    if artifacts is not None:
        if not isinstance(artifacts, list) or any(not isinstance(item, str) or not item.strip() for item in artifacts):
            raise RuntimeError("Review Agent finding evidence.artifacts must be a non-empty string array when provided.")
        cited.extend(item.strip() for item in artifacts)
    if not cited:
        # Structured reviewers sometimes label each evidence observation by
        # purpose (for example ``implementation`` or ``specification``) and
        # embed the canonical path in its value instead of duplicating it in
        # an ``artifact`` key. Recover only explicit package paths that the
        # reviewer actually returned; the structural gate still resolves
        # every recovered citation against the authoritative package.
        citation_pattern = re.compile(
            r"(?:model_package/)?(?:model|spec|reports|outputs|inputs)/[A-Za-z0-9_./-]+\.(?:py|json)"
        )

        def collect_paths(value: Any) -> None:
            if isinstance(value, str):
                cited.extend(match.group(0) for match in citation_pattern.finditer(value))
            elif isinstance(value, dict):
                for nested in value.values():
                    collect_paths(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect_paths(nested)

        collect_paths(evidence)
    cited = list(dict.fromkeys(cited))
    if not cited:
        raise RuntimeError("Review Agent finding evidence must include artifact or artifacts citations.")
    detail_values = [
        value
        for key, value in evidence.items()
        if key not in {"artifact", "artifacts"}
    ]
    if not any(value not in (None, "", [], {}) for value in detail_values):
        raise RuntimeError("Review Agent finding evidence must include concrete detail in addition to artifact citations.")
    parsed_evidence = dict(evidence)
    parsed_evidence["artifact"] = cited[0]
    parsed_evidence["artifacts"] = cited
    parsed["evidence"] = parsed_evidence
    if "requires_human_decision" in finding and not isinstance(finding.get("requires_human_decision"), bool):
        raise RuntimeError("Review Agent finding requires_human_decision must be a boolean.")
    # required_amendments is the authoritative action contract. This finding
    # flag is descriptive and historically duplicated that state, so omission
    # must not discard an otherwise substantive, evidence-backed review.
    parsed["requires_human_decision"] = bool(finding.get("requires_human_decision", False))
    return parsed


def _package_context(root: Path, prompt: str) -> dict[str, Any]:
    package_dir = root / "model_package"
    return {
        "canonical_runtime_verification": {
            "input_contract": "run_checks receives the same raw input object passed to run_model; it does not receive load_inputs(raw_inputs)",
            "required_invocation": "output = run_model(raw_inputs); report = run_checks(raw_inputs, output)",
            "forbidden_substitution": "Do not call run_checks(load_inputs(raw_inputs), output) or otherwise normalize/substitute its input argument.",
            "required_cases": ["base", "downside", "upside"],
            "scenario_suite_contract": "After all three cases execute, run_suite_checks receives those exact backend-executed raw input/output pairs once; checks.py must not recreate scenario overrides.",
        },
        "source_prompt": prompt,
        "approved_model_spec": _read_json(root / "model_spec.json"),
        "model_thesis": _read_json(root / "model_thesis.json"),
        "equation_graph": _read_json(root / "equation_graph.json"),
        "model_tests": _read_json(root / "model_tests.json"),
        "package_files": _read_package_files(package_dir),
        "base_inputs": _read_json(package_dir / "inputs" / "base_case.json"),
        "input_schema": _read_json(package_dir / "inputs" / "input_schema.json"),
        "scenario_cases": _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json"),
        "validation_report": _read_json(package_dir / "reports" / "validation_report.json"),
        "mechanical_stress_report": _read_json(package_dir / "reports" / "mechanical_stress_report.json"),
        "model_tests_report": _read_json(package_dir / "reports" / "model_tests_report.json"),
        "modeler_self_check": _read_json(package_dir / "reports" / "modeler_self_check.json"),
        "presentation_agent_report": _read_json(package_dir / "reports" / "presentation_agent_report.json"),
        "required_amendments_report": _read_json(package_dir / "reports" / "required_amendments_report.json"),
        "agent_tool_calls_report": _read_json(package_dir / "reports" / "agent_tool_calls_report.json"),
        "review_history": _read_json(root / "review_history.json"),
        "latest_output": _read_json(package_dir / "outputs" / "output.json"),
    }


def _package_summary(
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    self_check: dict[str, Any],
) -> dict[str, Any]:
    fields = schema.get("fields") if isinstance(schema, dict) else []
    return {
        "package_file_paths": [item.get("path") for item in package_files],
        "base_input_keys": sorted(base_inputs.keys()),
        "input_field_count": len(fields) if isinstance(fields, list) else 0,
        "scenario_ids": [str(case.get("id") or "") for case in scenarios if isinstance(case, dict)],
        "self_check_passed": self_check.get("passed") if isinstance(self_check, dict) else None,
        "code_interpreter_call_count": self_check.get("code_interpreter_call_count") if isinstance(self_check, dict) else None,
    }


def _review_repair_max_attempts() -> int:
    return model_config.attempt_policy_int("review_repair_max_attempts", 3)


def _persist_review_history(
    root: Path,
    review_history: list[dict[str, Any]],
    *,
    repairs_used: int,
    status: str,
) -> None:
    reports_dir = root / "model_package" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for index, report in enumerate(review_history):
        _write_json(reports_dir / f"review_report_round_{index}.json", report)
    latest = review_history[-1] if review_history else {}
    _write_json(reports_dir / "review_report.json", latest)
    history_payload = {
        "created_utc": _utc_now(),
        "max_repair_attempts": _review_repair_max_attempts(),
        "repairs_used": repairs_used,
        "status": status,
        "rounds": review_history,
    }
    _write_json(root / "review_history.json", history_payload)
    _write_json(reports_dir / "review_history.json", history_payload)
    for report in reversed(review_history):
        amendment_evidence = (report.get("required_amendments_report") or {}).get("report")
        if isinstance(amendment_evidence, dict) and amendment_evidence:
            _write_json(reports_dir / "required_amendments_report.json", amendment_evidence)
            break
    _write_json(reports_dir / "repair_plan.json", _repair_plan_payload(review_history, repairs_used=repairs_used, status=status))


def _backend_failure_amendment_report(failure_report: dict[str, Any], *, repair_round: int) -> dict[str, Any]:
    reasons = [str(item) for item in failure_report.get("failure_reasons") or []]
    observed = "; ".join(reasons) or "The repaired package failed deterministic backend checks."
    issue_id = f"backend_checks_after_repair_{repair_round}"
    return {
        "actor": "deterministic_backend",
        "attempt": f"backend_after_repair_{repair_round}",
        "approved": False,
        "repair_required": True,
        "summary": observed,
        "findings": [],
        "required_amendments": [{
            "issue_id": issue_id,
            "severity": "blocker",
            "category": "package_structure",
            "artifacts": ["failure_report.json"],
            "observed": observed,
            "required_change": "Restore all deterministic package, execution, stress, and model-test gates without regressing prior review amendments.",
            "acceptance_criteria": ["All deterministic validation, mechanical stress, and model-local test reports pass."],
            "human_decision_required": False,
        }],
        "repair_instructions": [observed],
        "human_questions": [],
        "failure_reasons": reasons,
    }


def _repair_plan_payload(review_history: list[dict[str, Any]], *, repairs_used: int, status: str) -> dict[str, Any]:
    latest = review_history[-1] if review_history else {}
    return {
        "created_utc": _utc_now(),
        "max_repair_attempts": _review_repair_max_attempts(),
        "repairs_used": repairs_used,
        "repair_attempted": repairs_used > 0,
        "review_round": max(0, len(review_history) - 1),
        "status": status,
        "source_review_attempt": latest.get("attempt") or "initial",
        "summary": latest.get("summary") or "",
        "findings": latest.get("findings") or [],
        "required_amendments": latest.get("required_amendments") or [],
        "required_amendments_report": latest.get("required_amendments_report") or {},
        "repair_instructions": latest.get("repair_instructions") or [],
        "human_questions": latest.get("human_questions") or [],
        "failure_reasons": latest.get("failure_reasons") or [],
        "review_history": review_history,
    }


def _build_required_amendments_report(root: Path, review_report: dict[str, Any]) -> dict[str, Any]:
    package_dir = root / "model_package"
    base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
    input_schema = _read_json(package_dir / "inputs" / "input_schema.json")
    latest_output = _read_json(package_dir / "outputs" / "output.json")
    schema_paths = {
        str(field.get("path")).strip()
        for field in (input_schema.get("fields") if isinstance(input_schema, dict) else []) or []
        if isinstance(field, dict) and isinstance(field.get("path"), str) and str(field.get("path")).strip()
    }
    amendments = review_report.get("required_amendments") or []
    report_amendments: list[dict[str, Any]] = []
    for amendment in amendments:
        artifacts = [str(item) for item in amendment.get("artifacts") or []]
        missing = [artifact for artifact in artifacts if not _artifact_relative_exists(root, artifact)]
        if missing:
            raise RuntimeError(f"Review required_amendment {amendment.get('issue_id')} references missing artifacts: {', '.join(missing)}")
        record = {
            "issue_id": amendment.get("issue_id"),
            "severity": amendment.get("severity"),
            "category": amendment.get("category"),
            "artifacts": artifacts,
            "human_decision_required": amendment.get("human_decision_required") is True,
            "observed": amendment.get("observed") or "",
            "required_change": amendment.get("required_change") or "",
            "acceptance_criteria": amendment.get("acceptance_criteria") or [],
            "executed": False,
        }
        probe = amendment.get("verification_probe")
        if isinstance(probe, dict):
            record["verification_probe"] = dict(probe)
            record.update(_execute_repair_input_probe(package_dir, base_inputs, schema_paths, latest_output, probe, str(amendment.get("issue_id") or "")))
        report_amendments.append(record)
    executable_count = sum(1 for item in report_amendments if item.get("verification_probe"))
    probes_valid = all(item.get("probe_valid") is not False for item in report_amendments)
    return {
        "created_utc": _utc_now(),
        "passed": probes_valid,
        "amendment_count": len(report_amendments),
        "executable_probe_count": executable_count,
        "amendments": report_amendments,
    }


def _write_required_amendments_report(root: Path, review_report: dict[str, Any], *, review_round: int) -> dict[str, Any]:
    report = _build_required_amendments_report(root, review_report)
    path = root / "model_package" / "reports" / f"required_amendments_report_round_{review_round}.json"
    _write_json(path, report)
    _write_json(root / "model_package" / "reports" / "required_amendments_report.json", report)
    summary = {
        "path": "model_package/reports/required_amendments_report.json",
        "round_path": f"model_package/reports/required_amendments_report_round_{review_round}.json",
        "amendment_count": report.get("amendment_count"),
        "executable_probe_count": report.get("executable_probe_count"),
        "passed": report.get("passed"),
    }
    model_trace.append_event(
        root,
        "review_required_amendments_report",
        actor="backend",
        recipient="trace",
        stage="review_required_amendments",
        status="captured",
        payload=report,
        artifacts={"required_amendments_report": "model_package/reports/required_amendments_report.json"},
    )
    return {**summary, "report": report}


def _artifact_relative_exists(root: Path, relative_path: str) -> bool:
    if not relative_path or Path(relative_path).is_absolute():
        return False
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return False
    return target.exists()


def _execute_repair_input_probe(
    package_dir: Path,
    base_inputs: dict[str, Any],
    schema_paths: set[str],
    latest_output: dict[str, Any],
    probe: dict[str, Any],
    issue_id: str,
) -> dict[str, Any]:
    input_path = str(probe.get("input_path") or "").strip()
    output_path = str(probe.get("output_path") or "").strip()
    expected_behavior = str(probe.get("expected_behavior") or "").strip()
    if input_path not in schema_paths:
        return {
            "executed": False,
            "probe_valid": False,
            "input_path_valid": False,
            "output_path_valid": False,
            "probe_error": f"Review repair_target {issue_id} input_probe.input_path is not in input_schema: {input_path}",
        }
    if not _path_exists(base_inputs, input_path):
        return {
            "executed": False,
            "probe_valid": False,
            "input_path_valid": False,
            "output_path_valid": False,
            "probe_error": f"Review repair_target {issue_id} input_probe.input_path is not in base_case: {input_path}",
        }
    output_path_exists, base_value = _get_output_path_value(latest_output, output_path)
    if not output_path_exists:
        return {
            "executed": False,
            "probe_valid": False,
            "input_path_valid": True,
            "output_path_valid": False,
            "probe_error": f"Review repair_target {issue_id} input_probe.output_path is not in latest output: {output_path}",
        }
    edited_inputs = json.loads(json.dumps(base_inputs))
    _set_path(edited_inputs, input_path, probe.get("changed_value"))
    try:
        changed_output = package_runtime.execute_package(package_dir, edited_inputs)
        changed_path_exists, changed_value = _get_output_path_value(changed_output, output_path)
        if not changed_path_exists:
            raise RuntimeError(f"changed output is missing {output_path}")
        expectation = _repair_probe_expectation(expected_behavior, base_value, changed_value)
        return {
            "executed": True,
            "probe_valid": True,
            "input_path_valid": True,
            "output_path_valid": True,
            "base_output_value": base_value,
            "changed_output_value": changed_value,
            "changed_output_fingerprint": _output_fingerprint(changed_output),
            "expected_behavior": expected_behavior,
            "expected_behavior_met": expectation.get("met"),
            "expected_behavior_evaluable": expectation.get("evaluable"),
            "observed_behavior": expectation.get("observed_behavior"),
            "confirmed_issue": expectation.get("met") is False,
        }
    except Exception as exc:
        return {
            "executed": False,
            "probe_valid": True,
            "input_path_valid": True,
            "output_path_valid": True,
            "base_output_value": base_value,
            "expected_behavior": expected_behavior,
            "execution_error": str(exc),
            "confirmed_issue": True,
        }


def _get_output_path_value(root: Any, path: str) -> tuple[bool, Any]:
    if not path:
        return False, None
    current: Any = root
    normalized_path = re.sub(r"\[(\d+)\]", r".\1", path).strip(".")
    for part in normalized_path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            if part.isdigit():
                index = int(part)
                if index < 0 or index >= len(current):
                    return False, None
                current = current[index]
            else:
                matches = [item for item in current if isinstance(item, dict) and item.get("id") == part]
                if not matches:
                    return False, None
                current = matches[0]
        else:
            return False, None
    return True, current


def _repair_probe_expectation(expected_behavior: str, base_value: Any, changed_value: Any) -> dict[str, Any]:
    same = _output_fingerprint(base_value) == _output_fingerprint(changed_value) if isinstance(base_value, dict) or isinstance(changed_value, dict) else base_value == changed_value
    if expected_behavior == "same":
        return {"evaluable": True, "met": same, "observed_behavior": "same" if same else "changed"}
    if expected_behavior == "change":
        return {"evaluable": True, "met": not same, "observed_behavior": "same" if same else "changed"}
    if expected_behavior == "not_null":
        return {"evaluable": True, "met": changed_value is not None, "observed_behavior": "not_null" if changed_value is not None else "null"}
    if not _is_number(base_value) or not _is_number(changed_value):
        return {"evaluable": False, "met": None, "observed_behavior": "non_numeric"}
    if changed_value > base_value:
        observed = "increase"
    elif changed_value < base_value:
        observed = "decrease"
    else:
        observed = "same"
    return {"evaluable": True, "met": observed == expected_behavior, "observed_behavior": observed}


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _fallback_failure_reasons(report: dict[str, Any]) -> list[str]:
    reasons = [str(item) for item in report.get("repair_instructions") or [] if str(item).strip()]
    if reasons:
        return reasons
    summary = str(report.get("summary") or "").strip()
    return [summary or "Review Agent denied the repaired package."]


def _snapshot_package(root: Path, target_name: str) -> str:
    source = root / "model_package"
    target = root / target_name
    if target.exists():
        shutil.rmtree(target)
    if source.exists():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        target.mkdir(parents=True, exist_ok=True)
    return target_name


def _append_final_trace(root: Path, status: str, summary: str) -> None:
    model_trace.append_event(
        root,
        "final_review_status",
        actor="backend",
        recipient="trace",
        stage="review_cycle",
        status=status,
        summary=summary,
        payload={"final_status": status, "stop_reason": summary},
    )


def _gate_snapshot(package_dir: Path) -> dict[str, Any]:
    validation = _read_json(package_dir / "reports" / "validation_report.json")
    stress = _read_json(package_dir / "reports" / "mechanical_stress_report.json")
    model_tests = _read_json(package_dir / "reports" / "model_tests_report.json")
    gates = {
        "validation_passed": validation.get("passed") is True,
        "mechanical_stress_passed": stress.get("passed") is True,
        "model_tests_passed": model_tests.get("passed") is True,
    }
    return {
        **gates,
        "gate_pass_count": sum(1 for passed in gates.values() if passed),
        "passed": all(gates.values()),
        "validation_report": validation,
        "mechanical_stress_report": stress,
        "model_tests_report": model_tests,
    }


def _capture_pre_self_check_evidence(
    root: Path,
    *,
    package_files: list[dict[str, str]],
    base_inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    package_dir = root / "pre_self_check_package"
    evidence: dict[str, Any]
    try:
        clean_files = _validate_package_files(package_files, source="pre_self_check package_files")
        _write_text(package_dir / "model" / "__init__.py", "")
        for file_record in clean_files:
            _write_text(package_dir / file_record["path"], file_record["content"])
        _write_json(package_dir / "inputs" / "input_schema.json", _validate_input_schema(schema, base_inputs, source="pre_self_check input_schema"))
        _write_json(package_dir / "inputs" / "base_case.json", base_inputs)
        _write_json(package_dir / "inputs" / "scenarios.json", {"scenario_cases": _parse_scenario_cases(scenarios, source="pre_self_check scenario_cases")})
        validation, output = validate_package(package_dir, base_inputs)
        stress = run_mechanical_stress(package_dir)
        model_tests = run_model_tests(package_dir, output, stress, active_inputs=base_inputs)
        _write_json(package_dir / "outputs" / "output.json", output)
        _write_json(package_dir / "reports" / "validation_report.json", validation)
        _write_json(package_dir / "reports" / "mechanical_stress_report.json", stress)
        _write_json(package_dir / "reports" / "model_tests_report.json", model_tests)
        evidence = {"available": True, **_gate_snapshot(package_dir)}
    except Exception as exc:
        evidence = {"available": False, "passed": False, "gate_pass_count": 0, "error": str(exc)}
    report = _read_json(root / "workflow_stage_evidence.json")
    report.update({"created_utc": report.get("created_utc") or _utc_now(), "draft": evidence})
    _write_json(root / "workflow_stage_evidence.json", report)
    model_trace.append_event(
        root,
        "pre_self_check_package_evaluated",
        actor="backend",
        recipient="trace",
        stage="modeler_package_draft",
        status="passed" if evidence.get("passed") else "failed",
        payload={key: value for key, value in evidence.items() if not key.endswith("_report")},
        artifacts={"pre_self_check_package": "pre_self_check_package", "workflow_stage_evidence": "workflow_stage_evidence.json"},
    )
    return evidence


def _record_workflow_stage(root: Path, stage: str) -> dict[str, Any]:
    report = _read_json(root / "workflow_stage_evidence.json")
    snapshot = _gate_snapshot(root / "model_package")
    draft = report.get("draft") if isinstance(report.get("draft"), dict) else {}
    draft_count = int(draft.get("gate_pass_count") or 0)
    snapshot["gate_delta_from_draft"] = int(snapshot.get("gate_pass_count") or 0) - draft_count
    snapshot["improved_from_draft"] = snapshot["gate_delta_from_draft"] > 0
    snapshot["regressed_from_draft"] = snapshot["gate_delta_from_draft"] < 0
    report.update({"created_utc": report.get("created_utc") or _utc_now(), stage: snapshot, "latest_stage": stage})
    _write_json(root / "workflow_stage_evidence.json", report)
    return report


def write_package(
    root: Path,
    manifest: dict[str, Any],
    prompt: str,
    inputs: dict[str, Any],
    schema: dict[str, Any],
    scenarios: list[dict[str, Any]],
    package_files: list[dict[str, str]],
    self_check: dict[str, Any],
    usage_report: dict[str, Any],
    approved_spec: dict[str, Any] | None = None,
) -> None:
    package_dir = root / "model_package"
    staging_dir = root / "model_package.__staging__"
    backup_dir = root / "model_package.__previous__"
    for disposable in (staging_dir, backup_dir):
        if disposable.exists():
            shutil.rmtree(disposable)
    clean_package_files = _validate_package_files(package_files, source="package_files")
    _write_text(staging_dir / "run.py", "from model.main import run_model\n\n\ndef main(inputs):\n    return run_model(inputs)\n")
    _write_text(staging_dir / "model" / "__init__.py", "")
    for file_record in clean_package_files:
        _write_text(staging_dir / file_record["path"], file_record["content"])
    _write_json(staging_dir / "inputs" / "input_schema.json", _validate_input_schema(schema, inputs, source="package input_schema"))
    _write_json(staging_dir / "inputs" / "base_case.json", inputs)
    _write_json(staging_dir / "inputs" / "scenarios.json", {"scenario_cases": _parse_scenario_cases(scenarios, source="package scenario_cases")})
    if approved_spec:
        _write_json(staging_dir / "spec" / "model_spec.json", approved_spec.get("model_spec") or approved_spec)
    for artifact_name in ("model_thesis.json", "equation_graph.json", "model_tests.json"):
        root_artifact = _read_json(root / artifact_name)
        if root_artifact:
            _write_json(staging_dir / "spec" / artifact_name, root_artifact)
    _write_json(staging_dir / "reports" / "modeler_self_check.json", self_check)
    presentation_report = self_check.get("presentation_agent_report") if isinstance(self_check, dict) else None
    if isinstance(presentation_report, dict) and presentation_report:
        _write_json(staging_dir / "reports" / "presentation_agent_report.json", presentation_report)
    if package_dir.exists():
        package_dir.replace(backup_dir)
    try:
        staging_dir.replace(package_dir)
    except Exception:
        if backup_dir.exists() and not package_dir.exists():
            backup_dir.replace(package_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    _write_json(
        root / "compiler_manifest.json",
        {
            "manifest_version": "model_package",
            "compile_strategy": "workspace_tool_loop" if self_check.get("transport") == "workspace_tool_loop" else "modeler_package_files",
            "generated_package_architecture": "boring_multi_file",
            "model_package": True,
            "requires_openai_for_build": True,
            "support_tier": "review_required",
            "publish_warning": PASS_MESSAGE,
        },
    )
    _write_json(
        root / "source_provenance.json",
        {
            "prompt": prompt,
            "openai_called": True,
            "model_spec": "model_spec.json",
            "model_thesis": "model_thesis.json",
            "equation_graph": "equation_graph.json",
            "model_tests": "model_tests.json",
            "package_model_spec": "model_package/spec/model_spec.json" if approved_spec else "",
            "model_spec_status": approved_spec.get("status") if approved_spec else "",
            "model_spec_approved": bool((approved_spec or {}).get("status") == "approved"),
            "generated_files": [f"model_package/{item['path']}" for item in clean_package_files],
            "self_check_report": "model_package/reports/modeler_self_check.json",
            "scenario_cases": "model_package/inputs/scenarios.json",
            "mechanical_stress_report": "model_package/reports/mechanical_stress_report.json",
            "model_tests_report": "model_package/reports/model_tests_report.json",
            "review_report": "model_package/reports/review_report.json",
            "presentation_agent_report": "model_package/reports/presentation_agent_report.json",
            "review_execution_evidence": "model_package/reports/review_execution_evidence.json",
            "rerun_execution_evidence": "model_package/reports/rerun_execution_evidence.json",
            "workflow_stage_evidence": "workflow_stage_evidence.json",
            "agent_tool_calls_report": "model_package/reports/agent_tool_calls_report.json",
            "repair_plan": "model_package/reports/repair_plan.json",
            "review_history": "model_package/reports/review_history.json",
            "required_amendments_report": "model_package/reports/required_amendments_report.json",
            "usage_report_path": "usage_report.json",
            "modeler_transport": self_check.get("transport") or "legacy_whole_package",
            "code_interpreter_required": self_check.get("code_interpreter_required", True),
        },
    )
    _update_version_manifest(root, "draft", usage_report=usage_report)


def run_minimal(manifest: dict[str, Any], version_id: str, input_params: dict[str, Any], *, published: bool) -> dict[str, Any]:
    root = version_dir(str(manifest["model_id"]), version_id)
    package_dir = root / "model_package"
    validation, output = validate_package(package_dir, input_params)
    stress_report = run_mechanical_stress(package_dir)
    model_tests_report = run_model_tests(package_dir, output, stress_report, active_inputs=input_params)
    _write_minimal_output_artifact(package_dir, output)
    _write_json(package_dir / "reports" / "validation_report.json", validation)
    _write_json(package_dir / "reports" / "mechanical_stress_report.json", stress_report)
    _write_json(package_dir / "reports" / "model_tests_report.json", model_tests_report)
    model_trace.append_event(
        root,
        "backend_validation_result",
        actor="backend",
        recipient="trace",
        stage="backend_validation",
        status="passed" if validation.get("passed") else "failed",
        payload=validation,
        artifacts={"validation_report": "model_package/reports/validation_report.json"},
    )
    model_trace.append_event(
        root,
        "backend_mechanical_stress_result",
        actor="backend",
        recipient="trace",
        stage="backend_mechanical_stress",
        status="passed" if stress_report.get("passed") else "failed",
        payload=stress_report,
        artifacts={"mechanical_stress_report": "model_package/reports/mechanical_stress_report.json"},
    )
    model_trace.append_event(
        root,
        "backend_model_tests_result",
        actor="backend",
        recipient="trace",
        stage="backend_model_tests",
        status="passed" if model_tests_report.get("passed") else "failed",
        payload=model_tests_report,
        artifacts={"model_tests_report": "model_package/reports/model_tests_report.json"},
    )
    passed = bool(validation.get("passed") and stress_report.get("passed") and model_tests_report.get("passed"))
    status = "published" if published and passed else "review_ready" if passed else "failed_checks"
    state = _update_version_manifest(root, status, latest_run_status="passed" if passed else "backend_checks_failed")
    if passed:
        failure_path = root / "failure_report.json"
        if failure_path.exists():
            failure_path.unlink()
        for key in ("failure_report", "failure_code", "failure_subcode", "failure_stage", "failure_reasons", "next_actions"):
            state.pop(key, None)
        _write_json(root / "version_manifest.json", state)
    if not passed:
        code = (
            "backend_validation_failed"
            if validation.get("passed") is not True
            else "mechanical_stress_failed"
            if stress_report.get("passed") is not True
            else "model_tests_failed"
        )
        report_path = (
            "model_package/reports/validation_report.json"
            if code == "backend_validation_failed"
            else "model_package/reports/mechanical_stress_report.json"
            if code == "mechanical_stress_failed"
            else "model_package/reports/model_tests_report.json"
        )
        return _write_failure_report(
            root,
            code=code,
            stage=(
                "backend_validation"
                if code == "backend_validation_failed"
                else "backend_mechanical_stress"
                if code == "mechanical_stress_failed"
                else "backend_model_tests"
            ),
            message="Backend package checks failed.",
            reasons=_backend_failure_reasons(validation, stress_report, model_tests_report),
            status=status,
            next_actions=FAILURE_NEXT_ACTIONS.get(code),
            artifacts={code: report_path},
        )
    return state


def validate_package(package_dir: Path, input_params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    import_check = _source_policy_check(package_dir)
    callable_check = {"id": "run_model_callable", "passed": import_check.get("run_model_found", False)}
    checks_callable_check = {"id": "run_checks_callable", "passed": import_check.get("run_checks_found", False)}
    output: dict[str, Any] = {}
    execution_error = ""
    input_contract_check = _input_contract_check(package_dir)
    try:
        output = package_runtime.execute_package(package_dir, input_params)
    except Exception as exc:
        execution_error = str(exc)
    output_contract = validate_output_contract(output)
    missing_input_check = _missing_required_input_check(package_dir, input_params) if not execution_error else {
        "id": "missing_required_inputs_fail",
        "passed": False,
        "skipped": True,
        "error": "Skipped because base package execution failed.",
    }
    passed = bool(
        import_check["passed"]
        and callable_check["passed"]
        and checks_callable_check["passed"]
        and input_contract_check["passed"]
        and output_contract["passed"]
        and missing_input_check["passed"]
        and not execution_error
    )
    validation = {
        "passed": passed,
        "message": PASS_MESSAGE if passed else "Package required checks failed.",
        "checks": [
            {"id": "package_imports", "passed": import_check["passed"], "error": import_check.get("error", "")},
            callable_check,
            checks_callable_check,
            input_contract_check,
            {"id": "output_contract_valid", "passed": output_contract["passed"], "report": output_contract},
            missing_input_check,
        ],
        "output_contract_report": output_contract,
    }
    if execution_error:
        validation["execution_error"] = execution_error
    return validation, output


def run_model_tests(
    package_dir: Path,
    base_output: dict[str, Any],
    stress_report: dict[str, Any],
    *,
    active_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declared = _declared_model_tests(package_dir)
    if not declared:
        return {
            "passed": False,
            "message": "No declared model tests were found.",
            "declared_tests": [],
            "checks": [{"id": "model_tests_declared", "passed": False, "error": "model_tests.json is missing or empty"}],
            "case_reports": [],
        }
    base_inputs = json.loads(json.dumps(active_inputs)) if isinstance(active_inputs, dict) else _read_json(package_dir / "inputs" / "base_case.json")
    scenarios = []
    try:
        scenarios = _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json")
    except Exception:
        scenarios = []
    scenario_by_id = {case.get("id"): case for case in scenarios if isinstance(case, dict)}
    case_reports: list[dict[str, Any]] = []
    declared_ids = [check["id"] for check in declared]
    case_test_ids = [check["id"] for check in declared if check.get("execution_scope", "case") == "case"]
    suite_test_ids = [check["id"] for check in declared if check.get("execution_scope") == "scenario_suite"]
    required_case_ids = ["base", "downside", "upside"]
    execution_errors: list[dict[str, str]] = []
    executed_cases: dict[str, dict[str, Any]] = {}

    for case_id in required_case_ids:
        inputs = json.loads(json.dumps(base_inputs))
        output = base_output if case_id == "base" else None
        case = scenario_by_id.get(case_id)
        if case_id != "base" and case:
            for path, value in (case.get("input_overrides") or {}).items():
                if isinstance(path, str):
                    _set_path(inputs, path, value)
        try:
            if output is None:
                output = package_runtime.execute_package(package_dir, inputs)
            executed_cases[case_id] = {"inputs": inputs, "output": output}
            raw_report = package_runtime.execute_package_checks(package_dir, inputs, output)
            parsed = _validate_model_test_execution_report(raw_report, case_test_ids, case_id=case_id)
            case_reports.append(parsed)
        except Exception as exc:
            execution_errors.append({"case_id": case_id, "error": str(exc)})
            case_reports.append({"case_id": case_id, "passed": False, "error": str(exc), "checks": []})

    suite_report: dict[str, Any] | None = None
    if suite_test_ids and not execution_errors and set(executed_cases) == set(required_case_ids):
        try:
            raw_suite_report = package_runtime.execute_package_suite_checks(package_dir, executed_cases)
            suite_report = _validate_model_test_execution_report(
                raw_suite_report,
                suite_test_ids,
                case_id="scenario_suite",
            )
        except Exception as exc:
            execution_errors.append({"case_id": "scenario_suite", "error": str(exc)})
            suite_report = {"case_id": "scenario_suite", "passed": False, "error": str(exc), "checks": []}

    failed_checks = [
        {"case_id": report.get("case_id"), "execution_scope": "case", "id": check.get("id"), "message": check.get("message") or ""}
        for report in case_reports
        for check in report.get("checks") or []
        if check.get("status") == "failed"
    ]
    if suite_report:
        failed_checks.extend(
            {
                "case_id": "scenario_suite",
                "execution_scope": "scenario_suite",
                "id": check.get("id"),
                "message": check.get("message") or "",
            }
            for check in suite_report.get("checks") or []
            if check.get("status") == "failed"
        )
    skipped_checks = [
        {"case_id": report.get("case_id"), "execution_scope": "case", "id": check.get("id"), "message": check.get("message") or ""}
        for report in case_reports
        for check in report.get("checks") or []
        if check.get("status") == "skipped"
    ]
    if suite_report:
        skipped_checks.extend(
            {
                "case_id": "scenario_suite",
                "execution_scope": "scenario_suite",
                "id": check.get("id"),
                "message": check.get("message") or "",
            }
            for check in suite_report.get("checks") or []
            if check.get("status") == "skipped"
        )
    passed = bool(
        declared
        and case_test_ids
        and not execution_errors
        and not failed_checks
        and all(report.get("passed") is True for report in case_reports)
        and (not suite_test_ids or bool(suite_report and suite_report.get("passed") is True))
    )
    return {
        "passed": passed,
        "message": "Model-local tests executed." if passed else "Model-local tests failed.",
        "declared_tests": declared,
        "declared_test_ids": declared_ids,
        "checks": [
            {"id": "model_tests_declared", "passed": bool(declared), "declared_test_ids": declared_ids},
            {"id": "model_tests_executed", "passed": not execution_errors, "execution_errors": execution_errors},
            {
                "id": "model_tests_all_passed",
                "passed": not failed_checks,
                "false_tests": failed_checks,
                "skipped_tests": skipped_checks,
            },
        ],
        "case_reports": case_reports,
        "suite_report": suite_report,
        "mechanical_stress_passed": stress_report.get("passed") is True,
    }


def _read_package_files(package_dir: Path) -> list[dict[str, str]]:
    model_dir = package_dir / "model"
    if not model_dir.exists():
        return []
    files: list[dict[str, str]] = []
    for path in sorted(model_dir.rglob("*.py")):
        relative = path.relative_to(package_dir).as_posix()
        if relative == "model/__init__.py":
            continue
        files.append({"path": relative, "content": path.read_text(encoding="utf-8")})
    return files


def _validate_model_test_execution_report(raw: Any, declared_ids: list[str], *, case_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("run_checks must return a JSON object.")
    checks = raw.get("checks")
    if not isinstance(checks, list) or not checks:
        raise RuntimeError("run_checks report must include a non-empty checks array.")
    by_id: dict[str, dict[str, Any]] = {}
    parsed_checks: list[dict[str, Any]] = []
    invalid: list[str] = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            invalid.append(f"checks[{index}] must be an object")
            continue
        check_id = item.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            invalid.append(f"checks[{index}].id must be a non-empty string")
            continue
        if check_id in by_id:
            invalid.append(f"checks[{index}].id is duplicated: {check_id}")
        passed = item.get("passed")
        if not isinstance(passed, bool):
            invalid.append(f"checks[{index}].passed must be a boolean")
        raw_status = item.get("status")
        if raw_status is None:
            status = "passed" if passed is True else "failed"
        elif raw_status not in {"passed", "failed", "skipped"}:
            status = "failed"
            invalid.append(f"checks[{index}].status must be passed, failed, or skipped")
        else:
            status = raw_status
        if status == "passed" and passed is not True:
            invalid.append(f"checks[{index}] status passed requires passed=true")
        if status in {"failed", "skipped"} and passed is not False:
            invalid.append(f"checks[{index}] status {status} requires passed=false")
        message = item.get("message")
        if not isinstance(message, str) or not message.strip():
            invalid.append(f"checks[{index}].message must be a non-empty string")
        evidence = item.get("evidence")
        if not isinstance(evidence, dict) or not evidence:
            invalid.append(f"checks[{index}].evidence must be a non-empty object")
        if status == "skipped" and (not isinstance(evidence, dict) or evidence.get("not_applicable") is not True):
            invalid.append(f"checks[{index}] status skipped requires evidence.not_applicable=true")
        parsed_item = {
            "id": check_id,
            "passed": passed,
            "status": status,
            "message": message.strip() if isinstance(message, str) else "",
            "evidence": dict(evidence) if isinstance(evidence, dict) else {},
        }
        by_id[check_id] = parsed_item
        parsed_checks.append(parsed_item)
    missing = [check_id for check_id in declared_ids if check_id not in by_id]
    if missing:
        invalid.append("run_checks missing declared model tests: " + ", ".join(missing))
    unexpected = [check_id for check_id in by_id if check_id not in declared_ids]
    if unexpected:
        invalid.append("check report returned tests for the wrong execution scope: " + ", ".join(unexpected))
    if invalid:
        raise RuntimeError("run_checks report is invalid: " + "; ".join(invalid))
    failed_checks = [check for check in parsed_checks if check.get("status") == "failed"]
    skipped_checks = [check for check in parsed_checks if check.get("status") == "skipped"]
    return {
        "case_id": case_id,
        "passed": not failed_checks,
        "checks": parsed_checks,
        "false_checks": failed_checks,
        "failed_checks": failed_checks,
        "skipped_checks": skipped_checks,
        "counts": {
            "passed": sum(1 for check in parsed_checks if check.get("status") == "passed"),
            "failed": len(failed_checks),
            "skipped": len(skipped_checks),
        },
    }


def read_state(manifest: dict[str, Any], selected_artifact: str | None = None, state_override: dict[str, Any] | None = None) -> dict[str, Any]:
    version_id = str(manifest.get("current_version_id") or manifest.get("canonical_version_id") or "")
    if not version_id:
        return {"version_id": None, "status": "not_started", "publish_eligible": False}
    root = version_dir(str(manifest["model_id"]), version_id)
    state = state_override or _read_json(root / "version_manifest.json")
    status = str(state.get("status") or "draft")
    selected = selected_artifact or (
        "model_package/outputs/output.json"
        if status in {"review_ready", "published"}
        else "model_spec.json"
        if status in {"spec_draft", "spec_approved"}
        else "model_package/model/main.py"
    )
    latest_output = _read_json(root / "model_package" / "outputs" / "output.json")
    spec_payload = _read_json(root / "model_spec.json")
    validation_report = _read_json(root / "model_package" / "reports" / "validation_report.json")
    mechanical_report = _read_json(root / "model_package" / "reports" / "mechanical_stress_report.json")
    model_tests_report = _read_json(root / "model_package" / "reports" / "model_tests_report.json")
    self_check = _read_json(root / "model_package" / "reports" / "modeler_self_check.json")
    review_report = _read_json(root / "model_package" / "reports" / "review_report.json")
    review_evidence = _read_json(root / "model_package" / "reports" / "review_execution_evidence.json")
    required_amendments_report = _read_json(root / "model_package" / "reports" / "required_amendments_report.json")
    review_history = _read_json(root / "review_history.json")
    repair_plan = _read_json(root / "model_package" / "reports" / "repair_plan.json")
    failure_report = _read_json(root / "failure_report.json")
    previous_reference = _read_json(root / "previous_version_reference.json")
    change_summary = _read_json(root / "change_summary.json")
    model_thesis_payload = _read_json(root / "model_thesis.json")
    equation_graph_payload = _read_json(root / "equation_graph.json")
    model_tests_payload = _read_json(root / "model_tests.json")
    agent_tool_calls_report = _read_json(root / "model_package" / "reports" / "agent_tool_calls_report.json")
    workflow_stage_evidence = _read_json(root / "workflow_stage_evidence.json")
    rerun_execution_evidence = _read_json(root / "model_package" / "reports" / "rerun_execution_evidence.json")
    input_schema_payload = _read_json(root / "model_package" / "inputs" / "input_schema.json")
    resolved_input_params = state.get("resolved_input_params") or _read_json(root / "model_package" / "inputs" / "base_case.json")
    return {
        "version_id": version_id,
        "canonical_version_id": manifest.get("canonical_version_id"),
        "status": status,
        "status_label": "Review-ready" if status == "review_ready" else "Published" if status == "published" else status.replace("_", " ").title(),
        "stages": _stages(status),
        "human_review_required": True,
        "publish_eligible": status == "review_ready",
        "artifact_root": _display_path(root),
        "artifact_tree": _artifact_tree(root),
        "selected_artifact": read_artifact(manifest, selected) if selected else None,
        "input_schema": input_schema_payload,
        "build_source": "modeler_package_files",
        "published_rerun_uses_saved_package": status == "published",
        "latest_run_status": state.get("latest_run_status") or status,
        "runtime_contract_defect": state.get("runtime_contract_defect"),
        "compiler_manifest": _read_json(root / "compiler_manifest.json"),
        "source_provenance": _read_json(root / "source_provenance.json"),
        "model_spec": spec_payload.get("model_spec") or {},
        "model_spec_status": spec_payload.get("status") or "missing",
        "model_spec_path": spec_payload.get("path") or ("model_spec.json" if spec_payload else ""),
        "model_spec_approval": spec_payload.get("approval") or {},
        "model_thesis": model_thesis_payload.get("model_thesis") or {},
        "model_thesis_status": model_thesis_payload.get("status") or ("ready" if model_thesis_payload else "missing"),
        "model_thesis_path": model_thesis_payload.get("path") or ("model_thesis.json" if model_thesis_payload else ""),
        "equation_graph": equation_graph_payload.get("equation_graph") or {},
        "equation_graph_status": equation_graph_payload.get("status") or ("ready" if equation_graph_payload else "missing"),
        "equation_graph_path": equation_graph_payload.get("path") or ("equation_graph.json" if equation_graph_payload else ""),
        "model_tests": model_tests_payload.get("model_tests") or [],
        "model_tests_status": model_tests_payload.get("status") or ("ready" if model_tests_payload else "missing"),
        "model_tests_path": model_tests_payload.get("path") or ("model_tests.json" if model_tests_payload else ""),
        "amendment_status": state.get("amendment_status") or ("not_amended" if not previous_reference else ""),
        "amendment_count": int(state.get("amendment_count") or previous_reference.get("amendment_count") or 0),
        "previous_version_id": state.get("previous_version_id") or previous_reference.get("previous_version_id") or "",
        "change_summary": change_summary,
        "pre_publish_summary": _pre_publish_summary(
            status=status,
            spec_payload=spec_payload,
            validation_report=validation_report,
            mechanical_report=mechanical_report,
            model_tests_report=model_tests_report,
            self_check=self_check,
            review_report=review_report,
            review_evidence=review_evidence,
            repair_plan=repair_plan,
            latest_output=latest_output,
            input_schema=input_schema_payload,
            resolved_input_params=resolved_input_params,
        ),
        "validation_report": validation_report,
        "mechanical_stress_report": mechanical_report,
        "model_tests_report": model_tests_report,
        "modeler_self_check": self_check,
        "presentation_agent_report": _read_json(root / "model_package" / "reports" / "presentation_agent_report.json"),
        "review_report": review_report,
        "review_execution_evidence": review_evidence,
        "required_amendments_report": required_amendments_report,
        "review_history": review_history,
        "agent_tool_calls_report": agent_tool_calls_report,
        "workflow_stage_evidence": workflow_stage_evidence,
        "rerun_execution_evidence": rerun_execution_evidence,
        "repair_plan": repair_plan,
        "failure_report": failure_report,
        "failure_code": failure_report.get("failure_code") or state.get("failure_code") or "",
        "failure_subcode": failure_report.get("failure_subcode") or state.get("failure_subcode") or "",
        "failure_stage": failure_report.get("failure_stage") or state.get("failure_stage") or "",
        "failure_reasons": failure_report.get("failure_reasons") or state.get("failure_reasons") or [],
        "next_actions": failure_report.get("next_actions") or state.get("next_actions") or [],
        "backend_repair_attempted": bool(state.get("backend_repair_attempted")),
        "backend_repair_attempts_used": int(state.get("backend_repair_attempts_used") or 0),
        "backend_repair_max_attempts": int(state.get("backend_repair_max_attempts") or 0),
        "backend_repair_status": state.get("backend_repair_status") or "",
        "review_failure_reasons": review_report.get("failure_reasons") or [],
        "latest_output": latest_output,
        "openai_calls": state.get("openai_calls", []),
        "openai_budget": {},
        "package_entrypoint": "model_package/model/main.py" if (root / "model_package" / "model" / "main.py").exists() else "",
        "package_files": [item["path"] for item in _read_package_files(root / "model_package")],
        "resolved_input_params": resolved_input_params,
    }


def _pre_publish_summary(
    *,
    status: str,
    spec_payload: dict[str, Any],
    validation_report: dict[str, Any],
    mechanical_report: dict[str, Any],
    model_tests_report: dict[str, Any] | None = None,
    self_check: dict[str, Any],
    review_report: dict[str, Any],
    review_evidence: dict[str, Any],
    repair_plan: dict[str, Any],
    latest_output: dict[str, Any],
    input_schema: dict[str, Any] | None = None,
    resolved_input_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in {"review_ready", "published", "review_failed"}:
        return {}
    sections = {
        "approved_spec": spec_payload.get("status") == "approved" and bool(spec_payload.get("model_spec")),
        "inputs": bool((input_schema or {}).get("fields") and resolved_input_params),
        "outputs": isinstance(latest_output.get("output_blocks"), list) and bool(latest_output.get("output_blocks")),
        "validation": bool(validation_report),
        "mechanical_stress": bool(mechanical_report),
        "model_tests": bool(model_tests_report),
        "review": bool(review_report),
        "technical_evidence": bool(self_check or review_evidence),
    }
    return {
        "status": "ready" if status == "review_ready" else "published" if status == "published" else "failed",
        "review_required_message": PASS_MESSAGE,
        "sections_present": sections,
        "all_sections_present": all(sections.values()),
        "can_publish": status == "review_ready" and review_report.get("approved") is True,
        "review_approved": review_report.get("approved") is True,
        "repair_attempted": bool(repair_plan.get("repair_attempted")),
        "failure_reasons": review_report.get("failure_reasons") or [],
        "human_questions": review_report.get("human_questions") or [],
        "artifact_paths": {
            "model_spec": "model_spec.json",
            "package_spec": "model_package/spec/model_spec.json",
            "validation_report": "model_package/reports/validation_report.json",
            "mechanical_stress_report": "model_package/reports/mechanical_stress_report.json",
            "model_tests_report": "model_package/reports/model_tests_report.json",
            "review_report": "model_package/reports/review_report.json",
            "modeler_self_check": "model_package/reports/modeler_self_check.json",
            "review_execution_evidence": "model_package/reports/review_execution_evidence.json",
        },
    }


def resolve_inputs(root: Path, input_params: dict[str, Any] | None, *, allow_defaults: bool) -> dict[str, Any]:
    if input_params:
        return input_params
    if allow_defaults:
        return _read_json(root / "model_package" / "inputs" / "base_case.json") or default_inputs()
    raise RuntimeError("Inputs are required for regular rerun.")


def read_artifact(manifest: dict[str, Any], relative_path: str | None) -> dict[str, Any] | None:
    version_id = str(manifest.get("current_version_id") or manifest.get("canonical_version_id") or "")
    if not version_id or not relative_path:
        return None
    root = version_dir(str(manifest["model_id"]), version_id).resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.exists() or target.is_dir():
        return None
    content: Any = _read_json(target) if target.suffix.lower() == ".json" else target.read_text(encoding="utf-8")
    return {"path": relative_path.replace("\\", "/"), "content": content, "kind": target.suffix.lower().lstrip(".") or "text"}


def _write_minimal_output_artifact(package_dir: Path, output: dict[str, Any]) -> None:
    outputs_dir = package_dir / "outputs"
    if outputs_dir.exists():
        for path in sorted(outputs_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    _write_json(outputs_dir / "output.json", output)


def _field(path: str, label: str, group: str, value: float, unit: str) -> dict[str, Any]:
    return {
        "path": path,
        "label": label,
        "group": group,
        "provenance": "editable_default",
        "value_number": value,
        "value_text": None,
        "type": "number",
        "unit": unit,
        "storage_scale": "decimal" if unit == "percent" else "native",
        "display_scale": "percent" if unit == "percent" else "native",
        "min_value": -1 if unit == "percent" else 0,
        "max_value": 2 if unit == "percent" else 1000000000,
        "required_for_publish": True,
        "read_only": False,
        "editable": True,
        "input_role": "editable_driver",
    }


def _validate_input_schema(raw: Any, base_inputs: dict[str, Any], *, source: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError(f"{source} must be a JSON object.")
    raw = json.loads(json.dumps(raw))
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields:
        raise RuntimeError(f"{source} must include a non-empty fields array.")
    invalid: list[str] = []
    scalar_paths = _scalar_paths(base_inputs)
    flexible_paths: set[str] = set()
    seen_paths: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            invalid.append(f"fields[{index}] must be an object")
            continue
        path = field.get("path")
        if not isinstance(path, str) or not path.strip():
            invalid.append(f"fields[{index}].path must be a non-empty string path")
            continue
        path = _normalize_data_path(path)
        field["path"] = path
        if path in seen_paths:
            invalid.append(f"fields[{index}].path is duplicated: {path}")
        seen_paths.add(path)
        if "editable" not in field or not isinstance(field.get("editable"), bool):
            invalid.append(f"fields[{index}].editable must be an explicit boolean")
        label = field.get("label")
        if not isinstance(label, str) or not label.strip():
            invalid.append(f"fields[{index}].label must be a non-empty string")
        field_type = field.get("type")
        if not isinstance(field_type, str) or not field_type.strip():
            invalid.append(f"fields[{index}].type must be a non-empty string")
        if not _path_exists(base_inputs, path):
            invalid.append(f"fields[{index}].path does not exist in base_inputs: {path}")
        elif field_type in {"number_or_13_number_array", "number_or_number_array"}:
            value = _get_path(base_inputs, path)
            period_count = 13 if field_type == "number_or_13_number_array" else field.get("period_count")
            if not isinstance(period_count, int) or isinstance(period_count, bool) or period_count < 2 or period_count > 366:
                invalid.append(f"fields[{index}].period_count must be an integer from 2 to 366 for type {field_type}")
                period_count = 0
            labels = field.get("period_labels")
            if field_type == "number_or_number_array" and (
                not isinstance(labels, list)
                or len(labels) != period_count
                or any(not isinstance(item, str) or not item.strip() for item in labels)
            ):
                invalid.append(f"fields[{index}].period_labels must contain exactly period_count non-empty labels for type number_or_number_array")
            valid_value = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
            ) or (
                isinstance(value, list)
                and len(value) == period_count
                and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
            )
            if not valid_value:
                invalid.append(
                    f"fields[{index}].path must point to a number or {period_count}-number array for type {field_type}: {path}"
                )
            else:
                flexible_paths.add(path)
        elif not _is_scalar(_get_path(base_inputs, path)):
            invalid.append(f"fields[{index}].path must point to a scalar base_inputs value: {path}")
    flexible_child_paths = {
        scalar_path
        for flexible_path in flexible_paths
        for scalar_path in scalar_paths
        if scalar_path.startswith(flexible_path + ".")
    }
    required_paths = (scalar_paths - flexible_child_paths) | flexible_paths
    missing_paths = sorted(required_paths - seen_paths)
    extra_paths = sorted(
        path
        for path in seen_paths
        if any(path.startswith(flexible_path + ".") for flexible_path in flexible_paths)
    )
    if missing_paths:
        invalid.append("input_schema.fields missing scalar base_inputs paths: " + ", ".join(missing_paths))
    if extra_paths:
        invalid.append("input_schema.fields contains paths not in scalar base_inputs: " + ", ".join(extra_paths))
    if invalid:
        raise RuntimeError(f"{source} is invalid: " + "; ".join(invalid))
    return raw


def _declared_model_tests(package_dir: Path) -> list[dict[str, Any]]:
    root = package_dir.parent
    tests_payload = _read_json(root / "model_tests.json")
    model_tests = tests_payload.get("model_tests") if isinstance(tests_payload.get("model_tests"), list) else tests_payload
    try:
        return _validate_declared_model_tests(model_tests, source="model_tests")
    except Exception:
        return []


def _validate_declared_model_tests(raw: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{source} must be a non-empty array.")
    required = ["id", "label", "test_type", "purpose", "logic_description", "evidence_expected", "repair_guidance"]
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    invalid: list[str] = []
    for index, item in enumerate(raw):
        item_path = f"[{index}]"
        if not isinstance(item, dict):
            invalid.append(f"{item_path} must be an object")
            continue
        extra = sorted(set(item.keys()) - (set(required) | {"severity", "execution_scope"}))
        if extra:
            invalid.append(f"{item_path} has unexpected fields: {', '.join(extra)}")
            continue
        missing = [key for key in required if not isinstance(item.get(key), str) or not str(item.get(key)).strip()]
        if missing:
            invalid.append(f"{item_path} missing non-empty string fields: {', '.join(missing)}")
            continue
        check_id = str(item["id"]).strip()
        if check_id in seen:
            invalid.append(f"{item_path}.id is duplicated: {check_id}")
            continue
        test_type = str(item.get("test_type") or "").strip()
        if test_type not in {"run_check", "input_probe", "output_presence"}:
            invalid.append(f"{item_path}.test_type must be run_check, input_probe, or output_presence")
            continue
        execution_scope = str(item.get("execution_scope") or "case").strip()
        if execution_scope not in {"case", "scenario_suite"}:
            invalid.append(f"{item_path}.execution_scope must be case or scenario_suite")
            continue
        seen.add(check_id)
        parsed_item = {key: str(item[key]).strip() for key in required}
        parsed_item["execution_scope"] = execution_scope
        if isinstance(item.get("severity"), str) and item["severity"].strip():
            parsed_item["severity"] = item["severity"].strip()
        parsed.append(parsed_item)
    if parsed and not any(item.get("execution_scope") == "case" for item in parsed):
        invalid.append("at least one model test must use execution_scope case")
    if invalid:
        raise RuntimeError(f"{source} is invalid: " + "; ".join(invalid))
    return parsed


def _read_scenario_cases_file(path: Path) -> list[dict[str, Any]]:
    raw = _read_json(path)
    if not isinstance(raw, dict) or sorted(raw.keys()) != ["scenario_cases"]:
        raise RuntimeError("Persisted scenarios.json must contain only scenario_cases.")
    return _parse_scenario_cases(raw.get("scenario_cases"), source="persisted scenario_cases")


def _parse_scenario_cases(raw: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise RuntimeError(f"{source} must be an array.")
    if len(raw) != 3:
        raise RuntimeError(f"{source} must contain exactly base, downside, and upside.")
    required_ids = {"base", "downside", "upside"}
    seen_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    invalid: list[str] = []
    for index, item in enumerate(raw):
        item_path = f"[{index}]"
        if not isinstance(item, dict):
            invalid.append(f"{item_path} must be an object")
            continue
        extra_keys = sorted(set(item.keys()) - {"id", "label", "description", "input_overrides"})
        if extra_keys:
            invalid.append(f"{item_path} has unexpected keys: {', '.join(extra_keys)}")
        case_id = item.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            invalid.append(f"{item_path}.id must be a non-empty string")
        elif case_id not in required_ids:
            invalid.append(f"{item_path}.id must be one of base, downside, or upside")
        else:
            if case_id in seen_ids:
                invalid.append(f"{item_path}.id is duplicated: {case_id}")
            seen_ids.add(case_id)
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            invalid.append(f"{item_path}.label must be a non-empty string")
        description = item.get("description")
        if not isinstance(description, str):
            invalid.append(f"{item_path}.description must be a string")
        overrides = item.get("input_overrides")
        if not isinstance(overrides, dict):
            invalid.append(f"{item_path}.input_overrides must be an object")
            overrides = {}
        else:
            normalized_overrides: dict[str, Any] = {}
            for path, value in overrides.items():
                if not isinstance(path, str) or not path.strip():
                    invalid.append(f"{item_path}.input_overrides keys must be non-empty string paths")
                else:
                    normalized_overrides[_normalize_data_path(path)] = value
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    invalid.append(f"{item_path}.input_overrides.{path} must be numeric")
            overrides = normalized_overrides
        if case_id == "base" and overrides:
            invalid.append(f"{item_path} Base input_overrides must be empty because base_inputs owns Base assumptions")
        if isinstance(case_id, str) and isinstance(label, str) and isinstance(description, str) and isinstance(overrides, dict):
            cases.append({**item, "input_overrides": overrides})
    missing = sorted(required_ids - seen_ids)
    if missing:
        invalid.append("missing required ids: " + ", ".join(missing))
    if invalid:
        raise RuntimeError(f"{source} is invalid: " + "; ".join(invalid))
    return cases


def run_mechanical_stress(package_dir: Path) -> dict[str, Any]:
    base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
    schema = _read_json(package_dir / "inputs" / "input_schema.json")
    required_ids = ["base", "downside", "upside"]
    try:
        scenarios = _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json")
        scenario_shape_error = ""
    except Exception as exc:
        scenarios = []
        scenario_shape_error = str(exc)
    scenario_by_id = {case["id"]: case for case in scenarios}
    valid_paths = _editable_numeric_paths(schema, base_inputs)
    cases: list[dict[str, Any]] = []
    fingerprints: dict[str, str] = {}
    output_keys: dict[str, list[str]] = {}
    missing_ids = [case_id for case_id in required_ids if case_id not in scenario_by_id]
    invalid_paths: list[dict[str, Any]] = []
    execution_errors: list[dict[str, str]] = []
    coverage_by_path: dict[str, list[str]] = {path: [] for path in sorted(valid_paths)}

    for case_id in required_ids:
        case = scenario_by_id.get(case_id)
        if not case:
            continue
        inputs = json.loads(json.dumps(base_inputs))
        overrides = case.get("input_overrides") if isinstance(case.get("input_overrides"), dict) else {}
        case_invalid = []
        for path, value in overrides.items():
            clean_path = str(path)
            if clean_path not in valid_paths or isinstance(value, bool) or not isinstance(value, (int, float)):
                case_invalid.append({"path": clean_path, "value": value})
                continue
            if case_id != "base":
                coverage_by_path.setdefault(clean_path, []).append(case_id)
            _set_path(inputs, clean_path, value)
        if case_invalid:
            invalid_paths.extend({"scenario_id": case_id, **item} for item in case_invalid)
        try:
            output = package_runtime.execute_package(package_dir, inputs)
            fingerprint = _output_fingerprint(output)
            fingerprints[case_id] = fingerprint
            output_keys[case_id] = sorted(output.keys()) if isinstance(output, dict) else []
            cases.append(
                {
                    "id": case_id,
                    "label": case["label"],
                    "passed": not case_invalid,
                    "input_overrides": overrides,
                    "invalid_paths": case_invalid,
                    "output_fingerprint": fingerprint,
                    "output_keys": output_keys[case_id],
                    "changed_vs_base": False,
                }
            )
        except Exception as exc:
            execution_errors.append({"scenario_id": case_id, "error": str(exc)})
            cases.append(
                {
                    "id": case_id,
                    "label": case["label"],
                    "passed": False,
                    "input_overrides": overrides,
                    "invalid_paths": case_invalid,
                    "execution_error": str(exc),
                    "changed_vs_base": False,
                }
            )

    base_fingerprint = fingerprints.get("base", "")
    base_keys = output_keys.get("base", [])
    comparable = bool(base_keys) and all(output_keys.get(case_id) == base_keys for case_id in required_ids if case_id in fingerprints)
    changed_ids = []
    unchanged_ids = []
    for row in cases:
        if row["id"] == "base":
            continue
        changed = bool(base_fingerprint and row.get("output_fingerprint") and row.get("output_fingerprint") != base_fingerprint)
        row["changed_vs_base"] = changed
        if changed:
            changed_ids.append(row["id"])
        else:
            unchanged_ids.append(row["id"])
    required_present = not missing_ids and not scenario_shape_error
    paths_valid = not invalid_paths
    execution_passed = not execution_errors and len(fingerprints) == len(required_ids)
    movement_passed = not missing_ids and not unchanged_ids and all(case_id in changed_ids for case_id in ("downside", "upside"))
    covered_paths = sorted(path for path, scenario_ids in coverage_by_path.items() if scenario_ids)
    missing_paths = sorted(path for path, scenario_ids in coverage_by_path.items() if not scenario_ids)
    coverage_ratio = round(len(covered_paths) / len(valid_paths), 6) if valid_paths else 0.0
    coverage_passed = bool(valid_paths) and not missing_paths
    shape_passed = not scenario_shape_error
    passed = bool(shape_passed and required_present and paths_valid and coverage_passed and execution_passed and comparable and movement_passed)
    return {
        "passed": passed,
        "message": "Mechanical stress scenarios executed; business review required." if passed else "Mechanical stress scenarios failed.",
        "required_scenarios": required_ids,
        "checks": [
            {"id": "scenario_cases_shape_valid", "passed": shape_passed, "error": scenario_shape_error},
            {"id": "required_scenarios_present", "passed": required_present, "missing_ids": missing_ids},
            {"id": "scenario_paths_valid", "passed": paths_valid, "invalid_paths": invalid_paths},
            {
                "id": "scenario_covers_editable_inputs",
                "passed": coverage_passed,
                "editable_paths": sorted(valid_paths),
                "covered_paths": covered_paths,
                "missing_paths": missing_paths,
                "coverage_ratio": coverage_ratio,
                "coverage_by_path": coverage_by_path,
            },
            {"id": "scenario_execution", "passed": execution_passed, "execution_errors": execution_errors},
            {"id": "scenario_outputs_comparable", "passed": comparable, "comparable_output_keys": base_keys},
            {"id": "non_base_scenarios_change_outputs", "passed": movement_passed, "changed_ids": changed_ids, "unchanged_ids": unchanged_ids},
        ],
        "cases": cases,
    }


def _source_policy_check(package_dir: Path) -> dict[str, Any]:
    try:
        model_dir = package_dir / "model"
        package_files = []
        for path in sorted(model_dir.rglob("*.py")):
            relative = path.relative_to(package_dir).as_posix()
            if relative == "model/__init__.py":
                continue
            package_files.append({"path": relative, "content": path.read_text(encoding="utf-8")})
        clean_files = _validate_package_files(package_files, source="persisted package_files")
    except Exception as exc:
        return {"id": "package_imports", "passed": False, "run_model_found": False, "run_checks_found": False, "error": str(exc)}
    run_model_found = False
    run_checks_found = False
    for item in clean_files:
        try:
            package_runtime._validate_generated_source(package_dir / item["path"])
            tree = ast.parse(item["content"], filename=item["path"])
        except Exception as exc:
            return {"id": "package_imports", "passed": False, "run_model_found": run_model_found, "run_checks_found": run_checks_found, "error": str(exc)}
        for node in ast.walk(tree):
            if item["path"] == "model/main.py" and isinstance(node, ast.FunctionDef) and node.name == "run_model":
                run_model_found = True
            if item["path"] == "model/checks.py" and isinstance(node, ast.FunctionDef) and node.name == "run_checks":
                run_checks_found = True
    return {"id": "package_imports", "passed": True, "run_model_found": run_model_found, "run_checks_found": run_checks_found}


def _editable_numeric_paths(schema: dict[str, Any], inputs: dict[str, Any]) -> set[str]:
    fields = schema.get("fields") if isinstance(schema, dict) else []
    if not isinstance(fields, list):
        return set()
    paths = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        raw_path = field.get("path")
        path = raw_path.strip() if isinstance(raw_path, str) else ""
        if not path or field.get("editable") is not True or field.get("read_only") is True:
            continue
        value = _get_path(inputs, path)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) or (
            field.get("type") in {"number_or_13_number_array", "number_or_number_array"}
            and isinstance(value, list)
            and len(value) == (13 if field.get("type") == "number_or_13_number_array" else field.get("period_count"))
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ):
            paths.add(path)
    return paths


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            paths.update(_scalar_paths(child, child_prefix))
        return paths
    return {prefix} if prefix and _is_scalar(value) else set()


def _normalize_data_path(path: str) -> str:
    return re.sub(r"\[(\d+)\]", r".\1", str(path).strip()).strip(".")


def _delete_path(root: dict[str, Any], path: str) -> bool:
    current: Any = root
    parts = _normalize_data_path(path).split(".")
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]
        return True
    if isinstance(current, list) and parts[-1].isdigit() and int(parts[-1]) < len(current):
        del current[int(parts[-1])]
        return True
    return False


def _input_contract_check(package_dir: Path) -> dict[str, Any]:
    base_path = package_dir / "inputs" / "base_case.json"
    schema_path = package_dir / "inputs" / "input_schema.json"
    if not base_path.exists() or not schema_path.exists():
        return {"id": "input_schema_contract_valid", "passed": True, "skipped": True}
    try:
        base_inputs = _read_json(base_path)
        schema = _read_json(schema_path)
        _validate_input_schema(schema, base_inputs, source="package input_schema")
        scalar_paths = sorted(_scalar_paths(base_inputs))
        editable_numeric = sorted(_editable_numeric_paths(schema, base_inputs))
        return {
            "id": "input_schema_contract_valid",
            "passed": True,
            "scalar_path_count": len(scalar_paths),
            "editable_numeric_paths": editable_numeric,
        }
    except Exception as exc:
        return {"id": "input_schema_contract_valid", "passed": False, "error": str(exc)}


def _missing_required_input_check(package_dir: Path, input_params: dict[str, Any]) -> dict[str, Any]:
    schema = _read_json(package_dir / "inputs" / "input_schema.json")
    fields = schema.get("fields") if isinstance(schema, dict) else []
    if not isinstance(fields, list):
        fields = []
    paths = sorted(
        str(field.get("path")).strip()
        for field in fields
        if isinstance(field, dict) and isinstance(field.get("path"), str) and str(field.get("path")).strip()
    )
    if not paths:
        return {"id": "missing_required_inputs_fail", "passed": False, "error": "No required input paths found."}
    fallback_paths: list[str] = []
    expected_errors: dict[str, str] = {}
    for path in paths:
        mutated = json.loads(json.dumps(input_params))
        if not _delete_path(mutated, path):
            continue
        try:
            package_runtime.execute_package(package_dir, mutated)
            fallback_paths.append(path)
        except Exception as exc:
            expected_errors[path] = str(exc)
    return {
        "id": "missing_required_inputs_fail",
        "passed": not fallback_paths and bool(expected_errors),
        "tested_paths": paths,
        "fallback_paths": fallback_paths,
        "expected_error_paths": sorted(expected_errors),
        "sample_errors": {path: expected_errors[path] for path in sorted(expected_errors)[:5]},
        "error": "Generated package silently ran with missing required inputs: " + ", ".join(fallback_paths) if fallback_paths else "",
    }


def _get_path(root: dict[str, Any], path: str) -> Any:
    current: Any = root
    for part in _normalize_data_path(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _path_exists(root: dict[str, Any], path: str) -> bool:
    current: Any = root
    for part in _normalize_data_path(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False
    return True


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    current: Any = root
    parts = _normalize_data_path(path).split(".")
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current.setdefault(part, {})
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return
    if isinstance(current, dict):
        current[parts[-1]] = value
    elif isinstance(current, list) and parts[-1].isdigit() and int(parts[-1]) < len(current):
        current[int(parts[-1])] = value


def _output_fingerprint(output: dict[str, Any]) -> str:
    return json.dumps(output, sort_keys=True, separators=(",", ":"), default=str)


def _extract_response_text(raw: dict[str, Any]) -> str:
    final_output = raw.get("_final_response_output")
    if isinstance(final_output, list):
        for item in final_output:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    return str(content["text"])
    for item in raw.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                return str(content["text"])
    if raw.get("output_text"):
        return str(raw["output_text"])
    raise RuntimeError("OpenAI response did not include output text.")


def _extract_code_interpreter_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in raw.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "code_interpreter_call":
            continue
        calls.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "code": item.get("code"),
                "outputs": item.get("outputs") or [],
            }
        )
    return calls


def _extract_function_calls(raw: dict[str, Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in raw.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "function_call":
            calls.append(
                {
                    "id": item.get("id"),
                    "call_id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": item.get("arguments") or "{}",
                    "status": item.get("status"),
                }
            )
    return calls


def _review_function_tool_definitions() -> list[dict[str, Any]]:
    string_schema = {"type": "string"}
    return [
        {
            "type": "function",
            "name": "list_package_artifacts",
            "description": "List the generated package artifact paths available for review.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "read_package_artifact",
            "description": "Read one bounded canonical saved package artifact for grounded review evidence.",
            "parameters": {"type": "object", "properties": {"artifact_path": string_schema}, "required": ["artifact_path"], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "validate_artifact_path",
            "description": "Check whether a relative package artifact path exists.",
            "parameters": {"type": "object", "properties": {"artifact_path": string_schema}, "required": ["artifact_path"], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "validate_input_path",
            "description": "Check whether an input path exists in base_case.json and input_schema.json.",
            "parameters": {"type": "object", "properties": {"input_path": string_schema}, "required": ["input_path"], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "validate_output_path",
            "description": "Check whether an output path exists in outputs/output.json.",
            "parameters": {"type": "object", "properties": {"output_path": string_schema}, "required": ["output_path"], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "execute_input_probe",
            "description": "Run the package after changing one input path and report the output movement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "issue_id": string_schema,
                    "input_path": string_schema,
                    "changed_value": {"type": ["number", "string", "boolean"]},
                    "output_path": string_schema,
                    "expected_behavior": {"type": "string", "enum": ["change", "increase", "decrease", "same", "not_null"]},
                },
                "required": ["issue_id", "input_path", "changed_value", "output_path", "expected_behavior"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "execute_model_test",
            "description": "Execute a declared model-local test for a scenario and return the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_id": string_schema,
                    "scenario_id": {"type": "string", "enum": ["base", "downside", "upside"]},
                },
                "required": ["test_id", "scenario_id"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


def _post_openai_with_function_tools(
    api_key: str,
    body: dict[str, Any],
    *,
    root: Path,
    stage: str,
    attempt: str = "",
    max_tool_rounds: int = 4,
) -> dict[str, Any]:
    conversation = list(body.get("input") or [])
    base_body = dict(body)
    all_records: list[dict[str, Any]] = []
    all_output_items: list[dict[str, Any]] = []
    combined_usage: dict[str, Any] = {}
    final_raw: dict[str, Any] | None = None
    needs_forced_finalization = False
    for round_index in range(max_tool_rounds + 1):
        request_body = {**base_body, "input": conversation}
        if round_index > 0 and request_body.get("tool_choice") == "required":
            request_body["tool_choice"] = "auto"
        raw = _post_openai(api_key, request_body)
        final_raw = raw
        all_output_items.extend(raw.get("output") or [])
        combined_usage = _combine_openai_usage(combined_usage, raw.get("usage") or {})
        fixture_records = raw.get("_function_tool_calls") if isinstance(raw.get("_function_tool_calls"), list) else []
        function_calls = _extract_function_calls(raw)
        if not function_calls:
            if fixture_records and not all_records:
                all_records.extend(fixture_records)
            break
        output_items: list[dict[str, Any]] = []
        for call in function_calls:
            record = _execute_review_function_call(root, call, stage=stage, attempt=attempt, round_index=round_index)
            all_records.append(record)
            output_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.get("call_id"),
                    "output": json.dumps(record.get("result") if record.get("ok") else {"ok": False, "error": record.get("error")}, separators=(",", ":"), default=str),
                }
            )
        conversation.extend(_response_output_input_items(raw.get("output") or []))
        conversation.extend(output_items)
        code_calls = _extract_code_interpreter_calls({"output": all_output_items})
        receipt_quality = _review_structural_evidence_quality(root, {}, code_calls, all_records)
        receipt_checks = receipt_quality.get("checks") or {}
        receipts_complete = all(
            receipt_checks.get(name) is True
            for name in (
                "code_interpreter_nontrivial",
                "artifact_listing_succeeded",
                "logic_or_spec_read_succeeded",
                "output_or_report_read_succeeded",
                "executable_probe_or_test_succeeded",
            )
        )
        if receipts_complete or round_index >= max_tool_rounds:
            needs_forced_finalization = True
            break
    if final_raw is None:
        raise RuntimeError("OpenAI function-tool call did not return a response.")
    if needs_forced_finalization:
        conversation.append(
            {
                "role": "user",
                "content": (
                    "Evidence collection is complete. Do not request or use another tool. "
                    "Return the final review verdict now in the required structured JSON schema, "
                    "grounded only in the package evidence and tool results already present in this conversation."
                ),
            }
        )
        finalization_body = {**base_body, "input": conversation, "tool_choice": "none"}
        forced_raw = _post_openai(api_key, finalization_body)
        final_raw = forced_raw
        all_output_items.extend(forced_raw.get("output") or [])
        combined_usage = _combine_openai_usage(combined_usage, forced_raw.get("usage") or {})
    if _extract_function_calls(final_raw):
        raise RuntimeError("OpenAI reviewer did not return final JSON after tool use was disabled.")
    final_raw["_final_response_output"] = list(final_raw.get("output") or [])
    final_raw["output"] = all_output_items
    if combined_usage:
        final_raw["usage"] = combined_usage
    if all_records:
        final_raw["_function_tool_calls"] = all_records
        _write_agent_tool_calls_report(root, stage=stage, attempt=attempt, records=all_records)
    return final_raw


def _response_output_input_items(output_items: list[Any]) -> list[dict[str, Any]]:
    """Carry response output into the next stateless Responses API turn.

    Reasoning models require their reasoning items to be returned alongside
    function-call outputs. The API also accepts prior response output items as
    subsequent input, so retain each structured item instead of reconstructing
    only function calls.
    """
    carry: list[dict[str, Any]] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        carry.append(json.loads(json.dumps(item)))
    return carry


def _function_call_input_items(output_items: list[Any]) -> list[dict[str, Any]]:
    """Backward-compatible alias for older focused tests and fixtures."""
    return _response_output_input_items(output_items)


def _combine_openai_usage(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return dict(right)
    combined = dict(left)
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        combined[key] = int(combined.get(key) or 0) + int(right.get(key) or 0)
    for nested_key in ("input_tokens_details", "output_tokens_details"):
        if isinstance(right.get(nested_key), dict):
            combined_nested = dict(combined.get(nested_key) or {})
            for key, value in right[nested_key].items():
                if isinstance(value, int):
                    combined_nested[key] = int(combined_nested.get(key) or 0) + value
            combined[nested_key] = combined_nested
    if isinstance(right.get("_transport"), dict):
        transports = list(combined.get("_transports") or [])
        # Only seed the list from the first response's transport.  Once
        # ``_transports`` exists, ``_transport`` is already the cumulative
        # summary and adding it again would double-count every prior turn.
        if not transports and isinstance(combined.get("_transport"), dict):
            transports.append(combined["_transport"])
        transports.append(right["_transport"])
        combined["_transports"] = transports
        combined["_transport"] = {
            "started_utc": transports[0].get("started_utc"),
            "completed_utc": transports[-1].get("completed_utc"),
            "duration_seconds": round(sum(float(item.get("duration_seconds") or 0.0) for item in transports), 3),
            "timeout_seconds": transports[-1].get("timeout_seconds"),
            "attempt_count": sum(int(item.get("attempt_count") or 0) for item in transports),
            "max_attempts": transports[-1].get("max_attempts"),
            "retry_count": sum(int(item.get("retry_count") or 0) for item in transports),
            "max_retries": transports[-1].get("max_retries"),
        }
    return combined


def _next_review_retry_attempt(root: Path, base_attempt: str) -> str:
    retry = 1
    while any(
        path.exists()
        for path in (
            root / f"raw_review_response_{base_attempt}_retry_{retry}.json",
            root / f"review_execution_evidence_{base_attempt}_retry_{retry}.json",
            root / f"agent_tool_calls_report_{base_attempt}_retry_{retry}.json",
        )
    ):
        retry += 1
    return f"{base_attempt}_retry_{retry}"


def _execute_review_function_call(root: Path, call: dict[str, Any], *, stage: str, attempt: str, round_index: int) -> dict[str, Any]:
    call_id = str(call.get("call_id") or "")
    name = str(call.get("name") or "")
    started = time.perf_counter()
    try:
        args = json.loads(str(call.get("arguments") or "{}"))
        if not isinstance(args, dict):
            raise RuntimeError("Function arguments must decode to an object.")
        result = _run_review_tool(root, name, args)
        ok = True
        error_text = ""
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        ok = False
        error_text = str(exc)
    record = {
        "created_utc": _utc_now(),
        "stage": stage,
        "attempt": attempt,
        "round_index": round_index,
        "call_id": call_id,
        "tool_name": name,
        "arguments": args if "args" in locals() else {},
        "ok": ok,
        "result": result,
        "duration_seconds": round(time.perf_counter() - started, 3),
    }
    if error_text:
        record["error"] = error_text
    model_trace.append_event(
        root,
        "agent_function_tool_call",
        actor="review_agent",
        recipient="backend_tool",
        stage=stage,
        attempt=attempt,
        status="completed" if ok else "error",
        payload=record,
        error=error_text,
    )
    return record


def _run_review_tool(root: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    package_dir = root / "model_package"
    if name == "list_package_artifacts":
        _validate_tool_args(args, allowed=set(), required=set())
        return {"ok": True, "artifacts": [item["path"] for item in _artifact_tree(root)]}
    if name == "read_package_artifact":
        _validate_tool_args(args, allowed={"artifact_path"}, required={"artifact_path"})
        return _read_review_artifact(root, str(args["artifact_path"]))
    if name == "validate_artifact_path":
        _validate_tool_args(args, allowed={"artifact_path"}, required={"artifact_path"})
        artifact_path = str(args["artifact_path"])
        return {"ok": True, "artifact_path": artifact_path, "exists": _artifact_relative_exists(root, artifact_path)}
    if name == "validate_input_path":
        _validate_tool_args(args, allowed={"input_path"}, required={"input_path"})
        base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
        schema = _read_json(package_dir / "inputs" / "input_schema.json")
        input_path = str(args["input_path"])
        field = _input_schema_field(schema, input_path)
        return {
            "ok": True,
            "input_path": input_path,
            "in_base_case": _path_exists(base_inputs, input_path),
            "in_input_schema": bool(field),
            "editable": field.get("editable") if field else None,
            "type": field.get("type") if field else None,
            "value": _get_path(base_inputs, input_path),
        }
    if name == "validate_output_path":
        _validate_tool_args(args, allowed={"output_path"}, required={"output_path"})
        output = _read_json(package_dir / "outputs" / "output.json")
        output_path = str(args["output_path"])
        exists, value = _get_output_path_value(output, output_path)
        return {"ok": True, "output_path": output_path, "exists": exists, "value": value}
    if name == "execute_input_probe":
        _validate_tool_args(args, allowed={"issue_id", "input_path", "changed_value", "output_path", "expected_behavior"}, required={"issue_id", "input_path", "changed_value", "output_path", "expected_behavior"})
        input_schema = _read_json(package_dir / "inputs" / "input_schema.json")
        base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
        latest_output = _read_json(package_dir / "outputs" / "output.json")
        schema_paths = {str(field.get("path")).strip() for field in (input_schema.get("fields") or []) if isinstance(field, dict) and isinstance(field.get("path"), str)}
        probe = {
            "input_path": args["input_path"],
            "changed_value": args["changed_value"],
            "output_path": args["output_path"],
            "expected_behavior": args["expected_behavior"],
        }
        return {"ok": True, **_execute_repair_input_probe(package_dir, base_inputs, schema_paths, latest_output, probe, str(args["issue_id"]))}
    if name == "execute_model_test":
        _validate_tool_args(args, allowed={"test_id", "scenario_id"}, required={"test_id", "scenario_id"})
        return {"ok": True, **_execute_single_model_test(package_dir, str(args["test_id"]), str(args["scenario_id"]))}
    raise RuntimeError(f"Unknown function tool: {name}")


def _read_review_artifact(root: Path, artifact_path: str) -> dict[str, Any]:
    normalized = artifact_path.strip().replace("\\", "/")
    if not normalized or Path(normalized).is_absolute():
        raise RuntimeError("artifact_path must be a canonical relative path.")
    target = (root / normalized).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError("artifact_path escapes the package version root.") from exc
    canonical_paths = {str(item.get("path") or "") for item in _artifact_tree(root)}
    if normalized not in canonical_paths or not target.is_file():
        raise RuntimeError("artifact_path is not a canonical saved package artifact.")
    size = target.stat().st_size
    if size > REVIEW_ARTIFACT_READ_MAX_BYTES:
        raise RuntimeError(f"artifact exceeds the {REVIEW_ARTIFACT_READ_MAX_BYTES}-byte review limit.")
    raw = target.read_bytes()
    if b"\x00" in raw:
        raise RuntimeError("binary artifacts cannot be read by the Review Agent.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RuntimeError("artifact is not valid UTF-8 text.") from exc
    content: Any = json.loads(text) if target.suffix.lower() == ".json" else text
    return {
        "ok": True,
        "artifact_path": normalized,
        "size_bytes": size,
        "kind": target.suffix.lower().lstrip(".") or "text",
        "content": content,
    }


def _validate_tool_args(args: dict[str, Any], *, allowed: set[str], required: set[str]) -> None:
    extra = sorted(set(args) - allowed)
    missing = sorted(required - set(args))
    if extra or missing:
        parts = []
        if extra:
            parts.append("unexpected args: " + ", ".join(extra))
        if missing:
            parts.append("missing args: " + ", ".join(missing))
        raise RuntimeError("; ".join(parts))


def _input_schema_field(schema: dict[str, Any], path: str) -> dict[str, Any]:
    for field in schema.get("fields") or []:
        if isinstance(field, dict) and field.get("path") == path:
            return field
    return {}


def _execute_single_model_test(package_dir: Path, test_id: str, scenario_id: str) -> dict[str, Any]:
    base_inputs = _read_json(package_dir / "inputs" / "base_case.json")
    scenarios = _read_scenario_cases_file(package_dir / "inputs" / "scenarios.json")
    declared = {item["id"]: item for item in _declared_model_tests(package_dir)}
    selected_test = declared.get(test_id)
    if not selected_test:
        raise RuntimeError(f"Unknown declared model test: {test_id}")
    if selected_test.get("execution_scope") == "scenario_suite":
        cases: dict[str, dict[str, Any]] = {}
        for case in scenarios:
            case_inputs = json.loads(json.dumps(base_inputs))
            if case["id"] != "base":
                for path, value in (case.get("input_overrides") or {}).items():
                    _set_path(case_inputs, str(path), value)
            cases[case["id"]] = {
                "inputs": case_inputs,
                "output": package_runtime.execute_package(package_dir, case_inputs),
            }
        raw_report = package_runtime.execute_package_suite_checks(package_dir, cases)
        for check in raw_report.get("checks") or []:
            if isinstance(check, dict) and check.get("id") == test_id:
                return {"test_id": test_id, "scenario_id": "scenario_suite", "check": check}
        raise RuntimeError(f"Declared scenario-suite test was not returned by checks.py: {test_id}")
    scenario = {case["id"]: case for case in scenarios}.get(scenario_id)
    if not scenario:
        raise RuntimeError(f"Unknown scenario_id: {scenario_id}")
    inputs = json.loads(json.dumps(base_inputs))
    for path, value in (scenario.get("input_overrides") or {}).items():
        _set_path(inputs, str(path), value)
    output = package_runtime.execute_package(package_dir, inputs)
    raw_report = package_runtime.execute_package_checks(package_dir, inputs, output)
    for check in raw_report.get("checks") or []:
        if isinstance(check, dict) and check.get("id") == test_id:
            return {"test_id": test_id, "scenario_id": scenario_id, "check": check}
    raise RuntimeError(f"Declared model test was not returned by checks.py: {test_id}")


def _write_agent_tool_calls_report(root: Path, *, stage: str, attempt: str, records: list[dict[str, Any]]) -> None:
    report = {
        "created_utc": _utc_now(),
        "stage": stage,
        "attempt": attempt,
        "tool_call_count": len(records),
        "failed_tool_call_count": sum(1 for record in records if record.get("ok") is not True),
        "tool_calls": records,
    }
    filename = "agent_tool_calls_report.json" if stage == "review_agent_audit" else f"{stage}_tool_calls_report.json"
    path = root / "model_package" / "reports" / filename
    _write_json(path, report)
    if stage == "review_agent_audit":
        _write_json(root / f"agent_tool_calls_report_{attempt}.json", report)
    model_trace.append_event(
        root,
        "agent_function_tool_calls_report",
        actor="backend",
        recipient="trace",
        stage=stage,
        attempt=attempt,
        status="captured",
        payload=report,
        artifacts={"agent_tool_calls_report": f"model_package/reports/{filename}"},
    )


def _review_structural_evidence_quality(
    root: Path,
    report: dict[str, Any],
    code_calls: list[dict[str, Any]],
    function_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    code_character_count = sum(len(str(call.get("code") or "")) for call in code_calls)
    output_count = sum(len(call.get("outputs") or []) for call in code_calls)
    code_execution_passed = bool(code_calls and code_character_count >= 80 and output_count > 0)
    successful = [call for call in function_calls if call.get("ok") is True]
    tools_used = sorted({str(call.get("tool_name") or "") for call in successful if call.get("tool_name")})
    reads = [
        str((call.get("result") or {}).get("artifact_path") or (call.get("arguments") or {}).get("artifact_path") or "")
        for call in successful
        if call.get("tool_name") == "read_package_artifact"
    ]
    logic_reads = sorted(
        path for path in reads
        if path.startswith("model_package/model/")
        or path.startswith("model_package/spec/")
        or path in {"model_spec.json", "model_thesis.json", "equation_graph.json", "model_tests.json"}
    )
    result_reads = sorted(
        path for path in reads
        if path.startswith("model_package/outputs/") or path.startswith("model_package/reports/")
    )
    execution_tools = sorted(
        str(call.get("tool_name") or "")
        for call in successful
        if call.get("tool_name") in {"execute_input_probe", "execute_model_test"}
    )
    finding_citations = {
        str(path).strip()
        for finding in report.get("findings") or []
        for path in (
            list((finding.get("evidence") or {}).get("artifacts") or [])
            + ([str((finding.get("evidence") or {}).get("artifact") or "")] if (finding.get("evidence") or {}).get("artifact") else [])
        )
    }
    cited_paths = sorted(
        finding_citations
        | {
            str(path).strip()
            for amendment in report.get("required_amendments") or []
            for path in amendment.get("artifacts") or []
        }
        - {""}
    )
    unresolved_citations = [path for path in cited_paths if not _artifact_relative_exists(root, path)]
    checks = {
        "code_interpreter_nontrivial": code_execution_passed,
        "artifact_listing_succeeded": "list_package_artifacts" in tools_used,
        "logic_or_spec_read_succeeded": bool(logic_reads),
        "output_or_report_read_succeeded": bool(result_reads),
        "executable_probe_or_test_succeeded": bool(execution_tools),
        "all_citations_resolved": not unresolved_citations,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "passed": not failed,
        "message": "Structural review evidence is complete." if not failed else "Missing structural review evidence: " + ", ".join(failed),
        "checks": checks,
        "tools_used": tools_used,
        "logic_or_spec_reads": logic_reads,
        "output_or_report_reads": result_reads,
        "execution_tools": execution_tools,
        "cited_artifacts": cited_paths,
        "unresolved_citations": unresolved_citations,
        "code_character_count": code_character_count,
        "output_count": output_count,
    }


def _normalize_review_artifact_aliases(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Resolve reviewer shorthand only when an authoritative canonical file exists."""
    canonical_spec_names = {"model_spec.json", "model_thesis.json", "equation_graph.json", "model_tests.json"}

    def canonicalize(path: str) -> str:
        clean = str(path or "").strip().replace("\\", "/")
        if _artifact_relative_exists(root, clean):
            return clean
        prefix = "model_package/"
        if clean.startswith(prefix) and clean.count("/") == 1:
            basename = clean[len(prefix):]
            candidate = f"model_package/spec/{basename}"
            if basename in canonical_spec_names and _artifact_relative_exists(root, candidate):
                return candidate
        return clean

    normalized = dict(report)
    findings: list[dict[str, Any]] = []
    for finding in report.get("findings") or []:
        updated = dict(finding)
        evidence = dict(updated.get("evidence") or {})
        artifacts = [canonicalize(path) for path in evidence.get("artifacts") or []]
        if evidence.get("artifact"):
            evidence["artifact"] = canonicalize(str(evidence["artifact"]))
        if artifacts:
            evidence["artifacts"] = list(dict.fromkeys(artifacts))
            evidence["artifact"] = evidence.get("artifact") or evidence["artifacts"][0]
        updated["evidence"] = evidence
        findings.append(updated)
    normalized["findings"] = findings

    amendments: list[dict[str, Any]] = []
    for amendment in report.get("required_amendments") or []:
        updated = dict(amendment)
        updated["artifacts"] = list(dict.fromkeys(canonicalize(path) for path in amendment.get("artifacts") or []))
        amendments.append(updated)
    normalized["required_amendments"] = amendments
    return normalized


def _openai_response_timeout_seconds() -> int:
    return model_config.ai_runtime_int("openai_response_timeout_seconds", 900)


def _openai_transport_max_retries() -> int:
    return model_config.ai_runtime_int("openai_transport_max_retries", 1)


def _openai_transport_retry_delay_seconds() -> int:
    return model_config.ai_runtime_int("openai_transport_retry_delay_seconds", 5)


def _is_retryable_openai_transport_error(exc: Exception) -> bool:
    if isinstance(exc, error.HTTPError):
        if exc.code == 429 and "insufficient_quota" in _http_error_detail(exc).lower():
            return False
        return exc.code in {408, 429, 500, 502, 503, 504, 520, 522, 524}
    if isinstance(exc, (TimeoutError, socket.timeout, http.client.IncompleteRead)):
        return True
    if isinstance(exc, error.URLError):
        reason = exc.reason
        return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower()
    return False


def _openai_error_message(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        detail = _http_error_detail(exc)
        return f"OpenAI request failed with HTTP {exc.code}: {detail}"
    if isinstance(exc, error.URLError):
        return f"OpenAI transport failed: {exc.reason}"
    return f"OpenAI transport failed: {type(exc).__name__}: {exc}"


def _http_error_detail(exc: error.HTTPError) -> str:
    cached = getattr(exc, "_model_factory_detail", None)
    if isinstance(cached, str):
        return cached
    detail = exc.read().decode("utf-8", errors="replace")
    setattr(exc, "_model_factory_detail", detail)
    return detail


def _budget_output_token_reservation(body: dict[str, Any]) -> int:
    configured = body.get("max_output_tokens")
    if isinstance(configured, int) and configured > 0:
        return configured
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    stage = str(metadata.get("stage") or "")
    if stage in {"modeler_package_build", "modeler_package_self_check", "modeler_package_preflight_repair", "modeler_package_backend_repair", "modeler_package_repair", "modeler_package_amendment", "presentation_agent_assembly", "presentation_agent_repair"}:
        return 64_000
    if stage in {"modeler_model_theory", "review_agent_audit"}:
        return 32_000
    if stage == "modeler_model_spec":
        return 16_000
    return 16_000


def _decision_gate_budget_limit() -> float | None:
    raw = os.environ.get("MODEL_FACTORY_DECISION_GATE_BUDGET_USD", "").strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _append_budget_call_record(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _record_budget_call(body: dict[str, Any], payload: dict[str, Any], decision: dict[str, Any]) -> None:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    model = str(body.get("model") or "")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    transport = usage.get("_transport") if isinstance(usage.get("_transport"), dict) else {}
    usage_for_summary = {key: value for key, value in usage.items() if key != "_transport"}
    summary = openai_usage.summarize_token_usage(usage_for_summary)
    record = {
        "created_utc": _utc_now(),
        "build_run_id": f"{metadata.get('version_id') or metadata.get('model_id') or 'conversation'}_{metadata.get('stage') or 'openai_call'}_{uuid.uuid4().hex[:8]}",
        "stage": metadata.get("stage") or "openai_call",
        "model": model,
        "usage_summary": summary,
        "cost_summary": openai_usage.estimate_cost(model, summary),
        "pre_call_budget_decision": decision,
        "duration_seconds": transport.get("duration_seconds"),
        "attempt_count": transport.get("attempt_count"),
        "retry_count": transport.get("retry_count"),
        "started_utc": transport.get("started_utc"),
        "completed_utc": transport.get("completed_utc"),
    }
    local_ledger = budget_call_ledger_path()
    suite_ledger = budget_suite_ledger_path()
    _append_budget_call_record(local_ledger, record)
    if suite_ledger is not None and suite_ledger != local_ledger:
        _append_budget_call_record(suite_ledger, record)


def _post_openai(api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    raw_body = json.dumps(body)
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    run_id = str(metadata.get("version_id") or metadata.get("model_id") or "conversation")
    budget_decision = openai_budget.pre_call_budget_decision(
        model=str(body.get("model") or model_config.DEFAULT_MODEL),
        body_json=raw_body,
        output_tokens=_budget_output_token_reservation(body),
        usage_ledger_path=budget_call_ledger_path(),
        run_id=run_id,
        suite_ledger_path=budget_suite_ledger_path(),
        suite_limit_usd=_decision_gate_budget_limit(),
    )
    if budget_decision.get("allowed") is not True:
        raise RuntimeError("OpenAI budget blocked: " + json.dumps(budget_decision, sort_keys=True))
    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=raw_body.encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    timeout = _openai_response_timeout_seconds()
    max_retries = _openai_transport_max_retries()
    retry_delay = _openai_transport_retry_delay_seconds()
    attempts = max_retries + 1
    started_at = time.perf_counter()
    started_utc = _utc_now()
    for attempt_index in range(attempts):
        try:
            with request.urlopen(req, timeout=timeout) as response:
                response_body = response.read().decode("utf-8")
        except Exception as exc:
            retryable = _is_retryable_openai_transport_error(exc)
            if not retryable or attempt_index >= max_retries:
                message = _openai_error_message(exc)
                if retryable:
                    message = f"{message} after {attempt_index + 1} attempt(s)"
                raise RuntimeError(message) from exc
            if retry_delay > 0:
                time.sleep(retry_delay)
            continue
        completed_utc = _utc_now()
        duration_seconds = round(time.perf_counter() - started_at, 3)
        payload = json.loads(response_body)
        if isinstance(payload, dict):
            usage_payload = payload.get("usage")
            if not isinstance(usage_payload, dict):
                usage_payload = {}
                payload["usage"] = usage_payload
            usage_payload["_transport"] = {
                "started_utc": started_utc,
                "completed_utc": completed_utc,
                "duration_seconds": duration_seconds,
                "timeout_seconds": timeout,
                "attempt_count": attempt_index + 1,
                "max_attempts": attempts,
                "retry_count": attempt_index,
                "max_retries": max_retries,
            }
            usage_payload["_budget"] = budget_decision
            _record_budget_call(body, payload, budget_decision)
        return payload
    raise RuntimeError("OpenAI transport failed without a response.")


def _record_usage(root: Path, model: str, usage: dict[str, Any], *, stage: str, code_interpreter_call_count: int = 0) -> dict[str, Any]:
    transport = usage.get("_transport") if isinstance(usage, dict) and isinstance(usage.get("_transport"), dict) else {}
    usage_for_summary = {key: value for key, value in (usage or {}).items() if key != "_transport"}
    summary = openai_usage.summarize_token_usage(usage_for_summary)
    cost = openai_usage.estimate_cost(model, summary)
    report = {
        "created_utc": _utc_now(),
        "started_utc": transport.get("started_utc"),
        "completed_utc": transport.get("completed_utc"),
        "duration_seconds": transport.get("duration_seconds"),
        "timeout_seconds": transport.get("timeout_seconds"),
        "attempt_count": transport.get("attempt_count"),
        "max_attempts": transport.get("max_attempts"),
        "retry_count": transport.get("retry_count"),
        "max_retries": transport.get("max_retries"),
        "build_run_id": f"{root.name}_{stage}",
        "status": "completed",
        "stage": stage,
        "model": model,
        "endpoint": "responses",
        "usage": usage_for_summary,
        "usage_summary": summary,
        "cost_summary": cost,
        "code_interpreter_call_count": code_interpreter_call_count,
        "artifact_dir": _display_path(root),
        "ledger_path": _display_path(usage_ledger_path()),
        "openai_called": True,
    }
    _write_json(root / f"usage_{stage}.json", report)
    if stage == "modeler_package_build":
        _write_json(root / "usage_report.json", report)
    ledger = usage_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
    return report


def _classify_generation_failure(exc: Exception, *, default: str) -> str:
    message = str(exc).lower()
    if "insufficient_quota" in message or "exceeded your current quota" in message:
        return "quota_blocked"
    if "budget" in message:
        return "budget_blocked"
    if "openai transport failed" in message or "openai request failed" in message or "http " in message or "urlopen" in message or "timed out" in message or "incompleteread" in message or "incomplete read" in message:
        return "openai_transport_failed"
    parser_markers = (
        "did not return",
        "must be",
        "missing required",
        "response did not include output text",
        "self-check did not pass",
        "invalid",
        "json",
    )
    if any(marker in message for marker in parser_markers):
        return "parser_failed"
    return default


def _classify_generation_failure_subcode(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "insufficient_quota" in message or "exceeded your current quota" in message:
        return "insufficient_quota"
    if "budget" in message:
        return "budget_blocked"
    if "timeout" in name or "timed out" in message:
        return "openai_timeout"
    if "incompleteread" in name or "incompleteread" in message or "incomplete read" in message:
        return "openai_incomplete_read"
    if "openai request failed with http" in message or "http " in message:
        return "openai_http_error"
    if "urlopen" in message:
        return "openai_urlopen_error"
    return ""


def _backend_failure_reasons(validation: dict[str, Any], stress_report: dict[str, Any], model_tests_report: dict[str, Any] | None = None) -> list[str]:
    reasons: list[str] = []
    if validation.get("passed") is not True:
        for check in validation.get("checks") or []:
            if isinstance(check, dict) and check.get("passed") is not True:
                reason = str(check.get("id") or "backend_validation")
                error_text = str(check.get("error") or "")
                if error_text:
                    reason = f"{reason}: {error_text}"
                reasons.append(reason)
        if validation.get("execution_error"):
            reasons.append("execution_error: " + str(validation["execution_error"]))
    if stress_report.get("passed") is not True:
        for check in stress_report.get("checks") or []:
            if isinstance(check, dict) and check.get("passed") is not True:
                reasons.append(str(check.get("id") or "backend_mechanical_stress"))
    if model_tests_report and model_tests_report.get("passed") is not True:
        for check in model_tests_report.get("checks") or []:
            if isinstance(check, dict) and check.get("passed") is not True:
                check_id = str(check.get("id") or "backend_model_tests")
                error_text = str(check.get("error") or "").strip()
                if error_text:
                    reasons.append(f"{check_id}: {error_text}")
                execution_errors = check.get("execution_errors") or []
                if isinstance(execution_errors, list) and execution_errors:
                    for execution_error in execution_errors[:3]:
                        if not isinstance(execution_error, dict):
                            continue
                        case_id = str(execution_error.get("case_id") or "case")
                        detail = str(execution_error.get("error") or "").strip()
                        if detail:
                            reasons.append(f"{check_id} [{case_id}]: {detail}")
                if not error_text and not execution_errors:
                    reasons.append(check_id)
    return reasons or ["Backend package checks failed."]


def _write_failure_report(
    root: Path,
    *,
    code: str,
    stage: str,
    message: str,
    reasons: list[str] | None = None,
    status: str | None = None,
    next_actions: list[str] | None = None,
    artifacts: dict[str, str] | None = None,
    failure_subcode: str = "",
) -> dict[str, Any]:
    clean_reasons = [str(item).strip() for item in reasons or [] if str(item).strip()] or [message]
    actions = [str(item).strip() for item in next_actions or FAILURE_NEXT_ACTIONS.get(code, ["review_failure_report"]) if str(item).strip()]
    report = {
        "created_utc": _utc_now(),
        "failure_code": code,
        "failure_subcode": failure_subcode,
        "failure_stage": stage,
        "message": message,
        "failure_reasons": clean_reasons,
        "next_actions": actions,
        "artifacts": artifacts or {},
        "recoverable": code not in {"budget_blocked"},
    }
    _write_json(root / "failure_report.json", report)
    state = _read_json(root / "version_manifest.json")
    if status:
        state["status"] = status
    state["updated_utc"] = _utc_now()
    state["failure_report"] = "failure_report.json"
    state["failure_code"] = code
    state["failure_subcode"] = failure_subcode
    state["failure_stage"] = stage
    state["failure_reasons"] = clean_reasons
    state["next_actions"] = actions
    state["latest_run_status"] = code
    _write_json(root / "version_manifest.json", state)
    model_trace.append_event(
        root,
        "backend_failure_report",
        actor="backend",
        recipient="trace",
        stage=stage,
        status="failed",
        payload=report,
        artifacts={"failure_report": "failure_report.json", **(artifacts or {})},
        error=message,
    )
    return state


def _update_version_manifest(
    root: Path,
    status: str,
    *,
    usage_report: dict[str, Any] | None = None,
    latest_output: dict[str, Any] | None = None,
    latest_run_status: str | None = None,
) -> dict[str, Any]:
    state = _read_json(root / "version_manifest.json")
    state["status"] = status
    state["updated_utc"] = _utc_now()
    state.pop("latest_output", None)
    state.pop("artifacts", None)
    if latest_run_status is not None:
        state["latest_run_status"] = latest_run_status
    if usage_report:
        calls = list(state.get("openai_calls") or [])
        staged_reports = usage_report.get("staged_reports") if isinstance(usage_report.get("staged_reports"), list) else None
        if staged_reports:
            calls.extend(staged_reports)
        else:
            calls.append(usage_report)
        state["openai_calls"] = calls
    _write_json(root / "version_manifest.json", state)
    return state


def _artifact_tree(root: Path, *, force: bool = False) -> list[dict[str, Any]]:
    del force
    rows = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if path.is_file():
                relative = str(path.relative_to(root)).replace("\\", "/")
                if "__pycache__" in relative:
                    continue
                rows.append({"path": relative, "size": path.stat().st_size})
    return rows


def _stages(status: str) -> list[dict[str, str]]:
    stages = [
        ("prompt", "Scope"),
        ("spec", "Model spec"),
        ("theory", "Model theory"),
        ("openai", "Generate package"),
        ("package", "Write package"),
        ("checks", "Technical checks"),
        ("review", "Review"),
        ("publish", "Publish"),
    ]
    done_count = (
        1
        if status == "spec_draft"
        else 2
        if status == "spec_approved"
        else 6
        if status == "review_ready"
        else 7
        if status == "published"
        else 5
        if status == "review_failed"
        else 1
    )
    return [
        {"id": stage_id, "label": label, "state": "done" if index < done_count else "active" if index == done_count else "pending"}
        for index, (stage_id, label) in enumerate(stages)
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _jsonl_record_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _stable_fingerprint(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    return str(resolved.relative_to(ROOT_DIR)).replace("\\", "/") if resolved.is_relative_to(ROOT_DIR) else str(resolved).replace("\\", "/")
