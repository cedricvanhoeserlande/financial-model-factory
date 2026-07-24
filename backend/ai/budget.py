from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from backend.ai import usage as openai_usage
from backend.app import model_config


def _ledger_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _recorded_cost(record: dict[str, Any]) -> float:
    summary = record.get("cost_summary")
    if not isinstance(summary, dict):
        return 0.0
    try:
        value = float(summary.get("estimated_cost_usd") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(value, 0.0)


def recorded_spend(records: Iterable[dict[str, Any]]) -> float:
    return round(sum(_recorded_cost(record) for record in records), 6)


def pre_call_budget_decision(
    *,
    model: str,
    body_json: str,
    output_tokens: int,
    usage_ledger_path: Path,
    run_id: str | None = None,
    suite_ledger_path: Path | None = None,
    suite_limit_usd: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Check completed-call spend plus a conservative reservation before a call.

    The usage ledger supplies local-day and per-run spend. A dedicated shared suite
    ledger additionally caps a multi-run evaluation. The result is secret-free and
    safe to include in a decision report.
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    day_key = current.astimezone(UTC).date().isoformat()
    usage_records = _ledger_records(usage_ledger_path)
    day_records = [
        record
        for record in usage_records
        if str(record.get("created_utc") or "")[:10] == day_key
    ]
    run_records = [
        record
        for record in usage_records
        if run_id is not None
        and str(record.get("build_run_id") or record.get("run_id") or "").startswith(run_id)
    ]
    suite_records = _ledger_records(suite_ledger_path)

    estimate = openai_usage.estimate_pre_call(model, body_json, output_tokens=output_tokens)
    multiplier = model_config.budget_float("pre_call_cost_safety_multiplier", 1.25) or 1.25
    reserved_cost = round(float(estimate["estimated_pre_call_cost_usd"]) * multiplier, 6)
    limits = {
        "day": model_config.budget_float("max_cost_usd_per_day_local", None),
        "run": model_config.budget_float("max_cost_usd_per_run", None),
        "suite": suite_limit_usd,
    }
    recorded = {
        "day": recorded_spend(day_records),
        "run": recorded_spend(run_records),
        "suite": recorded_spend(suite_records),
    }
    checks: dict[str, dict[str, Any]] = {}
    blocked_by: list[str] = []
    for scope, limit in limits.items():
        if limit is None:
            checks[scope] = {"enabled": False, "allowed": True}
            continue
        projected = round(recorded[scope] + reserved_cost, 6)
        allowed = projected <= float(limit) + 1e-12
        checks[scope] = {
            "enabled": True,
            "allowed": allowed,
            "limit_usd": float(limit),
            "recorded_spend_usd": recorded[scope],
            "remaining_before_call_usd": round(max(float(limit) - recorded[scope], 0.0), 6),
            "projected_spend_usd": projected,
        }
        if not allowed:
            blocked_by.append(scope)

    return {
        "allowed": not blocked_by,
        "status": "allowed" if not blocked_by else "blocked",
        "blocked_by": blocked_by,
        "model": model,
        "estimate": estimate,
        "safety_multiplier": multiplier,
        "conservative_estimated_cost_usd": reserved_cost,
        "checks": checks,
        "pricing_is_estimate": True,
        "billing_dashboard_is_authoritative": True,
    }
