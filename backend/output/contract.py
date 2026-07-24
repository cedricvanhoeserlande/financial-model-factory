from __future__ import annotations

from collections import Counter
from typing import Any

from backend.output.dashboard_contract import validate_dashboard_spec

OUTPUT_VERSION = "2026-05-25"
SUPPORTED_BLOCK_TYPES = {"kpi", "table", "time_series", "scenario_comparison", "custom"}
FIRST_CLASS_BLOCK_TYPES = SUPPORTED_BLOCK_TYPES - {"custom"}


def validate_output_contract(output: Any) -> dict[str, Any]:
    """Validate the generic output data-library contract without model semantics."""
    errors: list[dict[str, Any]] = []
    custom_block_ids: list[str] = []
    block_types: Counter[str] = Counter()

    top_level_passed = isinstance(output, dict)
    if not top_level_passed:
        return _report(
            passed=False,
            checks=[
                {"id": "output_is_object", "passed": False, "error": "Output must be a JSON object."},
                {"id": "output_blocks_present", "passed": False, "error": "output_blocks is missing."},
            ],
            errors=[{"path": "", "message": "Output must be a JSON object."}],
            block_types={},
            custom_block_ids=[],
        )

    output_version_passed = output.get("output_version") == OUTPUT_VERSION
    blocks = output.get("output_blocks")
    blocks_present = isinstance(blocks, list) and bool(blocks)
    dashboard_present = isinstance(output.get("dashboard_spec"), dict)
    metadata = output.get("metadata")
    metadata_passed = isinstance(metadata, dict) and metadata.get("openai_called") is False
    allowed_top_level = {"output_version", "output_blocks", "dashboard_spec", "metadata"}
    unexpected_keys = sorted(str(key) for key in output.keys() if key not in allowed_top_level)

    block_ids: list[str] = []
    block_errors: list[dict[str, Any]] = []
    if isinstance(blocks, list):
        for index, block in enumerate(blocks):
            path = f"output_blocks[{index}]"
            if not isinstance(block, dict):
                block_errors.append({"path": path, "message": "Block must be an object."})
                continue
            block_id = block.get("id")
            block_type = block.get("type")
            label = block.get("label")
            data = block.get("data")
            if not isinstance(block_id, str) or not block_id.strip():
                block_errors.append({"path": f"{path}.id", "message": "Block id must be a non-empty string."})
            else:
                block_ids.append(block_id)
            if not isinstance(block_type, str) or block_type not in SUPPORTED_BLOCK_TYPES:
                block_errors.append({"path": f"{path}.type", "message": f"Unsupported block type: {block_type!r}."})
                continue
            block_types[block_type] += 1
            if block_type == "custom":
                custom_block_ids.append(str(block_id or path))
            if not isinstance(label, str) or not label.strip():
                block_errors.append({"path": f"{path}.label", "message": "Block label must be a non-empty string."})
            if not isinstance(data, dict):
                block_errors.append({"path": f"{path}.data", "message": "Block data must be an object."})
                continue
            block_errors.extend(_validate_block_data(path, block_type, data))

    duplicates = sorted(block_id for block_id, count in Counter(block_ids).items() if count > 1)
    unique_ids_passed = not duplicates
    block_shapes_passed = blocks_present and not block_errors

    if not output_version_passed:
        errors.append({"path": "output_version", "message": f"output_version must be {OUTPUT_VERSION}."})
    if not blocks_present:
        errors.append({"path": "output_blocks", "message": "output_blocks must be a non-empty array."})
    if not dashboard_present:
        errors.append({"path": "dashboard_spec", "message": "dashboard_spec must be an object."})
    if not metadata_passed:
        errors.append({"path": "metadata.openai_called", "message": "metadata.openai_called must be false."})
    if unexpected_keys:
        errors.append({"path": "", "message": f"Unexpected top-level output keys: {', '.join(unexpected_keys)}."})
    if duplicates:
        errors.append({"path": "output_blocks", "message": f"Duplicate block ids: {', '.join(duplicates)}."})
    dashboard_report = validate_dashboard_spec(output.get("dashboard_spec"), blocks)
    errors.extend(block_errors)
    errors.extend(dashboard_report.get("errors") or [])

    checks = [
        {"id": "output_is_object", "passed": top_level_passed},
        {"id": "output_version_current", "passed": output_version_passed, "expected": OUTPUT_VERSION, "actual": output.get("output_version")},
        {"id": "output_blocks_present", "passed": blocks_present, "block_count": len(blocks) if isinstance(blocks, list) else 0},
        {"id": "output_block_ids_unique", "passed": unique_ids_passed, "duplicate_ids": duplicates},
        {"id": "output_block_shapes_valid", "passed": block_shapes_passed, "errors": block_errors, "custom_block_ids": custom_block_ids},
        {"id": "dashboard_spec_present", "passed": dashboard_present},
        {"id": "dashboard_spec_valid", "passed": dashboard_report.get("passed") is True, "details": dashboard_report},
        {"id": "metadata_openai_false", "passed": metadata_passed},
        {"id": "output_top_level_keys_exact", "passed": not unexpected_keys, "unexpected_keys": unexpected_keys},
    ]
    return _report(
        passed=all(check["passed"] for check in checks),
        checks=checks,
        errors=errors,
        block_types=dict(sorted(block_types.items())),
        custom_block_ids=custom_block_ids,
        dashboard_report=dashboard_report,
    )


def _validate_block_data(path: str, block_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    if block_type == "kpi":
        return _validate_kpi(path, data)
    if block_type == "table":
        return _validate_table(path, data)
    if block_type == "time_series":
        return _validate_time_series(path, data)
    if block_type == "scenario_comparison":
        return _validate_scenario_comparison(path, data)
    if block_type == "custom":
        return []
    return [{"path": f"{path}.type", "message": f"Unsupported block type: {block_type}."}]


def _validate_kpi(path: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    if "value" not in data:
        return [{"path": f"{path}.data.value", "message": "KPI data must include value."}]
    if not _is_scalar(data.get("value")):
        return [{"path": f"{path}.data.value", "message": "KPI value must be scalar."}]
    return []


def _validate_table(path: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    columns = data.get("columns")
    rows = data.get("rows")
    if not isinstance(columns, list) or not columns:
        errors.append({"path": f"{path}.data.columns", "message": "Table columns must be a non-empty array."})
        column_ids: list[str] = []
    else:
        column_ids = []
        for index, column in enumerate(columns):
            if not isinstance(column, dict):
                errors.append({"path": f"{path}.data.columns[{index}]", "message": "Column must be an object."})
                continue
            column_id = column.get("id")
            label = column.get("label")
            if not isinstance(column_id, str) or not column_id.strip():
                errors.append({"path": f"{path}.data.columns[{index}].id", "message": "Column id must be a non-empty string."})
            else:
                column_ids.append(column_id)
            if not isinstance(label, str) or not label.strip():
                errors.append({"path": f"{path}.data.columns[{index}].label", "message": "Column label must be a non-empty string."})
    duplicate_columns = sorted(column_id for column_id, count in Counter(column_ids).items() if count > 1)
    if duplicate_columns:
        errors.append({"path": f"{path}.data.columns", "message": f"Duplicate column ids: {', '.join(duplicate_columns)}."})
    if not isinstance(rows, list):
        errors.append({"path": f"{path}.data.rows", "message": "Table rows must be an array."})
    else:
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"path": f"{path}.data.rows[{row_index}]", "message": "Row must be an object."})
                continue
            missing = [column_id for column_id in column_ids if column_id not in row]
            if missing:
                errors.append({"path": f"{path}.data.rows[{row_index}]", "message": f"Row missing columns: {', '.join(missing)}."})
    return errors


def _validate_time_series(path: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    x_values = data.get("x")
    series = data.get("series")
    if not isinstance(x_values, list) or not x_values:
        errors.append({"path": f"{path}.data.x", "message": "Time series x must be a non-empty array."})
        x_len = 0
    else:
        x_len = len(x_values)
    if not isinstance(series, list) or not series:
        errors.append({"path": f"{path}.data.series", "message": "Time series series must be a non-empty array."})
        return errors
    for index, row in enumerate(series):
        row_path = f"{path}.data.series[{index}]"
        if not isinstance(row, dict):
            errors.append({"path": row_path, "message": "Series row must be an object."})
            continue
        for key in ("id", "label"):
            if not isinstance(row.get(key), str) or not str(row.get(key)).strip():
                errors.append({"path": f"{row_path}.{key}", "message": f"Series {key} must be a non-empty string."})
        values = row.get("values")
        if not isinstance(values, list):
            errors.append({"path": f"{row_path}.values", "message": "Series values must be an array."})
            continue
        if len(values) != x_len:
            errors.append({"path": f"{row_path}.values", "message": "Series values length must match x length."})
        bad_values = [value for value in values if not _is_number(value)]
        if bad_values:
            errors.append({"path": f"{row_path}.values", "message": "Series values must be numeric."})
    return errors


def _validate_scenario_comparison(path: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    scenarios = data.get("scenarios")
    metrics = data.get("metrics")
    scenario_ids: list[str] = []
    if not isinstance(scenarios, list) or not scenarios:
        errors.append({"path": f"{path}.data.scenarios", "message": "Scenario comparison scenarios must be a non-empty array."})
    else:
        for index, scenario in enumerate(scenarios):
            scenario_path = f"{path}.data.scenarios[{index}]"
            if isinstance(scenario, dict) and isinstance(scenario.get("id"), str) and scenario.get("id").strip() and isinstance(scenario.get("label"), str) and scenario.get("label").strip():
                scenario_ids.append(str(scenario["id"]))
                continue
            errors.append({"path": scenario_path, "message": "Scenario must be an object with non-empty string id and label."})
    if not isinstance(metrics, list) or not metrics:
        errors.append({"path": f"{path}.data.metrics", "message": "Scenario comparison metrics must be a non-empty array."})
        return errors
    for index, metric in enumerate(metrics):
        metric_path = f"{path}.data.metrics[{index}]"
        if not isinstance(metric, dict):
            errors.append({"path": metric_path, "message": "Metric must be an object."})
            continue
        for key in ("id", "label"):
            if not isinstance(metric.get(key), str) or not str(metric.get(key)).strip():
                errors.append({"path": f"{metric_path}.{key}", "message": f"Metric {key} must be a non-empty string."})
        values = metric.get("values")
        if not isinstance(values, dict):
            errors.append({"path": f"{metric_path}.values", "message": "Metric values must be an object keyed by scenario id."})
            continue
        missing = [scenario_id for scenario_id in scenario_ids if scenario_id not in values]
        if missing:
            errors.append({"path": f"{metric_path}.values", "message": f"Metric values missing scenarios: {', '.join(missing)}."})
        bad = [scenario_id for scenario_id in scenario_ids if scenario_id in values and not _is_scalar(values[scenario_id])]
        if bad:
            errors.append({"path": f"{metric_path}.values", "message": f"Metric values must be scalar for scenarios: {', '.join(bad)}."})
    return errors


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _report(
    *,
    passed: bool,
    checks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    block_types: dict[str, int],
    custom_block_ids: list[str],
    dashboard_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "message": "Output data-library contract passed." if passed else "Output data-library contract failed.",
        "output_version": OUTPUT_VERSION,
        "supported_block_types": sorted(SUPPORTED_BLOCK_TYPES),
        "first_class_block_types": sorted(FIRST_CLASS_BLOCK_TYPES),
        "block_types": block_types,
        "custom_block_ids": custom_block_ids,
        "dashboard_report": dashboard_report or {},
        "errors": errors,
        "checks": checks,
    }
