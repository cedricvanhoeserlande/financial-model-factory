from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PaintCorrectnessContractTests(unittest.TestCase):
    def test_live_fixture_contains_external_review_corrections(self) -> None:
        catalog = json.loads((ROOT / "tests" / "prompt_matrix" / "catalog.json").read_text(encoding="utf-8"))
        case = next(item for item in catalog if item["id"] == "paint_factory_three_statement_dcf")
        prompt = case["prompt"]
        for required in (
            "6.0x terminal EBITDA",
            "50% optional excess-cash sweep",
            "2% interest income",
            "10-year remaining life",
            "half-year convention",
            "1% annual disposal assumption",
            "fully depreciated gross cost",
            "Year 1 normalization",
            "must not hardcode EUR 20.0m assets",
            "Legitimate zero inputs must not crash",
        ):
            self.assertIn(required, prompt)
        self.assertNotIn("tornado analysis", prompt)

    def test_generic_prompts_separate_base_acceptance_from_rerun_checks(self) -> None:
        build = (ROOT / "backend" / "prompts" / "model_package_build.md").read_text(encoding="utf-8")
        review = (ROOT / "backend" / "prompts" / "model_package_review.md").read_text(encoding="utf-8")
        workspace = (ROOT / "backend" / "prompts" / "modeler_workspace.md").read_text(encoding="utf-8")
        self.assertIn("must validate the submitted current inputs", build)
        self.assertIn("must enforce each declared minimum and maximum", build)
        self.assertIn("alternative but balanced opening balance sheet", review)
        self.assertIn("legitimate zero values", workspace)

    def test_showcase_uses_package_data_schema_bounds_and_current_check_status(self) -> None:
        source = (ROOT / "frontend" / "src" / "showcase" / "PaintShowcase.tsx").read_text(encoding="utf-8")
        stylesheet = (ROOT / "frontend" / "src" / "showcase" / "paintShowcase.css").read_text(encoding="utf-8")
        backend = (ROOT / "backend" / "app" / "paint_showcase.py").read_text(encoding="utf-8")
        self.assertNotIn("paintShowcaseData", source)
        self.assertNotIn("8500000", source)
        self.assertIn('Number(inputs.opening_term_debt ?? 0)', source)
        self.assertIn('Number(inputs.opening_revolver ?? 0)', source)
        self.assertIn('Number(inputs.opening_cash ?? 0)', source)
        self.assertIn('sensitivity_value_type === "equity_value"', source)
        self.assertIn('"Checks stale"', source)
        self.assertIn('"Checks passed"', source)
        self.assertIn("field.min_value", source)
        self.assertIn("field.max_value", source)
        self.assertIn("Correct invalid inputs before rerunning", source)
        self.assertIn('/^opening(?:\\.|_)/', source)
        self.assertIn('path !== "opening_ppe_life"', source)
        self.assertNotIn('path === "drivers.minimum_cash"', source)
        self.assertNotIn('block.id === "calculated_schedules"', source)
        self.assertIn('status === "skipped"', source)
        self.assertIn('examples/paint_showcase/model_package', backend)
        self.assertNotIn('tests/.tmp/live_showcase', backend)
        self.assertIn('.paint-topbar', stylesheet)
        self.assertIn('position:fixed', stylesheet)
        self.assertIn('padding-top:var(--paint-topbar-height)', stylesheet)
        self.assertIn('#statements .paint-grid.two { align-items:start; }', stylesheet)
        self.assertFalse((ROOT / "frontend" / "src" / "showcase" / "paintShowcaseData.ts").exists())

    def test_curated_package_is_complete_and_excludes_raw_api_artifacts(self) -> None:
        package = ROOT / "examples" / "paint_showcase" / "model_package"
        manifest = json.loads(
            (package.parent / "showcase_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["accepted_package_version"],
            "version_20260721_005747_33fedf06",
        )
        self.assertEqual(manifest["final_review_model"], "gpt-5.6-luna")
        for relative in (
            "model/main.py",
            "model/assumptions.py",
            "model/checks.py",
            "model/outputs.py",
            "model/schedules/core.py",
            "inputs/base_case.json",
            "inputs/input_schema.json",
            "inputs/scenarios.json",
            "spec/model_spec.json",
            "spec/model_thesis.json",
            "spec/equation_graph.json",
            "spec/model_tests.json",
            "reports/validation_report.json",
            "reports/model_tests_report.json",
            "reports/review_report.json",
        ):
            self.assertTrue((package / relative).is_file(), relative)
        self.assertFalse(list(package.rglob("raw_*")))
        self.assertFalse(list(package.rglob("*reasoning*")))


if __name__ == "__main__":
    unittest.main()
