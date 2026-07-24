from __future__ import annotations

import unittest

from backend.output import validate_output_contract


def valid_output() -> dict:
    return {
        "output_version": "2026-05-25",
        "output_blocks": [
            {"id": "kpi_1", "type": "kpi", "label": "Metric", "data": {"value": 123.4}},
            {
                "id": "table_1",
                "type": "table",
                "label": "Rows",
                "data": {
                    "columns": [{"id": "period", "label": "Period"}, {"id": "value", "label": "Value"}],
                    "rows": [{"period": "Y1", "value": 1.0}],
                },
            },
            {
                "id": "series_1",
                "type": "time_series",
                "label": "Series",
                "data": {"x": ["Y1", "Y2"], "series": [{"id": "value", "label": "Value", "values": [1.0, 2.0]}]},
            },
            {
                "id": "scenarios_1",
                "type": "scenario_comparison",
                "label": "Scenarios",
                "data": {
                    "scenarios": [
                        {"id": "base", "label": "Base"},
                        {"id": "downside", "label": "Downside"},
                        {"id": "upside", "label": "Upside"},
                    ],
                    "metrics": [{"id": "value", "label": "Value", "values": {"base": 1.0, "downside": 0.8, "upside": 1.2}}],
                },
            },
            {"id": "custom_1", "type": "custom", "label": "Custom data", "data": {"payload": {"nested": True}}},
        ],
        "dashboard_spec": {"intent": "Display blocks by usefulness."},
        "metadata": {"openai_called": False},
    }


class OutputDataLibraryTest(unittest.TestCase):
    def test_accepts_supported_block_types(self) -> None:
        report = validate_output_contract(valid_output())

        self.assertTrue(report["passed"], report)
        self.assertEqual(report["block_types"]["kpi"], 1)
        self.assertEqual(report["custom_block_ids"], ["custom_1"])

    def test_rejects_missing_output_blocks(self) -> None:
        payload = valid_output()
        payload.pop("output_blocks")

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertIn("output_blocks", {error["path"] for error in report["errors"]})

    def test_rejects_duplicate_block_ids(self) -> None:
        payload = valid_output()
        payload["output_blocks"][1]["id"] = "kpi_1"

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        checks = {check["id"]: check for check in report["checks"]}
        self.assertFalse(checks["output_block_ids_unique"]["passed"])

    def test_rejects_malformed_table_rows(self) -> None:
        payload = valid_output()
        payload["output_blocks"][1]["data"]["rows"] = [{"period": "Y1"}]

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("missing columns" in error["message"].lower() for error in report["errors"]))

    def test_rejects_mismatched_time_series_lengths(self) -> None:
        payload = valid_output()
        payload["output_blocks"][2]["data"]["series"][0]["values"] = [1.0]

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("length" in error["message"].lower() for error in report["errors"]))

    def test_rejects_malformed_scenario_comparison(self) -> None:
        payload = valid_output()
        payload["output_blocks"][3]["data"]["metrics"][0]["values"].pop("upside")

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("missing scenarios" in error["message"].lower() for error in report["errors"]))

    def test_rejects_string_scenario_ids(self) -> None:
        payload = valid_output()
        payload["output_blocks"][3]["data"]["scenarios"] = [
            "base",
            "downside",
            "upside",
        ]

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("object with non-empty string id and label" in error["message"] for error in report["errors"]))

    def test_rejects_scenario_object_without_label(self) -> None:
        payload = valid_output()
        payload["output_blocks"][3]["data"]["scenarios"][0] = {"id": "base"}

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("object with non-empty string id and label" in error["message"] for error in report["errors"]))

    def test_rejects_unsupported_text_block_type(self) -> None:
        payload = valid_output()
        payload["output_blocks"].append({"id": "text_1", "type": "text", "label": "Text", "data": {"value": "not allowed"}})

        report = validate_output_contract(payload)

        self.assertFalse(report["passed"])
        self.assertTrue(any("unsupported block type" in error["message"].lower() for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
