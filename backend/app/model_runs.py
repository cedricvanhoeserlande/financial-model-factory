from __future__ import annotations

import io
import zipfile

from backend.app.model_context import *
from backend.app.model_usage import openai_status_payload
from backend.app.model_workspace import build_input_review_summary, build_workflow_state

def read_package_artifact(model_id: str, path: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    artifact = model_builder.read_artifact(manifest, path)
    if not artifact:
        raise RuntimeError("Artifact not found.")
    return {"artifact": artifact, "openai_called": False}


def build_package_archive(model_id: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    version_id = str(manifest.get("canonical_version_id") or manifest.get("current_version_id") or "")
    if not version_id:
        raise RuntimeError("Artifact not found.")
    package_dir = model_builder.version_dir(model_id, version_id) / "model_package"
    if not package_dir.exists():
        raise RuntimeError("Artifact not found.")
    allowed_report_names = {
        "validation_report.json", "mechanical_stress_report.json", "model_tests_report.json",
        "modeler_self_check.json", "presentation_agent_report.json", "review_execution_evidence.json",
        "review_report.json", "review_history.json", "rerun_execution_evidence.json",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(package_dir)
            if not relative.parts or relative.parts[0] not in {"model", "spec", "inputs", "outputs", "reports"}:
                continue
            if relative.parts[0] == "reports" and path.name not in allowed_report_names:
                continue
            archive.write(path, str(relative).replace("\\", "/"))
    return {"filename": f"{model_id}-{version_id}.zip", "content": buffer.getvalue(), "openai_called": False}

def execute_run(
    input_params: dict[str, Any],
    build_run_id: str | None = None,
    change_intent: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    _ensure_runtime_dirs()
    selected_model = model_registry.read_model(model_id) if model_id else None
    if model_id and not selected_model:
        raise RuntimeError(f"Model not found: {model_id}")
    canonical_version_id = str(selected_model.get("canonical_version_id") or "") if selected_model else ""
    if selected_model and canonical_version_id and (not build_run_id or str(build_run_id) == canonical_version_id):
        if not model_builder.is_model_package_version({**selected_model, "current_version_id": canonical_version_id}):
            raise RuntimeError("Regular rerun is only available for published generated packages.")
        pipe = model_builder.rerun(selected_model, input_params)
        resolved_input_params = pipe.get("resolved_input_params") or input_params
        output = pipe.get("latest_output") or {}
        validation = pipe.get("validation_report") or {}
        rerun_evidence = pipe.get("rerun_execution_evidence") or {}
        validation_passed = bool(validation.get("passed", True))
        selected_model = model_registry.attach_run(
            model_id=str(selected_model["model_id"]),
            run_id=canonical_version_id,
            build_run_id=canonical_version_id,
            input_params=resolved_input_params,
            validation_passed=validation_passed,
        )
        run_payload = {
            "run_id": canonical_version_id,
            "build_run_id": canonical_version_id,
            "input_params": resolved_input_params,
            "model": {
                "id": "generated_package_model",
                "label": selected_model.get("name") or "Generated package",
                "path": pipe.get("package_entrypoint"),
                "source": str((pipe.get("selected_artifact") or {}).get("content") or ""),
                "plan": {"title": selected_model.get("name") or "Generated package", "steps": [], "assumptions": []},
                "build_metadata": {"openai_called": False, "mode": "generated_package", "package_state": pipe},
            },
            "result": output,
            "validation_summary": validation,
            "workflow_state": build_workflow_state(
                current_stage="refine",
                input_review_summary=build_input_review_summary(resolved_input_params),
                change_classification={"type": "input_only", "source": "canonical_package", "reason": "Regular mode rerun uses the published package."},
                run_type="rerun",
                draft_status="published",
                validation=validation,
                stress={},
            ),
            "input_review_summary": build_input_review_summary(resolved_input_params),
            "metadata": {
                "openai_called": bool(rerun_evidence.get("openai_called", False)),
                "mode": "generated_package",
                "rerun_execution_evidence": rerun_evidence,
            },
            "model_manifest": selected_model,
            "openai": openai_status_payload(),
            "rerun_execution_evidence": rerun_evidence,
            "package_state": pipe,
        }
        _persist_run_payload(run_payload)
        return run_payload
    raise RuntimeError("Regular rerun requires a published canonical package. The removed generated-model execution path is unavailable.")

def list_model_builds(model_id: str | None = None) -> list[dict[str, Any]]:
    _ensure_runtime_dirs()
    selected_model = model_registry.read_model(model_id) if model_id else None
    if model_id and not selected_model:
        raise RuntimeError(f"Model not found: {model_id}")
    return []

def select_build(run_id: str, model_id: str | None = None) -> dict[str, Any]:
    raise RuntimeError("Legacy generated-model build selection was removed. Use published package versions.")

def read_build(run_id: str) -> dict[str, Any] | None:
    return None

def read_latest_build() -> dict[str, Any] | None:
    return None

def _run_state_path(run_id: str) -> Path | None:
    clean = str(run_id or "").strip()
    if not clean or any(sep in clean for sep in ("/", "\\")) or ":" in clean or ".." in Path(clean).parts:
        return None
    return RUN_STATE_DIR / f"{clean}.json"

def _persist_run_payload(run_payload: dict[str, Any]) -> None:
    run_id = str(run_payload.get("run_id") or "")
    path = _run_state_path(run_id)
    if path is None:
        return
    _write_json(path, run_payload)
    _write_json(LATEST_RUN_PATH, {"run_id": run_id, "updated_utc": _utc_now()})

def read_run(run_id: str) -> dict[str, Any] | None:
    path = _run_state_path(run_id)
    if path is None or not path.exists():
        return None
    return _read_json(path)

def read_latest_run(model_id: str | None = None) -> dict[str, Any] | None:
    if model_id:
        manifest = model_registry.read_model(model_id)
        if not manifest:
            raise RuntimeError(f"Model not found: {model_id}")
        return read_run(str(manifest.get("latest_run_id") or ""))
    if not LATEST_RUN_PATH.exists():
        return None
    payload = _read_json(LATEST_RUN_PATH)
    return read_run(payload["run_id"])


