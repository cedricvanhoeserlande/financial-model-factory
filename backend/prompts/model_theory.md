Create model-local finance theory artifacts from the approved model_spec. Do not write Python code in this step.

Return exactly these top-level keys:
- model_thesis
- equation_graph
- model_tests

model_thesis must use exactly this shape:
{
  "thesis_version": "2026-05-31",
  "purpose": "...",
  "modeled_objects": [{"id": "...", "label": "...", "description": "..."}],
  "assumptions": [{"id": "...", "label": "...", "description": "..."}],
  "policy_choices": [{"id": "...", "label": "...", "description": "..."}],
  "outputs": [{"id": "...", "label": "...", "description": "..."}],
  "exclusions": [{"id": "...", "label": "...", "description": "..."}],
  "limitations": [{"id": "...", "label": "...", "description": "..."}]
}

Use model_thesis.outputs, not requested_outputs. This is model-local finance knowledge; the backend will store it but will not interpret finance semantics.

equation_graph must use exactly this shape:
{
  "graph_version": "2026-05-31",
  "nodes": [{"id": "...", "label": "...", "description": "...", "depends_on": []}],
  "edges": [{"id": "...", "label": "...", "description": "..."}],
  "calculation_order": ["..."],
  "key_tie_outs": [{"id": "...", "label": "...", "description": "..."}],
  "output_dependencies": [{"id": "...", "label": "...", "description": "..."}]
}

Use clear ids that the later package can implement.

model_tests is required and must be a non-empty array of structured executable tests the generated package must later implement in model/checks.py. These tests are model-local: choose them from the approved specification, model_thesis, and equation_graph. The backend will execute them but will not know finance semantics.

Each model_tests item must include:
- id
- label
- test_type: run_check, input_probe, or output_presence
- execution_scope: `case` when the check is independently true for one raw input/output pair, or `scenario_suite` when it compares Base, Downside, and Upside
- purpose
- logic_description
- evidence_expected
- repair_guidance

Use stable lowercase ids with underscores. Do not return prose-only tests. Do not leave model_tests empty, and include at least one `case` test. Include tests for important tie-outs, roll-forwards, prompt-fit requirements, scenario-sensitive mechanics, and output usefulness relevant to this specific model. Cross-scenario directionality or comparison tests must use `scenario_suite`; they must consume the backend-executed cases and must not recreate scenario overrides.

For every material KPI, status flag, warning, limit, threshold, or capacity mechanic, state its exact business meaning and make the test evidence distinguish that meaning from adjacent concepts. Where a threshold or branch exists, design executable evidence below, exactly at, and above the boundary when practical, and demonstrate both activation and deactivation. A test may claim branch coverage only when its inputs actually reach that branch and its observed outputs prove the expected behavior. Do not use tautologies, hard-coded passing booleans, or the same production expression on both sides of a purported check. Treat utilization of a limit and failure to satisfy a requirement as separate concepts unless the approved specification explicitly defines them as identical.

Separate Base-fixture acceptance from reusable model invariants. Original opening totals, leverage, or other requested starting facts may be verified as saved Base assumptions, but case tests must remain valid for any internally coherent changed input set. Design independent roll-forward checks from current inputs and schedule components, and include zero-value behavior plus alternative balanced opening structures where relevant.

The response is a design artifact, not final code. Keep it concise but specific enough that the package builder can implement the model without guessing the main mechanics.
