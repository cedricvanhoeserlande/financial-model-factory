from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
PRICING_CONFIG_PATH = ROOT_DIR / "backend" / "config" / "openai_pricing.json"
DEFAULT_PRICING_MODEL = "gpt-5.6-terra"


@lru_cache(maxsize=1)
def load_pricing_config() -> dict[str, Any]:
    return json.loads(PRICING_CONFIG_PATH.read_text(encoding="utf-8-sig"))


def pricing_source() -> str:
    return str(load_pricing_config().get("pricing_source") or "https://openai.com/api/pricing/")


def pricing_table() -> dict[str, dict[str, float]]:
    raw = load_pricing_config().get("models") or {}
    return {
        str(model): {str(kind): float(value) for kind, value in rates.items()}
        for model, rates in raw.items()
        if isinstance(rates, dict)
    }


def summarize_token_usage(usage: dict[str, Any]) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "api_call_count": 0,
    }
    records = _flatten_usage_records(usage)
    for record in records:
        if not isinstance(record, dict):
            continue
        input_tokens = int(record.get("input_tokens") or 0)
        output_tokens = int(record.get("output_tokens") or 0)
        total_tokens = int(record.get("total_tokens") or input_tokens + output_tokens)
        input_details = record.get("input_tokens_details") or {}
        output_details = record.get("output_tokens_details") or {}
        totals["input_tokens"] += input_tokens
        totals["cached_input_tokens"] += int(input_details.get("cached_tokens") or 0)
        totals["output_tokens"] += output_tokens
        totals["reasoning_tokens"] += int(output_details.get("reasoning_tokens") or 0)
        totals["total_tokens"] += total_tokens
        totals["api_call_count"] += 1
    return totals


def _flatten_usage_records(usage: Any) -> list[dict[str, Any]]:
    if not isinstance(usage, dict):
        return []
    records: list[dict[str, Any]] = []
    if any(key in usage for key in ("input_tokens", "output_tokens", "total_tokens")):
        records.append(usage)
    for value in usage.values():
        if isinstance(value, dict):
            records.extend(_flatten_usage_records(value))
    return records


def estimate_cost(model: str, usage_summary: dict[str, int]) -> dict[str, Any]:
    rates = pricing_table().get(model)
    if not rates:
        return {
            "estimated_cost_usd": None,
            "pricing_note": f"No local price table entry for {model}; check the OpenAI usage dashboard.",
            "pricing_source": pricing_source(),
        }
    cached_input_tokens = min(usage_summary["cached_input_tokens"], usage_summary["input_tokens"])
    billable_input_tokens = max(usage_summary["input_tokens"] - cached_input_tokens, 0)
    estimated_cost = (
        billable_input_tokens * rates["input"]
        + cached_input_tokens * rates["cached_input"]
        + usage_summary["output_tokens"] * rates["output"]
    ) / 1_000_000
    return {
        "estimated_cost_usd": round(estimated_cost, 6),
        "pricing_note": "Estimate based on local standard-processing price table; billing dashboard is authoritative.",
        "pricing_source": pricing_source(),
        "rates_usd_per_1m_tokens": rates,
        "billable_input_tokens": billable_input_tokens,
    }


def estimate_pre_call(model: str, body_json: str, *, output_tokens: int) -> dict[str, Any]:
    rates = pricing_table().get(model) or pricing_table()[DEFAULT_PRICING_MODEL]
    input_tokens = max(1, int(len(body_json) / 3) + 1)
    estimated_cost = ((input_tokens * rates["input"]) + (output_tokens * rates["output"])) / 1_000_000
    return {
        "estimated_pre_call_tokens": input_tokens + output_tokens,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_pre_call_cost_usd": round(estimated_cost, 6),
        "payload_chars": len(body_json),
    }
