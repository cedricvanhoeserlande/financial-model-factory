from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
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


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp" / "regular_mode_browser"


def _request_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class RegularModeBrowserTest(unittest.TestCase):
    def test_seeded_two_agent_history_is_visible_in_development_mode(self) -> None:
        if not (ROOT / "frontend" / "dist" / "index.html").exists():
            self.skipTest("Frontend production build is required.")
        try:
            from playwright.sync_api import expect, sync_playwright
        except ModuleNotFoundError:
            self.skipTest("Python Playwright is not installed.")

        runtime = RUNTIME_DIR / "two_agent_history"
        with isolated_runtime(runtime, unit_stubs="0"):
            model_loop, _registry, model_builder = reload_app_runtime_modules()
            created = model_loop.create_model_record("Seeded two-agent review proof", "")
            model_id = created["model_manifest"]["model_id"]
            approve_stub_spec(model_loop, model_id, "Build a narrow deterministic review fixture.")
            fake_usage = {"stage": "modeler_package_build", "model": "gpt-5.6-terra", "usage": {}, "openai_called": True}
            needs_repair = stub_review_report(approved=False, repair_required=True, summary="Exercise the stressed branch.")
            approved = stub_review_report(approved=True, summary="The revised package is grounded and acceptable.")
            with patch.object(model_builder, "request_model_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)), patch.object(
                model_builder, "request_review_report", side_effect=[needs_repair, needs_repair, approved]
            ), patch.object(
                model_builder, "request_repaired_package", return_value=(stub_package_files(), stub_base_inputs(), stub_input_schema(), stub_scenario_cases(), stub_modeler_self_check(), fake_usage)
            ):
                model_loop.build_model_package_record(model_id, "Build the seeded review package.")

            from backend.app import server as server_module

            httpd = server_module.create_server("127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                with sync_playwright() as playwright:
                    executable = os.environ.get("MODEL_FACTORY_PLAYWRIGHT_CHROMIUM_EXECUTABLE")
                    browser = playwright.chromium.launch(executable_path=executable or None)
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    page = context.new_page()
                    page.goto(base_url, wait_until="networkidle")
                    page.get_by_role("button", name="Seeded two-agent review proof", exact=True).first.click()
                    expect(page.get_by_test_id("pre-publish-workbench")).to_be_visible()
                    expect(page.get_by_test_id("review-repair-progress")).to_have_text("2 of 3")
                    expect(page.get_by_test_id("pre-publish-limitations")).to_be_visible()
                    page.screenshot(path=str(runtime / "two_agent_history.png"), full_page=True)
                    context.close()
                    browser.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=10)

    def test_seeded_published_package_reruns_with_visible_zero_call_evidence(self) -> None:
        if not (ROOT / "frontend" / "dist" / "index.html").exists():
            self.skipTest("Frontend production build is required.")
        try:
            from playwright.sync_api import expect, sync_playwright
        except ModuleNotFoundError:
            self.skipTest("Python Playwright is not installed.")

        with isolated_runtime(RUNTIME_DIR, unit_stubs="0"):
            model_loop, _registry, model_builder = reload_app_runtime_modules()
            created = model_loop.create_model_record("Seeded Regular Mode proof", "")
            model_id = created["model_manifest"]["model_id"]
            approve_stub_spec(model_loop, model_id, "Build a narrow deterministic browser fixture.")
            fake_usage = {
                "stage": "modeler_package_build",
                "model": "gpt-5.6-terra",
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
                "openai_called": True,
            }
            package_files = stub_package_files()
            for package_file in package_files:
                if package_file["path"] == "model/schedules/core.py":
                    package_file["content"] = package_file["content"].replace(
                        'primary = float(inputs["drivers"]["primary_value"])',
                        'primary_input = inputs["drivers"]["primary_value"]\n    primary_values = primary_input if isinstance(primary_input, list) else [float(primary_input)] * len(periods)\n    primary = float(primary_values[0])',
                    ).replace(
                        'change_rate = float(inputs["drivers"]["change_rate"])',
                        'change_input = inputs["drivers"]["change_rate"]\n    change_rates = change_input if isinstance(change_input, list) else [float(change_input)] * len(periods)',
                    ).replace(
                        'if index:\n            primary *= 1 + change_rate',
                        'if index:\n            primary = float(primary_values[index]) if isinstance(primary_input, list) else primary * (1 + float(change_rates[index]))',
                    )
                if package_file["path"] == "model/outputs.py":
                    package_file["content"] = package_file["content"].replace(
                        '"dashboard_spec": {"intent": "Show KPI, model rows, time series, and scenario comparison blocks."},',
                        '"dashboard_spec": {"version": "2.0", "template_id": "executive_finance", "title": "Browser fixture", "subtitle": "Synthetic deterministic dashboard", "currency": "EUR", "display_units": "actuals", "sections": [{"id": "overview", "title": "Overview", "widgets": [{"id": "kpi", "block_id": "primary_result", "component": "kpi", "visual": "kpi", "columns": 4, "rows": 1, "options": {}}, {"id": "trend", "block_id": "primary_value_series", "component": "chart", "visual": "combo", "columns": 8, "rows": 3, "options": {"series_visuals": {"primary_value": "bar"}}}, {"id": "table", "block_id": "model_rows", "component": "table", "visual": "statement", "columns": 12, "rows": 3, "options": {}}]}]},',
                    )
            input_schema = stub_input_schema()
            input_schema["fields"][0].update({
                "type": "number_or_number_array",
                "period_count": 5,
                "period_labels": ["Year 1", "Year 2", "Year 3", "Year 4", "Year 5"],
                "min_value": 0.0,
                "max_value": 200.0,
            })
            input_schema["fields"][1].update({
                "type": "number_or_13_number_array",
                "unit": "percent",
                "storage_scale": "decimal",
                "display_scale": "percent",
                "min_value": -1.0,
                "max_value": 1.0,
            })
            with patch.object(
                model_builder,
                "request_model_package",
                return_value=(
                    package_files,
                    stub_base_inputs(),
                    input_schema,
                    stub_scenario_cases(),
                    stub_modeler_self_check(),
                    fake_usage,
                ),
            ), patch.object(model_builder, "request_review_report", return_value=stub_review_report()):
                model_loop.build_model_package_record(model_id, "Build the seeded package.")
            model_loop.publish_model_record(model_id)

            from backend.app import server as server_module

            httpd = server_module.create_server("127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{httpd.server_address[1]}"
            try:
                self.assertTrue(_request_json(f"{base_url}/api/health")["ok"])
                with sync_playwright() as playwright:
                    executable = os.environ.get("MODEL_FACTORY_PLAYWRIGHT_CHROMIUM_EXECUTABLE")
                    browser = playwright.chromium.launch(executable_path=executable or None)
                    context = browser.new_context(viewport={"width": 1440, "height": 900})
                    page = context.new_page()
                    page.goto(base_url, wait_until="networkidle")
                    page.get_by_role("button", name="Seeded Regular Mode proof", exact=True).first.click()
                    expect(page.get_by_test_id("regular-mode-trust-panel")).to_be_visible()
                    page.get_by_role("button", name="Model", exact=True).click()
                    expect(page.get_by_test_id("tab-model")).to_be_visible()
                    page.locator(".artifact-tree button").filter(has_text="main.py").click()
                    expect(page.locator(".artifact-code-panel pre")).to_contain_text("run_model")
                    with page.expect_download() as download_info:
                        page.get_by_test_id("download-package-archive").click()
                    self.assertTrue(download_info.value.suggested_filename.endswith(".zip"))
                    page.get_by_role("button", name="Input", exact=True).click()
                    page.get_by_test_id("input-group-Other").locator("summary").click()

                    page.get_by_test_id("expand-weekly-drivers-primary_value").click()
                    expect(page.get_by_test_id("input-drivers-primary_value-week-5")).to_be_visible()
                    expect(page.get_by_test_id("weekly-editor-drivers-primary_value")).to_contain_text("Year 5")
                    page.get_by_test_id("input-drivers-primary_value-week-1").fill("250")
                    expect(page.get_by_role("alert")).to_contain_text("at most 200")
                    expect(page.get_by_test_id("rerun-inputs-button")).to_be_disabled()
                    page.get_by_test_id("input-drivers-primary_value-week-1").fill("150")
                    expect(page.get_by_test_id("rerun-inputs-button")).to_be_enabled()

                    page.get_by_test_id("expand-weekly-drivers-change_rate").click()
                    expect(page.get_by_test_id("input-drivers-change_rate-week-1")).to_have_value("10")
                    page.get_by_test_id("input-drivers-change_rate-week-2").fill("20")
                    with page.expect_response(
                        lambda response: response.url.endswith("/api/run") and response.request.method == "POST"
                    ) as response_info:
                        page.get_by_test_id("header-rerun-button").click()
                    payload = response_info.value.json()

                    evidence = payload["package_state"]["rerun_execution_evidence"]
                    self.assertEqual(evidence["openai_call_delta"], 0)
                    self.assertFalse(evidence["openai_called"])
                    self.assertTrue(evidence["output_changed"])
                    page.get_by_role("button", name="Output", exact=True).click()
                    expect(page.get_by_test_id("regular-rerun-proof")).to_have_text("No-OpenAI rerun verified")
                    expect(page.get_by_test_id("regular-rerun-evidence-details")).to_contain_text("OpenAI call delta")
                    expect(page.get_by_test_id("regular-rerun-evidence-details")).to_contain_text("Outputs changed")
                    expect(page.locator(".echarts-finance-chart")).to_be_visible()
                    expect(page.locator(".finance-table-widget")).to_be_visible()
                    page.set_viewport_size({"width": 900, "height": 900})
                    expect(page.get_by_test_id("output-blocks-surface")).to_be_visible()
                    page.screenshot(path=str(RUNTIME_DIR / "regular_mode_rerun.png"), full_page=True)
                    context.close()
                    browser.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
