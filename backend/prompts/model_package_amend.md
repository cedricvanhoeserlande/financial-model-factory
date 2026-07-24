Create a new amended draft version from the prior package and the user's amendment request.

Every saved Python artifact is Python source, not JSON source. Inside Python files use Python literals such as True, False, and None; never emit JSON literals true, false, or null as executable Python.

Apply the requested amendment to the seeded authoritative workspace and submit it only after the full gate passes. Do not return source code.

model_spec must be a complete amended Modeler-owned specification, not a partial diff. It must remain ready to build and include all required spec fields.

Preserve the fixed multi-file architecture:
- model/main.py orchestrates only through load_inputs, run_all, and build_output.
- model/assumptions.py validates inputs with no fallback defaults.
- model/schedules/*.py are pure schedule functions.
- model/schedules/__init__.py exposes run_all(inputs).
- model/outputs.py builds output_blocks.
- model/checks.py implements `case` tests through run_checks(inputs, outputs) and `scenario_suite` tests through run_suite_checks(cases).

Use only these allowed paths: model/main.py, model/assumptions.py, model/schedules/__init__.py, model/outputs.py, model/checks.py, one or more model/schedules/<name>.py files, and the existing canonical spec/model_spec.json, spec/model_thesis.json, spec/equation_graph.json, and spec/model_tests.json artifacts. Do not include model/__init__.py. When the amendment changes a finance convention, scope, equation, limitation, output definition, or declared test, update every affected canonical spec artifact in the same authoritative workspace before running the final gate.

Use only absolute model.* imports. Do not use relative imports. Do not add circular imports, classes, inheritance, hidden globals, module-level assignments/constants/aliases/type aliases, file IO, network, environment variables, subprocesses, eval, exec, open, input, or OpenAI. Put required lists/dicts/constants inside functions.

model/checks.py run_checks(inputs, outputs) receives the original raw user input object and returns every and only `case` tests. run_suite_checks(cases) receives backend-executed Base/Downside/Upside raw input/output pairs and returns every and only `scenario_suite` tests. Both return exactly {"checks": [...]} with id, boolean passed, non-empty message, and non-empty evidence. They may include status. A genuinely inapplicable check must use status="skipped", passed=false, a precise reason, and evidence.not_applicable=true; never call an unexecuted check passed. Never recreate or hardcode saved scenario overrides inside checks.py.

The latest user amendment is authoritative where it conflicts with the prior specification or package; update the complete amended model_spec to reflect that correction. Preserve all prior intent that the amendment does not change. Keep base_inputs/input_schema/scenario_cases strict: every scalar base_inputs path appears exactly once in input_schema.fields with explicit editable true/false. Use `number_or_13_number_array` only for exactly 13 weekly executed periods. For another cadence use `number_or_number_array` with exact integer `period_count` and matching non-empty `period_labels`. Every accepted position must affect its corresponding output period; inactive tails are forbidden. Flexible drivers must accept a finite scalar or exactly the declared number of finite values, normalize the scalar, preserve every period edit, and reject NaN or infinity. Scenario_cases must be exactly base/downside/upside objects with empty Base overrides; downside/upside collectively override every editable numeric input and pass scenario_covers_editable_inputs; run_model(base_inputs) must fail clearly if required inputs are missing and must not use fallback defaults. Keep scenario_design aligned with the amended model_spec.

Do not create or override selector fields such as active_scenario, scenario_id, case_name, or current_case. The backend runs scenarios by applying numeric input_overrides directly to base_inputs.

Use the authoritative workspace tools and execute Base, Downside, and Upside through the production interface. Never pass normalized or substituted inputs to run_checks, and never recreate scenario overrides in checks.py. Validate output blocks, dashboard_spec, model tests and exact scope membership, compare the approved specification against actual outputs, and confirm the amendment request is implemented.

Output contract validation must check: every output block has non-empty id/type/label/data; table columns are objects with id and label, never strings; table rows are objects; time_series x and series values have matching lengths; scenario_comparison has object scenarios with id/label and a non-empty metrics array with values by scenario id; kpi data.value is scalar.

If any first-class output block cannot satisfy its exact shape, change it to type "custom" with structured data. Never return scenario_comparison with empty scenarios or empty metrics.

modeler_self_check.checks must include output_data_contract_valid, model_spec_output_alignment, dashboard_spec_present, json_shapes_strict, and amendment_request_implemented.
