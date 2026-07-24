from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCustomUxContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
        self.components = (ROOT / "frontend" / "src" / "components" / "WorkspaceComponents.tsx").read_text(encoding="utf-8")
        self.helpers = (ROOT / "frontend" / "src" / "utils" / "viewHelpers.ts").read_text(encoding="utf-8")
        self.types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    def test_model_package_inputs_use_schema_driven_nested_renderer(self) -> None:
        self.assertIn('strategy === "model_package"', self.helpers)
        self.assertIn("function CustomInputsTable", self.components)
        self.assertIn("function NestedObjectRows", self.components)
        self.assertIn('data-testid={`${basePath}-input-table`}', self.components)

    def test_schema_driven_weekly_editor_is_explicit_and_validated(self) -> None:
        self.assertIn('field?.type === "number_or_13_number_array"', self.components)
        self.assertIn('field?.type === "number_or_number_array"', self.components)
        self.assertIn("function FlexibleScheduleEditor", self.components)
        self.assertIn("Edit by {cadenceLabel}", self.components)
        self.assertIn("periodLabels[index]", self.components)
        self.assertIn("Enter exactly 13 weekly values.", self.helpers)
        self.assertIn("period_count", self.helpers)
        self.assertIn("inputBoundsError", self.helpers)
        self.assertIn("inputErrors", self.app)
        self.assertIn("Correct invalid inputs before rerunning", self.app)

    def test_percent_schedule_formatting_preserves_field_scale(self) -> None:
        self.assertIn("value.map((item) => inputValue(item, field))", self.helpers)
        self.assertIn("toStoredInputNumber", self.helpers)

    def test_regular_custom_results_are_finance_user_surfaces(self) -> None:
        self.assertIn("function OutputBlocksSurface", self.components)
        self.assertIn('data-testid="output-blocks-surface"', self.components)
        self.assertIn("function OutputTableBlock", self.components)
        self.assertIn("function FinanceDashboard", self.components)
        self.assertIn("function FinanceChart", self.components)
        self.assertIn("echarts.init", self.components)
        self.assertIn("function ModelArtifactSurface", self.components)
        self.assertIn("Download package ZIP", self.components)
        self.assertIn("Presentation Agent", self.components)
        self.assertIn('data-testid="output-contract-problem"', self.components)
        self.assertNotIn('data-testid="regular-technical-details"', self.components)
        self.assertNotIn("function StressMatrix", self.components)
        self.assertNotIn('data-testid="stress-matrix"', self.components)
        self.assertNotIn("function ObjectGraphOutputs", self.components)
        self.assertNotIn("function CustomModelOutputs", self.components)
        self.assertNotIn("result.results_table", self.components)

    def test_regular_navigation_is_single_input_model_output_strip(self) -> None:
        self.assertIn('(["inputs", "model", "results"] as ActiveTab[])', self.components)
        self.assertIn('tab === "inputs" ? "Input" : tab === "results" ? "Output" : "Model"', self.components)
        self.assertNotIn('["inputs", "Inputs"]', self.components)
        self.assertNotIn('["results", "Results"]', self.components)

    def test_object_values_are_not_stringified_as_object_object(self) -> None:
        self.assertNotIn("[object Object]", self.helpers)
        self.assertNotIn("[object Object]", self.components)
        self.assertIn("JSON.stringify(value)", self.helpers)
        self.assertNotIn("No trend chart data was included in this run.", self.components)

    def test_set_by_path_uses_path_ancestor_cloning(self) -> None:
        self.assertIn("function cloneBranch", self.helpers)
        self.assertIn("const copy = current.slice()", self.helpers)
        self.assertIn("const copy: Record<string, unknown> = { ...source }", self.helpers)
        self.assertNotIn("structuredClone(root)", self.helpers)

    def test_publish_does_not_open_browser_confirm_dialog(self) -> None:
        publish_handler = self.app.split("async function handlePublish()", 1)[1].split("async function handleEnterDevelopment()", 1)[0]
        self.assertNotIn("window.confirm", publish_handler)

    def test_pre_publish_surfaces_do_not_claim_local_rerun(self) -> None:
        self.assertNotIn('data-testid="rerun-draft-inputs-button"', self.components)
        self.assertNotIn("Rerun draft inputs", self.components)
        self.assertNotIn("handleRunDraftInputs", self.app)
        self.assertIn("Local rerun becomes available after publication.", self.components)

    def test_development_action_is_an_honest_mode_switch(self) -> None:
        self.assertIn("Return to Development Mode", self.components)
        self.assertNotIn("Create draft version", self.components)
        self.assertIn("No new draft has been created", self.app)

    def test_regular_mode_exposes_version_review_and_rerun_evidence(self) -> None:
        self.assertIn('data-testid="regular-mode-trust-panel"', self.components)
        self.assertIn('data-testid="regular-version-identity"', self.components)
        self.assertIn('data-testid="regular-rerun-proof"', self.components)
        self.assertIn('data-testid="regular-rerun-evidence-details"', self.components)
        self.assertIn('data-testid="regular-limitations"', self.components)
        self.assertIn("Approved; business review still required", self.components)
        self.assertIn("export type RerunExecutionEvidence", self.types)
        self.assertIn("rerun_execution_evidence?: RerunExecutionEvidence", self.types)

    def test_pre_publish_workbench_contains_publish_ready_surfaces(self) -> None:
        self.assertIn('data-testid="pre-publish-workbench"', self.components)
        self.assertIn('data-testid="pre-publish-spec"', self.components)
        self.assertIn('data-testid="pre-publish-amendment"', self.components)
        self.assertIn('data-testid="modeler-amendment-input"', self.components)
        self.assertIn('data-testid="modeler-amendment-submit"', self.components)
        self.assertIn('data-testid="pre-publish-change-summary"', self.components)
        self.assertIn('data-testid="pre-publish-inputs"', self.components)
        self.assertIn('data-testid="pre-publish-outputs"', self.components)
        self.assertIn('data-testid="pre-publish-checks"', self.components)
        self.assertIn('data-testid="pre-publish-review"', self.components)
        self.assertIn('data-testid="pre-publish-technical-evidence"', self.components)

    def test_modeler_amendment_uses_backend_endpoint_only(self) -> None:
        self.assertIn('"/api/model/amend"', self.api)
        self.assertNotIn("api.openai.com", self.api)
        self.assertNotIn("api.openai.com", self.app)
        self.assertNotIn("version rollback", self.components.lower())
        self.assertIn("Technical checks passed; business review required", self.components)


if __name__ == "__main__":
    unittest.main()
