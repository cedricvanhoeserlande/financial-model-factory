from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

from tests.runtime_helpers import isolated_runtime, reload_app_runtime_modules
from tests.test_minimal_product_path import (
    approve_stub_spec,
    stub_base_inputs,
    stub_input_schema,
    stub_modeler_self_check,
    stub_package_files,
    stub_review_report,
    stub_scenario_cases,
)


def dashboard_package_files() -> list[dict[str, str]]:
    files = stub_package_files()
    for item in files:
        if item["path"] != "model/outputs.py":
            continue
        item["content"] = item["content"].replace(
            '"dashboard_spec": {"intent": "Show KPI, model rows, time series, and scenario comparison blocks."},',
            '"dashboard_spec": {"version": "2.0", "template_id": "executive_finance", "title": "Atelier presentation fixture", "subtitle": "Synthetic deterministic dashboard", "currency": "EUR", "display_units": "actuals", "sections": [{"id": "overview", "title": "Executive overview", "widgets": [{"id": "kpi", "block_id": "primary_result", "component": "kpi", "visual": "kpi", "columns": 4, "rows": 1, "options": {}}, {"id": "trend", "block_id": "primary_value_series", "component": "chart", "visual": "combo", "columns": 8, "rows": 3, "options": {"series_visuals": {"primary_value": "bar"}}}, {"id": "table", "block_id": "model_rows", "component": "table", "visual": "statement", "columns": 12, "rows": 3, "options": {}}]}]},',
        )
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    with isolated_runtime(runtime, unit_stubs="0"):
        model_loop, _registry, model_builder = reload_app_runtime_modules()
        created = model_loop.create_model_record("Deterministic presentation fixture", "")
        model_id = created["model_manifest"]["model_id"]
        approve_stub_spec(model_loop, model_id, "Build a deterministic presentation fixture.")
        fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.6-terra", "usage": {}, "openai_called": False}
        with patch.object(model_builder, "request_model_package", return_value=(dashboard_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)), patch.object(
            model_builder, "request_review_report", return_value=stub_review_report()
        ):
            model_loop.build_model_package_record(model_id, "Build deterministic presentation fixture.")
        model_loop.publish_model_record(model_id)
        (runtime / "fixture_metadata.json").write_text(json.dumps({"model_id": model_id, "name": "Deterministic presentation fixture"}, indent=2), encoding="utf-8")

        from backend.app.server import create_server

        server = create_server("127.0.0.1", args.port)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
