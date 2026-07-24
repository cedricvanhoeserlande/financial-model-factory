from __future__ import annotations

from backend.app.model_context import *

def default_input_params() -> dict[str, Any]:
    return {"horizon_years": []}

def build_input_review_summary(input_params: dict[str, Any]) -> dict[str, Any]:
    return _build_input_review_summary(input_params, default_input_params(), now=_utc_now)

def assumption_label(key: str) -> str:
    return key.replace("_", " ").replace(".", " ").title()

def _build_input_review_summary(input_params: dict[str, Any], baseline: dict[str, Any], *, now: Callable[[], str]) -> dict[str, Any]:
    rows = []
    for path, value in _flatten_input_params(input_params):
        baseline_value = _get_input_path(baseline, path)
        source = "editable_default" if value == baseline_value else "user_edit"
        rows.append({"key": path, "path": path, "label": assumption_label(path), "value": value, "source": source, "provenance": source})

    missing_inputs = []
    for path, _value in _flatten_input_params(baseline):
        if _get_input_path(input_params, path) is None:
            missing_inputs.append({"key": path, "path": path, "label": assumption_label(path), "required": True})

    return {
        "created_utc": now(),
        "extracted_assumptions": rows,
        "canonical_inputs": rows,
        "missing_inputs": missing_inputs,
        "ambiguous_items": [],
        "inferred_defaults": [],
        "summary": {
            "extracted_count": len(rows),
            "canonical_count": len(rows),
            "missing_count": len(missing_inputs),
            "ambiguous_count": 0,
            "inferred_default_count": 0,
        },
    }

def _flatten_input_params(root: dict[str, Any]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(f"{prefix}.{key}" if prefix else str(key), child)
            return
        rows.append((prefix, value))

    for key, value in root.items():
        visit(str(key), value)
    return rows

def _get_input_path(root: dict[str, Any], path: str) -> Any:
    current: Any = root
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current

def classify_change(
    *,
    prompt: str = "",
    input_params: dict[str, Any] | None = None,
    baseline_params: dict[str, Any] | None = None,
    explicit_intent: str | None = None,
) -> dict[str, Any]:
    if explicit_intent in {"input_only", "logic_structure"}:
        return {
            "type": explicit_intent,
            "source": "explicit_user_action",
            "reason": "The UI action explicitly selected this change path.",
        }

    lowered_prompt = prompt.lower()
    matched_keywords = [keyword for keyword in sorted(LOGIC_CHANGE_KEYWORDS) if keyword in lowered_prompt]
    if matched_keywords:
        return {
            "type": "logic_structure",
            "source": "prompt_classifier",
            "reason": f"Prompt contains logic/structure keywords: {', '.join(matched_keywords)}.",
        }

    changed_inputs = changed_input_keys(input_params or {}, baseline_params or {})
    return {
        "type": "input_only",
        "source": "deterministic_input_diff",
        "reason": "Only canonical input values changed; existing generated Python can be rerun.",
        "changed_inputs": changed_inputs,
    }

def changed_input_keys(input_params: dict[str, Any], baseline_params: dict[str, Any]) -> list[str]:
    changed = []
    for key, value in input_params.items():
        if key not in baseline_params:
            changed.append(key)
        elif value != baseline_params[key]:
            changed.append(key)
    for key in baseline_params:
        if key not in input_params:
            changed.append(key)
    return sorted(changed)

def build_workflow_state(
    *,
    current_stage: str,
    input_review_summary: dict[str, Any],
    change_classification: dict[str, Any],
    run_type: str,
    draft_status: str,
    validation: dict[str, Any] | None = None,
    stress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_index = next(
        (index for index, stage in enumerate(WORKFLOW_STAGES) if stage["id"] == current_stage),
        0,
    )
    stages = []
    for index, stage in enumerate(WORKFLOW_STAGES):
        if index < current_index:
            status = "complete"
        elif index == current_index:
            status = "current"
        else:
            status = "pending"
        stages.append({**stage, "status": status})

    missing_count = input_review_summary["summary"]["missing_count"]
    ambiguous_count = input_review_summary["summary"]["ambiguous_count"]
    validation_passed = bool(validation and validation.get("passed"))
    stress_passed = bool(stress and stress.get("passed"))
    if current_stage == "define":
        next_required = "Describe the model scope or use the seeded case."
    elif missing_count or ambiguous_count:
        next_required = "Resolve missing or ambiguous inputs before treating the draft as ready."
    elif current_stage == "review_plan":
        next_required = "Review the plan, then run a draft or rebuild if model logic changes."
    elif current_stage == "build_run_draft":
        next_required = "Run the package checks."
    elif validation_passed and stress_passed:
        next_required = "Validated draft is ready for refinement."
    else:
        next_required = "Inspect failed checks and refine inputs or rebuild logic."

    return {
        "version": "2026.05",
        "created_utc": _utc_now(),
        "current_stage": current_stage,
        "stages": stages,
        "next_required": next_required,
        "unresolved": {
            "missing_count": missing_count,
            "ambiguous_count": ambiguous_count,
        },
        "change_classification": change_classification,
        "run_type": run_type,
        "draft_status": draft_status,
        "validation_passed": validation_passed,
        "stress_passed": stress_passed,
    }

def _workspace_action_state(
    selected_model: dict[str, Any] | None,
    latest_build: dict[str, Any] | None,
    latest_run: dict[str, Any] | None,
) -> dict[str, Any]:
    if not selected_model:
        return {
            "can_rebuild": False,
            "rebuild_reason": "Create or open a model first.",
            "can_rerun": False,
            "rerun_reason": "Build model logic before rerunning inputs.",
            "can_reload_latest": False,
            "reload_latest_reason": "No output has been generated for this model.",
            "can_publish": False,
            "publish_reason": "Create or open a model first.",
            "can_open_regular": False,
            "open_regular_reason": "Publish the model before regular mode.",
        }

    publish_eligible = bool(selected_model.get("publish_eligible"))
    return {
        "can_rebuild": True,
        "rebuild_reason": "",
        "can_rerun": bool(latest_build) or bool(selected_model.get("canonical_version_id")),
        "rerun_reason": "" if (latest_build or selected_model.get("canonical_version_id")) else "Build model logic before rerunning inputs.",
        "can_reload_latest": bool(latest_run),
        "reload_latest_reason": "" if latest_run else "No output has been generated for this model.",
        "can_publish": publish_eligible,
        "publish_reason": "" if publish_eligible else selected_model.get("publish_blocker", "Build, run, and validate before publishing."),
        "can_open_regular": selected_model.get("status") == "published",
        "open_regular_reason": ""
        if selected_model.get("status") == "published"
        else "Publish the model before regular mode.",
    }

def build_workspace_payload(model_id: str | None = None) -> dict[str, Any]:
    from backend.app.model_conversations import (
        _initial_conversation,
        _initial_review_conversation,
        read_input_agent_conversation,
        read_review_agent_conversation,
    )
    from backend.app.model_runs import read_build, read_run
    from backend.app.model_usage import openai_status_payload

    selected_model = model_registry.read_model(model_id) if model_id else None
    if model_id and not selected_model:
        raise RuntimeError(f"Model not found: {model_id}")
    if not selected_model:
        models = model_registry.list_models()
        selected_model = models[0] if models else None
        model_id = str(selected_model["model_id"]) if selected_model else None

    latest_build = (
        read_build(str(selected_model["current_build_id"]))
        if selected_model and selected_model.get("current_build_id")
        else None
    )
    latest_run = (
        read_run(str(selected_model["latest_run_id"]))
        if selected_model and selected_model.get("latest_run_id")
        else None
    )
    input_params = (
        latest_run.get("input_params")
        if latest_run
        else (selected_model.get("current_input_params") if selected_model else None)
        or default_input_params()
    )
    input_review = build_input_review_summary(input_params)
    if latest_build:
        model = latest_build["model"]
    else:
        change_classification = {
            "type": "input_only",
            "source": "empty_workspace",
            "reason": "No generated package exists yet.",
        }
        workflow_state = build_workflow_state(
            current_stage="define",
            input_review_summary=input_review,
            change_classification=change_classification,
            run_type="seed",
            draft_status="not_built",
        )
        model = {
            "id": "",
            "label": "No generated package",
            "source": "",
            "plan": {"title": "No generated package", "steps": [], "assumptions": []},
            "build_metadata": {
                "openai_called": False,
                "mode": "empty_workspace",
                "workflow_state": workflow_state,
                "input_review_summary": input_review,
                "draft_status": "not_built",
            },
        }
    workflow_state = (
        (latest_run.get("workflow_state") if latest_run else None)
        or model.get("build_metadata", {}).get("workflow_state")
        or build_workflow_state(
            current_stage="define",
            input_review_summary=input_review,
            change_classification={
                "type": "input_only",
                "source": "empty_workspace",
                "reason": "No generated package metadata is available yet.",
            },
            run_type="seed",
            draft_status="not_built",
        )
    )
    visible_input_review = (latest_run.get("input_review_summary") if latest_run else None) or input_review
    conversation = read_input_agent_conversation(model_id) if selected_model else _initial_conversation("new model")
    review_conversation = read_review_agent_conversation(model_id) if selected_model else _initial_review_conversation("new model")
    if selected_model:
        selected_model = model_registry.read_model(model_id)
    if selected_model and (
        model_builder.is_model_package_version(selected_model)
        or (
            selected_model.get("current_version_id")
            and (model_builder.version_dir(str(selected_model["model_id"]), str(selected_model["current_version_id"])) / "model_spec.json").exists()
        )
    ):
        package_state = model_builder.read_state(selected_model)
    else:
        package_state = {"version_id": None, "status": "not_started", "publish_eligible": False}
    if selected_model:
        package_state_inputs = _workspace_input_params(selected_model.get("current_input_params"), package_state.get("resolved_input_params"))
        if package_state_inputs:
            input_params = package_state_inputs
            input_review = build_input_review_summary(input_params)
            visible_input_review = input_review
        if not latest_run:
            latest_run = _latest_run_from_package_state(selected_model, package_state, input_params)
            if latest_run:
                visible_input_review = latest_run.get("input_review_summary") or visible_input_review
                workflow_state = latest_run.get("workflow_state") or workflow_state

    return {
        **EMPTY_WORKSPACE_PAYLOAD,
        "account": model_registry.LOCAL_ACCOUNT,
        "selected_model": selected_model,
        "canonical_inputs": input_params,
        "input_review_summary": visible_input_review,
        "workflow_state": workflow_state,
        "model": model,
        "model_library": [],
        "model_library_lazy": {
            "loaded": False,
            "endpoint": f"/api/builds?model_id={model_id}" if model_id else "/api/builds",
        },
        "latest_run": latest_run,
        "action_state": _workspace_action_state(selected_model, latest_build, latest_run),
        "openai": openai_status_payload(),
        "package_state": package_state,
        "input_agent_conversation": conversation,
        "review_agent_conversation": review_conversation,
    }

def _latest_run_from_package_state(
    manifest: dict[str, Any],
    package_state: dict[str, Any],
    input_params: dict[str, Any],
) -> dict[str, Any] | None:
    from backend.app.model_usage import openai_status_payload

    """Expose persisted package output as a run when older local data lacks run JSON."""
    output = package_state.get("latest_output")
    if not isinstance(output, dict) or not isinstance(output.get("output_blocks"), list):
        return None
    run_id = str(manifest.get("latest_run_id") or manifest.get("canonical_version_id") or package_state.get("version_id") or "")
    if not run_id:
        return None
    resolved_inputs = package_state.get("resolved_input_params") if isinstance(package_state.get("resolved_input_params"), dict) else input_params
    validation = package_state.get("validation_report") if isinstance(package_state.get("validation_report"), dict) else {}
    return {
        "run_id": run_id,
        "build_run_id": str(manifest.get("current_build_id") or run_id),
        "input_params": resolved_inputs,
        "model": {
            "id": "generated_package_model",
            "label": manifest.get("name") or "Generated package",
            "path": package_state.get("package_entrypoint") or "",
            "source": "",
            "plan": {"title": manifest.get("name") or "Generated package", "steps": [], "assumptions": []},
            "build_metadata": {"openai_called": False, "mode": "canonical_package", "package_state": package_state},
        },
        "result": output,
        "validation_summary": validation,
        "workflow_state": build_workflow_state(
            current_stage="refine",
            input_review_summary=build_input_review_summary(resolved_inputs),
            change_classification={"type": "input_only", "source": "published_package", "reason": "Loaded persisted package output."},
            run_type="latest",
            draft_status="published" if manifest.get("status") == "published" else str(manifest.get("status") or "draft"),
            validation=validation,
            stress={},
        ),
        "input_review_summary": build_input_review_summary(resolved_inputs),
        "metadata": {"openai_called": False, "mode": "canonical_package", "source": "package_state_latest_output"},
        "model_manifest": manifest,
        "openai": openai_status_payload(),
        "package_state": package_state,
    }

def _workspace_input_params(current_params: Any, resolved_params: Any) -> dict[str, Any]:
    current = current_params if isinstance(current_params, dict) else {}
    resolved = resolved_params if isinstance(resolved_params, dict) else {}
    if resolved and (not current or current == default_input_params()):
        return resolved
    return current or resolved


_MODEL_LIST_FIELDS = {
    "version",
    "account_id",
    "model_id",
    "name",
    "description",
    "status",
    "scope_approved",
    "version_ids",
    "current_version_id",
    "canonical_version_id",
    "current_version_state",
    "published_utc",
    "created_utc",
    "updated_utc",
    "current_build_id",
    "latest_run_id",
    "latest_validation_state",
    "latest_stress_state",
    "publish_eligible",
    "publish_blocker",
    "artifact_kind",
}


def _model_list_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in _MODEL_LIST_FIELDS if key in manifest}


def list_models_payload() -> dict[str, Any]:
    from backend.app.model_usage import openai_status_payload

    payload = model_registry.build_models_payload()
    return {
        **payload,
        "models": [_model_list_summary(model) for model in payload.get("models", [])],
        "openai": openai_status_payload(),
    }


