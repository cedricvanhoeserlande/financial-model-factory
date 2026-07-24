from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Any

from backend.app.package_runtime import execute_package, execute_package_checks


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE = Path("examples/paint_showcase/model_package")
MAX_ARTIFACT_BYTES = 512_000


def package_dir() -> Path:
    configured = os.environ.get("MODEL_FACTORY_PAINT_SHOWCASE_PACKAGE_DIR", "").strip()
    candidate = Path(configured) if configured else DEFAULT_PACKAGE
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    resolved = candidate.resolve()
    if not resolved.is_dir() or not (resolved / "model" / "main.py").is_file():
        raise RuntimeError(
            "The illustrative paint showcase package is unavailable. "
            "Set MODEL_FACTORY_PAINT_SHOWCASE_PACKAGE_DIR to the accepted package directory."
        )
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object at {path.name}.")
    return value


def _showcase_metadata(root: Path) -> dict[str, Any]:
    manifest_path = root.parent / "showcase_manifest.json"
    if not manifest_path.is_file():
        return {"package_version": root.parent.name}
    manifest = _read_json(manifest_path)
    return {
        "package_version": str(manifest.get("accepted_package_version") or root.parent.name),
        "source_model_id": str(manifest.get("source_model_id") or ""),
        "review_status": str(manifest.get("review_status") or ""),
    }


def _model_files(root: Path) -> list[dict[str, Any]]:
    model_root = (root / "model").resolve()
    result: list[dict[str, Any]] = []
    for path in sorted(model_root.rglob("*.py")):
        resolved = path.resolve()
        if not resolved.is_relative_to(model_root) or path.is_symlink():
            continue
        result.append(
            {
                "path": resolved.relative_to(root).as_posix(),
                "bytes": resolved.stat().st_size,
                "kind": "python",
            }
        )
    return result


def read_showcase() -> dict[str, Any]:
    root = package_dir()
    inputs = _read_json(root / "inputs" / "base_case.json")
    schema = _read_json(root / "inputs" / "input_schema.json")
    output = execute_package(root, inputs)
    checks = execute_package_checks(root, inputs, output)
    thesis = _read_json(root / "spec" / "model_thesis.json")
    limitations = [
        str(item.get("description") or "").strip()
        for item in ((thesis.get("model_thesis") or {}).get("limitations") or [])
        if isinstance(item, dict) and str(item.get("description") or "").strip()
    ]
    showcase_metadata = _showcase_metadata(root)
    return {
        "title": "Atelier Coatings & Tools S.A.",
        "synthetic": True,
        "inputs": inputs,
        "input_schema": schema,
        "model_files": _model_files(root),
        "output": output,
        "checks": checks,
        "limitations": limitations,
        "openai_called": False,
        "openai_call_delta": 0,
        **showcase_metadata,
    }


def rerun_showcase(inputs: Any) -> dict[str, Any]:
    if not isinstance(inputs, dict) or not inputs:
        raise RuntimeError("Showcase rerun requires a complete input object.")
    root = package_dir()
    output = execute_package(root, inputs)
    checks = execute_package_checks(root, inputs, output)
    check_rows = checks.get("checks") if isinstance(checks, dict) else None
    technical_passed = bool(check_rows) and all(
        isinstance(item, dict)
        and (
            item.get("passed") is True
            or (
                item.get("status") == "skipped"
                and item.get("passed") is False
                and isinstance(item.get("evidence"), dict)
                and item["evidence"].get("not_applicable") is True
            )
        )
        for item in check_rows
    )
    return {
        "output": output,
        "checks": checks,
        "technical_checks_passed": technical_passed,
        "openai_called": False,
        "openai_call_delta": 0,
        "execution_mode": "saved_python_package",
    }


def read_model_file(relative_path: str) -> dict[str, Any]:
    root = package_dir()
    normalized = relative_path.strip().replace("\\", "/")
    allowed = {item["path"] for item in _model_files(root)}
    if normalized not in allowed:
        raise RuntimeError("Requested showcase artifact is not an allowed generated model file.")
    path = (root / normalized).resolve()
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise RuntimeError("Showcase artifact is too large to preview.")
    return {
        "path": normalized,
        "content": path.read_text(encoding="utf-8"),
        "bytes": path.stat().st_size,
        "openai_called": False,
    }


def build_archive() -> dict[str, Any]:
    root = package_dir()
    allowed_roots = ("model", "inputs", "spec")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in allowed_roots:
            base = root / folder
            for path in sorted(base.rglob("*")) if base.exists() else []:
                if not path.is_file() or path.is_symlink():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(base.resolve()):
                    continue
                archive.write(resolved, resolved.relative_to(root).as_posix())
        run_path = root / "run.py"
        if run_path.is_file() and not run_path.is_symlink():
            archive.write(run_path, "run.py")
    return {
        "filename": "model-factory-showcase.zip",
        "content": buffer.getvalue(),
        "openai_called": False,
    }
