from __future__ import annotations

from backend.app.model_context import *

def _use_unit_stubs() -> bool:
    return os.environ.get("MODEL_FACTORY_UNIT_STUBS", "").lower() in {"1", "true", "yes"}

def openai_status_payload() -> dict[str, Any]:
    use_unit_stubs = _use_unit_stubs()
    configured_model = model_config.model_for_role("modeler")
    return {
        "openai_mode": "unit_stub" if use_unit_stubs else "live",
        "may_call_openai": not use_unit_stubs,
        "configured_model": configured_model,
        "api_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
    }

def _summarize_token_usage(usage: dict[str, Any]) -> dict[str, int]:
    return openai_usage.summarize_token_usage(usage)

def _estimate_openai_cost(model: str, usage_summary: dict[str, int]) -> dict[str, Any]:
    return openai_usage.estimate_cost(model, usage_summary)

def _usage_ledger_path_for_display() -> str:
    if OPENAI_USAGE_LEDGER_PATH.is_relative_to(ROOT_DIR):
        return str(OPENAI_USAGE_LEDGER_PATH.relative_to(ROOT_DIR)).replace("\\", "/")
    return str(OPENAI_USAGE_LEDGER_PATH)

def _build_usage_report(
    *,
    build_run_id: str,
    model: str,
    status: str,
    usage: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    usage_summary = _summarize_token_usage(usage)
    cost_summary = _estimate_openai_cost(model, usage_summary)
    artifact_display = (
        str(artifact_dir.relative_to(ROOT_DIR)).replace("\\", "/")
        if artifact_dir.is_relative_to(ROOT_DIR)
        else str(artifact_dir)
    )
    return {
        "created_utc": _utc_now(),
        "build_run_id": build_run_id,
        "status": status,
        "model": model,
        "endpoint": "responses",
        "usage": usage,
        "usage_summary": usage_summary,
        "cost_summary": cost_summary,
        "artifact_dir": artifact_display,
        "ledger_path": _usage_ledger_path_for_display(),
    }

def _record_openai_usage(
    *,
    build_run_id: str,
    model: str,
    status: str,
    usage: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    report = _build_usage_report(
        build_run_id=build_run_id,
        model=model,
        status=status,
        usage=usage,
        artifact_dir=artifact_dir,
    )
    _write_json(artifact_dir / "usage_report.json", report)
    _append_jsonl(OPENAI_USAGE_LEDGER_PATH, report)
    return report
