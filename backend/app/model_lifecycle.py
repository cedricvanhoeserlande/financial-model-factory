from __future__ import annotations

from backend.app.model_context import *
from backend.app import model_spec
from backend.app.model_workspace import build_workspace_payload, default_input_params, list_models_payload
from backend.app.model_conversations import read_input_agent_conversation, _write_input_agent_conversation

def create_model_record(name: str, description: str) -> dict[str, Any]:
    manifest = model_registry.create_model(
        name=name,
        description=description,
        input_params=default_input_params(),
    )
    return {
        "model_manifest": manifest,
        "workspace": build_workspace_payload(manifest["model_id"]),
        **list_models_payload(),
    }

def build_model_package_record(model_id: str, prompt: str, *, openai_backed: bool = True, run_review: bool = True) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    if not openai_backed:
        raise RuntimeError("Package builds require OpenAI to generate model logic.")
    approved_spec = model_spec.require_approved_model_spec(manifest)
    clean_prompt = prompt.strip() or approved_spec.get("source_prompt") or manifest.get("description") or manifest.get("name") or "Build a custom model package."
    pipe = model_builder.build(manifest, clean_prompt, approved_spec=approved_spec, run_review=run_review)
    updated_manifest = _attach_package_state(model_id, pipe, pipe.get("resolved_input_params") or model_builder.default_inputs())
    _append_minimal_conversation(updated_manifest, clean_prompt)
    return {"model_manifest": updated_manifest, "workspace": build_workspace_payload(model_id), "package_state": pipe}

def resume_interrupted_review_record(model_id: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    approved_spec = model_spec.require_approved_model_spec(manifest)
    prompt = str(approved_spec.get("source_prompt") or manifest.get("description") or manifest.get("name") or "").strip()
    if not prompt:
        raise RuntimeError("The interrupted review is missing its source prompt.")
    version_id = str(manifest.get("current_version_id") or "")
    failure = model_builder._read_json(model_builder.version_dir(model_id, version_id) / "failure_report.json")
    structural_retry = (
        str(failure.get("failure_stage") or "") == "review_agent_audit"
        and "structural evidence failed" in str(failure.get("message") or "").lower()
    )
    convergence_retry = (
        str(failure.get("failure_stage") or "") == "review_agent_audit"
        and any(
            marker in str(failure.get("message") or "").lower()
            for marker in (
                "function-tool loop ended",
                "did not return final json after tool use was disabled",
                "review agent finding is missing required fields",
            )
        )
    )
    if structural_retry:
        try:
            pipe = model_builder.resume_review_cycle_from_saved_attempts(manifest, prompt)
        except RuntimeError as exc:
            expected_incomplete = (
                "cumulative structural evidence" in str(exc).lower()
                or "at least two saved attempts" in str(exc).lower()
                or "matching saved package fingerprints" in str(exc).lower()
            )
            if not expected_incomplete:
                raise
        else:
            state = model_builder.read_state(manifest, state_override=pipe)
            updated_manifest = _attach_package_state(
                model_id,
                state,
                state.get("resolved_input_params") or manifest.get("current_input_params") or model_builder.default_inputs(),
            )
            return {"model_manifest": updated_manifest, "workspace": build_workspace_payload(model_id), "package_state": state}
    pipe = model_builder.run_review_cycle(
        manifest,
        prompt,
        resume_interrupted=not structural_retry and not convergence_retry,
        retry_structural_review=structural_retry,
        retry_failed_review=convergence_retry,
    )
    state = model_builder.read_state(manifest, state_override=pipe)
    updated_manifest = _attach_package_state(
        model_id,
        state,
        state.get("resolved_input_params") or manifest.get("current_input_params") or model_builder.default_inputs(),
    )
    return {"model_manifest": updated_manifest, "workspace": build_workspace_payload(model_id), "package_state": state}

def amend_model_package_record(model_id: str, message: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    versions_before = {
        item.name
        for item in model_builder.versions_root().joinpath(model_id).iterdir()
        if item.is_dir()
    } if model_builder.versions_root().joinpath(model_id).exists() else set()
    try:
        pipe = model_builder.amend(manifest, message)
    except Exception:
        versions_path = model_builder.versions_root() / model_id
        created = sorted(
            (item for item in versions_path.iterdir() if item.is_dir() and item.name not in versions_before),
            key=lambda item: item.stat().st_mtime,
        ) if versions_path.exists() else []
        if len(created) == 1:
            failed_state = model_builder._read_json(created[0] / "version_manifest.json")
            if failed_state.get("version_id"):
                _attach_package_state(
                    model_id,
                    failed_state,
                    failed_state.get("resolved_input_params") or manifest.get("current_input_params") or model_builder.default_inputs(),
                )
        raise
    updated_manifest = _attach_package_state(model_id, pipe, pipe.get("resolved_input_params") or manifest.get("current_input_params") or model_builder.default_inputs())
    return {"model_manifest": updated_manifest, "workspace": build_workspace_payload(model_id), "package_state": pipe}

def generate_model_spec_record(model_id: str, prompt: str = "") -> dict[str, Any]:
    return model_spec.generate_model_spec_record(model_id, prompt)

def approve_model_spec_record(model_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    return model_spec.approve_model_spec_record(model_id, spec)

def _append_minimal_conversation(manifest: dict[str, Any], prompt: str) -> None:
    conversation = read_input_agent_conversation(str(manifest["model_id"]))
    messages = list(conversation.get("messages") or [])
    if not any(item.get("role") == "user" and item.get("content") == prompt for item in messages if isinstance(item, dict)):
        messages.append({"role": "user", "content": prompt, "created_utc": _utc_now()})
    package_state = manifest.get("package_state") if isinstance(manifest.get("package_state"), dict) else {}
    status = str(package_state.get("status") or "")
    assistant_content = (
        "Built a generated Python package. Technical checks passed; business review required."
        if status in {"review_ready", "published"}
        else "Generated package build did not reach review-ready status. Check the package failure report for exact reasons."
    )
    messages.append(
        {
            "role": "assistant",
            "content": assistant_content,
            "created_utc": _utc_now(),
        }
    )
    _write_input_agent_conversation(
        manifest,
        {
            **conversation,
            "messages": messages,
            "ready_to_draft": True,
            "ready_to_spec": True,
            "scope_summary": prompt,
            "open_questions": [],
            "locked_decisions": ["Approved model specification was used for package build."],
        },
    )

def _mark_model_artifact_kind(model_id: str, artifact_kind: str) -> None:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        return
    manifest["artifact_kind"] = artifact_kind
    model_registry.save_model(manifest)

def delete_model_record(model_id: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    build_ids = {str(build_id) for build_id in manifest.get("build_ids", []) if build_id}
    if manifest.get("current_build_id"):
        build_ids.add(str(manifest["current_build_id"]))
    run_ids = {str(run_id) for run_id in [manifest.get("latest_run_id")] if run_id}
    versions_path = model_builder.versions_root() / model_id
    if versions_path.exists():
        shutil.rmtree(versions_path)
    for build_id in build_ids:
        build_path = ARTIFACTS_DIR / build_id
        if build_path.exists():
            shutil.rmtree(build_path)
    for artifact_dir in ARTIFACTS_DIR.iterdir() if ARTIFACTS_DIR.exists() else []:
        if not artifact_dir.is_dir() or artifact_dir.name == "model_versions":
            continue
        metadata_path = artifact_dir / "metadata.json"
        metadata = _read_json(metadata_path) if metadata_path.exists() else {}
        if (
            artifact_dir.name in run_ids
            or str(metadata.get("model_id") or "") == model_id
            or str(metadata.get("build_run_id") or "") in build_ids
        ):
            shutil.rmtree(artifact_dir)
    _clear_latest_pointer_if_deleted(LATEST_BUILD_PATH, "run_id", build_ids)
    _clear_latest_pointer_if_deleted(LATEST_RUN_PATH, "run_id", run_ids | build_ids)
    if BUILD_INDEX_PATH.exists():
        _write_json(BUILD_INDEX_PATH, {"updated_utc": _utc_now(), "build_ids": []})
    return model_registry.delete_model(model_id)

def _clear_latest_pointer_if_deleted(path: Path, key: str, deleted_ids: set[str]) -> None:
    if not path.exists() or not deleted_ids:
        return
    payload = _read_json(path)
    if str(payload.get(key) or "") in deleted_ids or str(payload.get("build_run_id") or "") in deleted_ids:
        path.unlink()

def rename_model_record(model_id: str, name: str) -> dict[str, Any]:
    return model_registry.rename_model(model_id, name)

def open_model_workspace(model_id: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    return {
        "model_manifest": manifest,
        "workspace": build_workspace_payload(model_id),
    }

def publish_model_record(model_id: str) -> dict[str, Any]:
    current = model_registry.read_model(model_id)
    if not current:
        raise RuntimeError(f"Model not found: {model_id}")
    if current.get("current_version_id") and model_builder.is_model_package_version(current):
        pipe = model_builder.read_state(current)
        validation = pipe.get("validation_report") if isinstance(pipe.get("validation_report"), dict) else {}
        checks = {
            str(check.get("id")): bool(check.get("passed"))
            for check in validation.get("checks", [])
            if isinstance(check, dict)
        }
        required = {
            "package_imports",
            "run_model_callable",
            "output_contract_valid",
        }
        if validation.get("passed") is not True or not required.issubset(checks) or not all(checks[key] for key in required):
            raise RuntimeError("Package checks must pass before publishing.")
        stress = pipe.get("mechanical_stress_report") if isinstance(pipe.get("mechanical_stress_report"), dict) else {}
        stress_checks = {
            str(check.get("id")): bool(check.get("passed"))
            for check in stress.get("checks", [])
            if isinstance(check, dict)
        }
        stress_required = {
            "required_scenarios_present",
            "scenario_paths_valid",
            "scenario_covers_editable_inputs",
            "scenario_execution",
            "scenario_outputs_comparable",
            "non_base_scenarios_change_outputs",
        }
        if stress.get("passed") is not True or not stress_required.issubset(stress_checks) or not all(stress_checks[key] for key in stress_required):
            raise RuntimeError("Mechanical stress scenarios must pass before publishing.")
        review = pipe.get("review_report") if isinstance(pipe.get("review_report"), dict) else {}
        if review.get("approved") is not True or review.get("repair_required") is True:
            raise RuntimeError("Review Agent must approve before publishing.")
        model_registry.attach_package_version(
            model_id=model_id,
            version_id=str(current["current_version_id"]),
            state="review_ready",
            input_params=pipe.get("resolved_input_params") or current.get("current_input_params") or model_builder.default_inputs(),
        )
        manifest = model_registry.publish_model(model_id)
        model_builder.mark_published(manifest)
        return {
            "model_manifest": model_registry.read_model(model_id),
            "workspace": build_workspace_payload(model_id),
        }
    raise RuntimeError("Publishing is only available for generated package versions.")

def _attach_package_state(
    model_id: str,
    package_state: dict[str, Any],
    input_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    version_id = package_state.get("version_id")
    if not version_id:
        raise RuntimeError("Package action did not produce a version id.")
    manifest = model_registry.attach_package_version(
        model_id=model_id,
        version_id=str(version_id),
        state=str(package_state.get("status") or "draft"),
        input_params=input_params,
    )
    return manifest


