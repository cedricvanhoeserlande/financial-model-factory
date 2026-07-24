from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RUNTIME_DIR = Path(os.environ.get("MODEL_FACTORY_RUNTIME_DIR", DATA_DIR)).resolve()
MODELS_DIR = RUNTIME_DIR / "models"
MODEL_VERSIONS_DIR = RUNTIME_DIR / "artifacts" / "model_versions"
CURATED_MODEL_INDEX_PATH = DATA_DIR / "models" / "index.json"
USES_DEFAULT_DATA_RUNTIME = RUNTIME_DIR == DATA_DIR.resolve()
MODEL_INDEX_PATH = MODELS_DIR / ("runtime_index.json" if USES_DEFAULT_DATA_RUNTIME else "index.json")
LOCAL_ACCOUNT = {
    "account_id": "local_default",
    "name": "Local account",
}


def _scope_questions(name: str, description: str) -> list[str]:
    subject = name.strip() or "this model"
    purpose = description.strip()
    return [
        f"What purpose should {subject} support?",
        "Which objects or segments should be modeled separately?",
        "Which editable drivers should shape the outputs?",
        "Which output views should the package produce?",
        "Which assumptions should be editable by a regular user?",
        "What technical checks would make the package trustworthy?",
    ] if not purpose else [
        f"Confirm the model purpose: {purpose}",
        "Confirm the required output views and model cadence.",
        "Confirm the main drivers and which inputs should stay editable.",
        "Confirm whether any model-specific logic changes the package structure.",
        "Confirm the technical checks that must pass before publish.",
    ]


def _publish_eligible(manifest: dict[str, Any]) -> bool:
    if manifest.get("status") == "published" and not _published_package_health(manifest)["ok"]:
        return False
    return bool(manifest.get("current_version_state") == "review_ready" and manifest.get("current_version_id"))


def _publish_reason(manifest: dict[str, Any]) -> str:
    if manifest.get("current_version_state") == "artifact_missing":
        artifact_health = manifest.get("published_artifact_health") if isinstance(manifest.get("published_artifact_health"), dict) else {}
        return str(artifact_health.get("issue") or "Published package artifacts are missing.")
    if manifest.get("status") == "published":
        artifact_health = _published_package_health(manifest)
        if not artifact_health["ok"]:
            return str(artifact_health["issue"])
    if manifest.get("current_version_id") and manifest.get("current_version_state") != "review_ready":
        return "Package checks must pass before publishing."
    if not manifest.get("current_version_id"):
        return "Build the generated package before publishing."
    return "Ready to publish."


def _safe_artifact_child(root: Path, *parts: str) -> Path:
    resolved_root = root.resolve()
    path = resolved_root
    for part in parts:
        value = str(part or "").strip()
        if not value or any(sep in value for sep in ("/", "\\")) or ":" in value or ".." in Path(value).parts:
            raise ValueError(f"Invalid artifact path segment: {value}")
        path = path / value
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Artifact path escapes runtime root.") from exc
    return resolved


def _has_results_output(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("output_blocks"), list) and bool(payload.get("output_blocks"))


def _published_package_health(manifest: dict[str, Any]) -> dict[str, Any]:
    version_id = str(manifest.get("canonical_version_id") or manifest.get("current_version_id") or "").strip()
    model_id = str(manifest.get("model_id") or "").strip()
    if not version_id:
        return {"ok": False, "issue": "Published package version is missing."}
    try:
        root = _safe_artifact_child(MODEL_VERSIONS_DIR, validate_model_id(model_id), version_id)
    except ValueError as exc:
        return {"ok": False, "issue": str(exc)}
    version_manifest_path = root / "version_manifest.json"
    if not version_manifest_path.exists():
        return {"ok": False, "issue": "Published package manifest is missing."}
    version_manifest = _read_json(version_manifest_path)
    if version_manifest.get("status") != "published":
        return {"ok": False, "issue": "Published model points to a version that is not marked published."}
    if not (root / "model_package" / "model" / "main.py").exists():
        return {"ok": False, "issue": "Published package code is missing."}
    output_path = root / "model_package" / "outputs" / "output.json"
    if not output_path.exists() and not _has_results_output(version_manifest.get("latest_output")):
        return {"ok": False, "issue": "Published package output is missing."}
    return {"ok": True, "issue": ""}


def decorate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return a manifest with safe defaults and computed action state."""
    clean = dict(manifest)
    clean.setdefault("scope_approved", False)
    clean.setdefault("build_ids", [])
    clean.setdefault("version_ids", [])
    clean.setdefault("current_version_id", None)
    clean.setdefault("canonical_version_id", None)
    clean.setdefault("current_version_state", "not_started")
    clean.setdefault("published_utc", None)
    clean.setdefault("latest_stress_state", "not_run")
    clean.setdefault("latest_validation_state", "not_run")
    if clean.get("status") == "published":
        artifact_health = _published_package_health(clean)
        clean["published_artifact_health"] = artifact_health
        if not artifact_health["ok"]:
            clean["status"] = "draft"
            clean["current_version_state"] = "artifact_missing"
            clean["latest_validation_state"] = "failed"
            clean["latest_stress_state"] = "failed"
    clean["publish_eligible"] = _publish_eligible(clean)
    clean["publish_blocker"] = "" if clean["publish_eligible"] else _publish_reason(clean)
    return clean


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_models_dir() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _blank_index() -> dict[str, Any]:
    return {
        "version": "2026.05",
        "account": LOCAL_ACCOUNT,
        "model_ids": [],
        "updated_utc": _utc_now(),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _model_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "model"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


def validate_model_id(model_id: str) -> str:
    value = str(model_id or "").strip()
    if not value:
        raise ValueError("Model id is required.")
    if any(sep in value for sep in ("/", "\\")) or ":" in value:
        raise ValueError(f"Invalid model id: {value}")
    candidate = Path(value)
    if candidate.is_absolute() or value != candidate.name or ".." in candidate.parts:
        raise ValueError(f"Invalid model id: {value}")
    root = MODELS_DIR.resolve()
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Invalid model id: {value}") from exc
    return value


def _manifest_path(model_id: str) -> Path:
    return MODELS_DIR / validate_model_id(model_id) / "model_manifest.json"


def load_index() -> dict[str, Any]:
    _ensure_models_dir()
    if not MODEL_INDEX_PATH.exists():
        index = _blank_index()
        if USES_DEFAULT_DATA_RUNTIME and CURATED_MODEL_INDEX_PATH.exists():
            index = _read_json(CURATED_MODEL_INDEX_PATH)
        _write_json(MODEL_INDEX_PATH, index)
        return index
    return _read_json(MODEL_INDEX_PATH)


def save_index(index: dict[str, Any]) -> None:
    index["updated_utc"] = _utc_now()
    _write_json(MODEL_INDEX_PATH, index)


def list_models() -> list[dict[str, Any]]:
    index = load_index()
    models = []
    for model_id in index.get("model_ids", []):
        manifest = read_model(str(model_id))
        if manifest:
            models.append(decorate_manifest(manifest))
    return sorted(models, key=lambda model: model.get("updated_utc") or "", reverse=True)


def delete_model(model_id: str) -> dict[str, Any]:
    model_id = validate_model_id(model_id)
    index = load_index()
    model_ids = [str(existing_id) for existing_id in index.get("model_ids", [])]
    if model_id not in model_ids:
        raise RuntimeError(f"Model not found: {model_id}")
    model_dir = MODELS_DIR / model_id
    if model_dir.exists():
        shutil.rmtree(model_dir)
    index["model_ids"] = [existing_id for existing_id in model_ids if existing_id != model_id]
    save_index(index)
    return build_models_payload()


def rename_model(model_id: str, name: str) -> dict[str, Any]:
    manifest = read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    clean_name = name.strip()
    if not clean_name:
        raise RuntimeError("Model name is required.")
    manifest["name"] = clean_name
    manifest.setdefault("scope_summary", {})["model_name"] = clean_name
    save_model(manifest)
    return build_models_payload()


def create_model(
    *,
    name: str,
    description: str,
    input_params: dict[str, Any],
) -> dict[str, Any]:
    clean_name = name.strip() or "Untitled model"
    clean_description = description.strip()
    model_id = _model_id_from_name(clean_name)
    now = _utc_now()
    manifest = {
        "version": "2026.05",
        "account_id": LOCAL_ACCOUNT["account_id"],
        "model_id": model_id,
        "name": clean_name,
        "description": clean_description,
        "status": "draft",
        "scope_approved": False,
        "version_ids": [],
        "current_version_id": None,
        "canonical_version_id": None,
        "current_version_state": "not_started",
        "published_utc": None,
        "created_utc": now,
        "updated_utc": now,
        "current_build_id": None,
        "latest_run_id": None,
        "build_ids": [],
        "current_input_params": input_params,
        "latest_validation_state": "not_run",
        "latest_stress_state": "not_run",
        "scope_summary": {
            "agent": "Input Agent",
            "summary": clean_description or f"Define the operating model scope for {clean_name}.",
            "questions": _scope_questions(clean_name, clean_description),
        },
    }
    _write_json(_manifest_path(model_id), manifest)
    index = load_index()
    model_ids = [str(existing_id) for existing_id in index.get("model_ids", [])]
    if model_id not in model_ids:
        model_ids.append(model_id)
    index["model_ids"] = model_ids
    save_index(index)
    return decorate_manifest(manifest)


def read_model(model_id: str) -> dict[str, Any] | None:
    path = _manifest_path(model_id)
    if not path.exists():
        return None
    return decorate_manifest(_read_json(path))


def save_model(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest.pop("publish_eligible", None)
    manifest.pop("publish_blocker", None)
    manifest.pop("published_artifact_health", None)
    manifest["updated_utc"] = _utc_now()
    _write_json(_manifest_path(str(manifest["model_id"])), manifest)
    return decorate_manifest(manifest)


def publish_model(model_id: str) -> dict[str, Any]:
    manifest = read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    if not _publish_eligible(manifest):
        raise RuntimeError(_publish_reason(manifest))
    manifest["status"] = "published"
    if manifest.get("current_version_id"):
        manifest["canonical_version_id"] = manifest["current_version_id"]
        manifest["current_version_state"] = "published"
    manifest["published_utc"] = _utc_now()
    return save_model(manifest)


def attach_package_version(
    *,
    model_id: str,
    version_id: str,
    state: str,
    input_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    version_ids = [str(item) for item in manifest.get("version_ids", [])]
    if version_id not in version_ids:
        version_ids.append(version_id)
    manifest["version_ids"] = version_ids
    manifest["current_version_id"] = version_id
    manifest["current_version_state"] = state
    if input_params is not None:
        manifest["current_input_params"] = input_params
    if state in {"failed_checks", "repair_exhausted"}:
        manifest["latest_validation_state"] = "failed"
        manifest["latest_stress_state"] = "failed"
    elif state in {"review_ready", "published"}:
        manifest["latest_validation_state"] = "passed"
        manifest["latest_stress_state"] = "passed"
    elif state in {"package_built", "planned", "spec_approved", "spec_draft"}:
        manifest["latest_validation_state"] = "not_run"
        manifest["latest_stress_state"] = "not_run"
    return save_model(manifest)


def attach_build(
    *,
    model_id: str,
    build_run_id: str,
    input_params: dict[str, Any],
) -> dict[str, Any]:
    manifest = read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    build_ids = [str(build_id) for build_id in manifest.get("build_ids", [])]
    if build_run_id not in build_ids:
        build_ids.append(build_run_id)
    manifest["build_ids"] = build_ids
    manifest["current_build_id"] = build_run_id
    manifest["current_input_params"] = input_params
    manifest["latest_validation_state"] = "draft"
    manifest["latest_stress_state"] = "not_run"
    return save_model(manifest)


def attach_run(
    *,
    model_id: str,
    run_id: str,
    build_run_id: str,
    input_params: dict[str, Any],
    validation_passed: bool,
) -> dict[str, Any]:
    manifest = read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    manifest["latest_run_id"] = run_id
    manifest["current_build_id"] = build_run_id
    manifest["current_input_params"] = input_params
    manifest["latest_validation_state"] = "passed" if validation_passed else "failed"
    manifest["latest_stress_state"] = "passed" if validation_passed else "failed"
    return save_model(manifest)


def build_models_payload() -> dict[str, Any]:
    index = load_index()
    return {
        "account": index["account"],
        "models": list_models(),
    }
