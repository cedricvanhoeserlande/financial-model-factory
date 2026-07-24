from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = Path(__file__).with_name("catalog.json")
DEFAULT_SELECTOR = "1"


@dataclass(frozen=True)
class PromptCase:
    id: str
    label: str
    prompt: str
    tags: tuple[str, ...]
    notes: str
    difficulty: str
    prompt_complexity: str

    def as_report(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "prompt": self.prompt,
            "tags": list(self.tags),
            "notes": self.notes,
            "difficulty": self.difficulty,
            "prompt_complexity": self.prompt_complexity,
        }


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._-").lower() or "prompt"


def load_prompt_catalog(path: Path = CATALOG_PATH) -> list[PromptCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Prompt catalog must be a JSON list.")
    cases: list[PromptCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Prompt catalog item {index} must be an object.")
        missing = [field for field in ("id", "label", "prompt", "tags", "notes", "difficulty", "prompt_complexity") if not item.get(field)]
        if missing:
            raise ValueError(f"Prompt catalog item {index} is missing required fields: {missing}")
        prompt_id = str(item["id"])
        if prompt_id in seen:
            raise ValueError(f"Duplicate prompt id: {prompt_id}")
        tags = item["tags"]
        if not isinstance(tags, list) or not all(isinstance(tag, str) and tag for tag in tags):
            raise ValueError(f"Prompt catalog item {prompt_id} must include non-empty string tags.")
        seen.add(prompt_id)
        cases.append(
            PromptCase(
                id=prompt_id,
                label=str(item["label"]),
                prompt=str(item["prompt"]),
                tags=tuple(tags),
                notes=str(item["notes"]),
                difficulty=str(item["difficulty"]),
                prompt_complexity=str(item["prompt_complexity"]),
            )
        )
    return cases


def select_prompt_cases(
    selector: str | None = None,
    *,
    catalog: Iterable[PromptCase] | None = None,
    random_count: int | None = None,
    seed: int | str | None = None,
) -> list[PromptCase]:
    cases = list(catalog if catalog is not None else load_prompt_catalog())
    if random_count is not None:
        if random_count < 1:
            raise ValueError("Random prompt count must be at least 1.")
        if random_count > len(cases):
            raise ValueError(f"Random prompt count {random_count} exceeds catalog size {len(cases)}.")
        rng = random.Random(str(seed or ""))
        return rng.sample(cases, random_count)
    chosen = (selector or DEFAULT_SELECTOR).strip()
    if not chosen:
        chosen = DEFAULT_SELECTOR
    if chosen.lower() == "all":
        return cases
    if chosen.isdigit():
        count = int(chosen)
        if count < 1:
            raise ValueError("Prompt count must be at least 1.")
        if count > len(cases):
            raise ValueError(f"Prompt count {count} exceeds catalog size {len(cases)}.")
        return cases[:count]
    requested = [part.strip() for part in chosen.split(",") if part.strip()]
    by_id = {case.id: case for case in cases}
    unknown = [prompt_id for prompt_id in requested if prompt_id not in by_id]
    if unknown:
        raise ValueError(f"Unknown prompt id(s): {', '.join(unknown)}")
    return [by_id[prompt_id] for prompt_id in requested]


def selected_prompt_cases() -> list[PromptCase]:
    random_selector = os.environ.get("MODEL_FACTORY_PROMPT_RANDOM")
    if random_selector:
        return select_prompt_cases(
            catalog=load_prompt_catalog(),
            random_count=int(random_selector),
            seed=os.environ.get("MODEL_FACTORY_PROMPT_SEED") or "",
        )
    selector = (
        os.environ.get("MODEL_FACTORY_PROMPT_SELECTOR")
        or os.environ.get("MODEL_FACTORY_PROMPTS")
        or DEFAULT_SELECTOR
    )
    return select_prompt_cases(selector)


def make_suite_run_dir(runtime_root: Path, test_name: str) -> Path:
    return runtime_root / f"{test_name}_{utc_stamp()}"


def make_cell_dir(suite_dir: Path, prompt_id: str) -> Path:
    return suite_dir / safe_id(prompt_id)


def empty_cell_report(case: PromptCase, methodology: str, cell_dir: Path) -> dict[str, Any]:
    return {
        "created_utc": utc_now(),
        "prompt": case.as_report(),
        "prompt_difficulty": case.difficulty,
        "prompt_complexity": case.prompt_complexity,
        "methodology": methodology,
        "passed": False,
        "failed_stage": None,
        "model_spec_status": None,
        "model_spec_ready": None,
        "spec_status": None,
        "pre_publish_status": None,
        "pre_publish_sections_present": {},
        "published_from_workbench": False,
        "validation_status": None,
        "output_block_validation": None,
        "mechanical_stress_status": None,
        "review_status": None,
        "repair_attempted": False,
        "function_tool_call_count": 0,
        "function_tool_error_count": 0,
        "required_amendments": [],
        "final_failure_reasons": [],
        "publish_status": None,
        "regular_rerun_openai_called": None,
        "model": None,
        "calls": 0,
        "openai_called": False,
        "api_durations": {},
        "tokens": {},
        "estimated_cost": {},
        "budget_status": None,
        "failure_code": None,
        "failure_subcode": None,
        "failure_stage": None,
        "failure_reasons": [],
        "next_actions": [],
        "review_findings": [],
        "artifact_paths": {
            "cell_dir": str(cell_dir),
        },
    }


def review_findings_summary(review_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(review_report, dict):
        return []
    rows: list[dict[str, Any]] = []
    for finding in review_report.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        evidence = finding.get("evidence") if isinstance(finding.get("evidence"), dict) else {}
        rows.append(
            {
                "severity": finding.get("severity"),
                "area": finding.get("area"),
                "claim_tested": finding.get("claim_tested"),
                "message": finding.get("message"),
                "artifact": evidence.get("artifact"),
                "requires_human_decision": finding.get("requires_human_decision"),
            }
        )
    return rows


def apply_package_diagnostics(report: dict[str, Any], package_state: dict[str, Any] | None, version_root: Path | None = None) -> None:
    if not isinstance(package_state, dict):
        return
    failure_report = package_state.get("failure_report") if isinstance(package_state.get("failure_report"), dict) else {}
    review_report = package_state.get("review_report") if isinstance(package_state.get("review_report"), dict) else {}
    report["failure_code"] = package_state.get("failure_code") or failure_report.get("failure_code") or report.get("failure_code")
    report["failure_subcode"] = package_state.get("failure_subcode") or failure_report.get("failure_subcode") or report.get("failure_subcode")
    report["failure_stage"] = package_state.get("failure_stage") or failure_report.get("failure_stage") or report.get("failure_stage")
    report["failure_reasons"] = package_state.get("failure_reasons") or failure_report.get("failure_reasons") or report.get("failure_reasons") or []
    report["next_actions"] = package_state.get("next_actions") or failure_report.get("next_actions") or report.get("next_actions") or []
    report["review_findings"] = review_findings_summary(review_report)
    tool_report = package_state.get("agent_tool_calls_report") if isinstance(package_state.get("agent_tool_calls_report"), dict) else {}
    report["function_tool_call_count"] = int(tool_report.get("tool_call_count") or report.get("function_tool_call_count") or 0)
    report["function_tool_error_count"] = int(tool_report.get("failed_tool_call_count") or report.get("function_tool_error_count") or 0)
    if isinstance(review_report.get("required_amendments"), list):
        report["required_amendments"] = review_report.get("required_amendments") or []
    if version_root:
        report.setdefault("artifact_paths", {})
        report["artifact_paths"]["agent_trace"] = str(version_root / "agent_trace.json")
        if (version_root / "failure_report.json").exists() or failure_report:
            report["artifact_paths"]["failure_report"] = str(version_root / "failure_report.json")


def apply_root_diagnostics(report: dict[str, Any], version_root: Path | None) -> None:
    if not version_root:
        return
    failure_path = version_root / "failure_report.json"
    review_path = version_root / "model_package" / "reports" / "review_report.json"
    manifest_path = version_root / "version_manifest.json"
    failure_report: dict[str, Any] = {}
    review_report: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    if failure_path.exists():
        failure_report = json.loads(failure_path.read_text(encoding="utf-8-sig"))
    if review_path.exists():
        review_report = json.loads(review_path.read_text(encoding="utf-8-sig"))
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    openai_calls = manifest.get("openai_calls") if isinstance(manifest.get("openai_calls"), list) else []
    if openai_calls and int(report.get("calls") or 0) == 0:
        call_summary = summarize_calls(openai_calls)
        report["model"] = call_summary["models"]
        report["calls"] = call_summary["calls"]
        report["openai_called"] = call_summary["calls"] > 0
        report["api_durations"] = call_summary["api_durations"]
        report["tokens"] = call_summary["tokens"]
        report["estimated_cost"] = call_summary["estimated_cost"]
        report["budget_status"] = call_summary["budget_status"]
        report["openai_stages"] = [call.get("stage") for call in openai_calls]
    if failure_report:
        report["failure_code"] = failure_report.get("failure_code") or report.get("failure_code")
        report["failure_subcode"] = failure_report.get("failure_subcode") or report.get("failure_subcode")
        report["failure_stage"] = failure_report.get("failure_stage") or report.get("failure_stage")
        report["failure_reasons"] = failure_report.get("failure_reasons") or report.get("failure_reasons") or []
        report["next_actions"] = failure_report.get("next_actions") or report.get("next_actions") or []
    if review_report:
        report["review_findings"] = review_findings_summary(review_report)
    report.setdefault("artifact_paths", {})
    report["artifact_paths"]["version_root"] = str(version_root)
    report["artifact_paths"]["agent_trace"] = str(version_root / "agent_trace.json")
    if failure_path.exists():
        report["artifact_paths"]["failure_report"] = str(failure_path)


def summarize_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    total_input = 0
    total_output = 0
    total_reasoning = 0
    total_tokens = 0
    estimated_cost = 0.0
    budget_status: str | None = None
    models: list[str] = []
    durations: list[float] = []
    retry_count = 0
    for call in calls:
        model = call.get("model")
        if model and model not in models:
            models.append(str(model))
        usage = call.get("usage_summary") or {}
        cost = call.get("cost_summary") or {}
        total_input += int(usage.get("input_tokens") or 0)
        total_output += int(usage.get("output_tokens") or 0)
        total_reasoning += int(usage.get("reasoning_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)
        estimated_cost += float(cost.get("estimated_cost_usd") or 0.0)
        if cost.get("budget_blocked") is True:
            budget_status = "blocked"
        if call.get("duration_seconds") is not None:
            durations.append(float(call.get("duration_seconds") or 0.0))
        retry_count += int(call.get("retry_count") or 0)
    return {
        "models": models,
        "calls": len(calls),
        "api_durations": {
            "total_duration_seconds": round(sum(durations), 3),
            "max_duration_seconds": round(max(durations), 3) if durations else None,
            "durations_seconds": durations,
            "retry_count": retry_count,
        },
        "tokens": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "reasoning_tokens": total_reasoning,
            "total_tokens": total_tokens,
        },
        "estimated_cost": {
            "estimated_cost_usd": round(estimated_cost, 6),
        },
        "budget_status": budget_status or "not_blocked",
    }


def output_contract_status(validation_report: dict[str, Any]) -> dict[str, Any]:
    report = validation_report.get("output_contract_report")
    if not isinstance(report, dict):
        for check in validation_report.get("checks") or []:
            if isinstance(check, dict) and check.get("id") == "output_contract_valid":
                report = check.get("report") if isinstance(check.get("report"), dict) else {}
                break
    return {
        "passed": bool(report.get("passed")) if isinstance(report, dict) else False,
        "block_types": report.get("block_types") if isinstance(report, dict) else {},
        "custom_block_ids": report.get("custom_block_ids") if isinstance(report, dict) else [],
        "errors": report.get("errors") if isinstance(report, dict) else [],
    }


def write_cell_report(cell_dir: Path, test_name: str, report: dict[str, Any]) -> Path:
    cell_dir.mkdir(parents=True, exist_ok=True)
    report_path = cell_dir / f"{test_name}_report.json"
    report["openai_called"] = bool(report.get("openai_called")) or int(report.get("calls") or 0) > 0
    report["artifact_paths"]["cell_report"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report_path


def write_summary_report(suite_dir: Path, test_name: str, reports: list[dict[str, Any]]) -> Path:
    suite_dir.mkdir(parents=True, exist_ok=True)
    total_cost = 0.0
    token_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    models: list[str] = []
    repair_count = 0
    function_tool_call_count = 0
    function_tool_error_count = 0
    required_amendments_by_prompt: dict[str, list[dict[str, Any]]] = {}
    api_duration_total = 0.0
    api_duration_max: float | None = None
    api_retry_count = 0
    failures: list[dict[str, Any]] = []
    budget_status = "not_blocked"
    regular_rerun_values: list[bool | None] = []
    for report in reports:
        for model in report.get("model") or []:
            if model not in models:
                models.append(model)
        tokens = report.get("tokens") or {}
        for key in token_totals:
            token_totals[key] += int(tokens.get(key) or 0)
        total_cost += float((report.get("estimated_cost") or {}).get("estimated_cost_usd") or 0.0)
        if report.get("repair_attempted"):
            repair_count += 1
        function_tool_call_count += int(report.get("function_tool_call_count") or 0)
        function_tool_error_count += int(report.get("function_tool_error_count") or 0)
        prompt_id = str((report.get("prompt") or {}).get("id") or "")
        if prompt_id and report.get("required_amendments"):
            required_amendments_by_prompt[prompt_id] = report.get("required_amendments") or []
        api_durations = report.get("api_durations") or {}
        api_duration_total += float(api_durations.get("total_duration_seconds") or 0.0)
        if api_durations.get("max_duration_seconds") is not None:
            max_duration = float(api_durations.get("max_duration_seconds") or 0.0)
            api_duration_max = max_duration if api_duration_max is None else max(api_duration_max, max_duration)
        api_retry_count += int(api_durations.get("retry_count") or 0)
        if not report.get("passed"):
            failures.append(
                {
                    "prompt_id": (report.get("prompt") or {}).get("id"),
                    "difficulty": report.get("prompt_difficulty") or (report.get("prompt") or {}).get("difficulty"),
                    "prompt_complexity": report.get("prompt_complexity") or (report.get("prompt") or {}).get("prompt_complexity"),
                    "methodology": report.get("methodology"),
                    "failed_stage": report.get("failed_stage"),
                    "failure_code": report.get("failure_code"),
                    "failure_subcode": report.get("failure_subcode"),
                    "failure_stage": report.get("failure_stage"),
                    "failure_reasons": report.get("failure_reasons") or [],
                    "next_actions": report.get("next_actions") or [],
                    "review_findings": report.get("review_findings") or [],
                    "required_amendments": report.get("required_amendments") or [],
                    "artifact_paths": report.get("artifact_paths") or {},
                    "final_failure_reasons": report.get("final_failure_reasons") or [],
                }
            )
        if report.get("budget_status") == "blocked":
            budget_status = "blocked"
        regular_rerun_values.append(report.get("regular_rerun_openai_called"))
    summary = {
        "created_utc": utc_now(),
        "test_name": test_name,
        "selected_prompt_count": len(reports),
        "prompt_difficulties": sorted({str(report.get("prompt_difficulty") or (report.get("prompt") or {}).get("difficulty") or "") for report in reports if report.get("prompt_difficulty") or (report.get("prompt") or {}).get("difficulty")}),
        "prompt_complexities": sorted({str(report.get("prompt_complexity") or (report.get("prompt") or {}).get("prompt_complexity") or "") for report in reports if report.get("prompt_complexity") or (report.get("prompt") or {}).get("prompt_complexity")}),
        "passed": not failures,
        "failures": failures,
        "repair_count": repair_count,
        "function_tool_call_count": function_tool_call_count,
        "function_tool_error_count": function_tool_error_count,
        "models": models,
        "calls": sum(int(report.get("calls") or 0) for report in reports),
        "openai_called": any(bool(report.get("openai_called")) or int(report.get("calls") or 0) > 0 for report in reports),
        "api_durations": {
            "total_duration_seconds": round(api_duration_total, 3),
            "max_duration_seconds": round(api_duration_max, 3) if api_duration_max is not None else None,
            "retry_count": api_retry_count,
        },
        "tokens": token_totals,
        "estimated_cost": {"estimated_cost_usd": round(total_cost, 6)},
        "budget_status": budget_status,
        "regular_rerun_openai_called_values": regular_rerun_values,
        "required_amendments_by_prompt": required_amendments_by_prompt,
        "cell_reports": [report.get("artifact_paths", {}).get("cell_report") for report in reports],
    }
    summary_path = suite_dir / f"{test_name}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return summary_path


def get_path(root: dict[str, Any], path: str) -> Any:
    current: Any = root
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def set_path(root: dict[str, Any], path: str, value: Any) -> None:
    current: Any = root
    parts = path.split(".")
    for part in parts[:-1]:
        next_value = current.setdefault(part, {})
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def editable_numeric_input_path(schema: dict[str, Any], inputs: dict[str, Any]) -> str:
    for field in schema.get("fields") or []:
        if not isinstance(field, dict) or field.get("read_only") is True or field.get("editable") is False:
            continue
        path = field.get("path")
        if not isinstance(path, str) or not path:
            continue
        value = get_path(inputs, path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return path
    raise AssertionError("Generated schema did not include an editable numeric field.")


def fingerprint(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
