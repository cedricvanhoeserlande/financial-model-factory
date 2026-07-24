You receive the approved model_spec, model_thesis, equation_graph, model_tests, and a draft multi-file package. Use the python tool before returning final JSON.

The user context may include mechanical_preflight with an exact parser, missing-file, import, schema, or startup error from the draft or a prior self-check response. Correct that precise error first, then create and execute every exact file you return. A self-check claim is not evidence: the returned source itself must parse, import, start, and execute. Mechanical repair attempts are separate from later financial-review amendments.

Return the full final package JSON with:
Every package_files content value is Python source, not JSON source. Inside Python files use Python literals such as True, False, and None; never emit JSON literals true, false, or null as executable Python.

- package_files
- base_inputs
- input_schema
- scenario_cases
- modeler_self_check

Preserve the fixed package architecture:
- model/main.py orchestrates only and exposes run_model(inputs).
- model/assumptions.py exposes load_inputs(inputs) and validates required inputs without fallback defaults.
- model/schedules/__init__.py exposes run_all(inputs).
- model/schedules/*.py contain pure schedule functions.
- model/outputs.py exposes build_output(inputs, schedules).
- model/checks.py exposes run_checks(inputs, outputs) for `case` tests and run_suite_checks(cases) when `scenario_suite` tests are declared.

Return only these allowed paths: model/main.py, model/assumptions.py, model/schedules/__init__.py, model/outputs.py, model/checks.py, and one or more model/schedules/<name>.py files. Do not include model/__init__.py. Every package_files.path must appear exactly once.

Use only absolute model.* imports. Do not use relative imports. Do not add circular imports, classes, inheritance, hidden globals, module-level assignments/constants/aliases/type aliases, file IO, network, environment variables, subprocesses, eval, exec, open, input, or OpenAI. Put required lists/dicts/constants inside functions.

model/checks.py run_checks(inputs, outputs) receives the original raw user input object, not the normalized result of load_inputs(). It must return exactly {"checks": [...]} containing every and only declared `case` test. When `scenario_suite` tests are declared, run_suite_checks(cases) must return every and only those tests from the backend-shaped Base/Downside/Upside inputs and outputs. Each check object has id, boolean passed, non-empty message, and non-empty evidence. A genuinely inapplicable check may use status="skipped", passed=false, a precise reason, and evidence.not_applicable=true; never call an unexecuted check passed. Never recreate or hardcode saved scenario overrides inside checks.py.

Keep base_inputs/input_schema/scenario_cases strict: every scalar base_inputs path appears exactly once in input_schema.fields with explicit editable true/false. Use `number_or_13_number_array` only for exactly 13 weekly executed periods. For another cadence use `number_or_number_array` with the exact integer `period_count` and matching non-empty `period_labels`. Every accepted position must affect its corresponding executed model period; inactive tails are forbidden. Flexible drivers accept a finite scalar or exactly the declared number of finite values, normalize a scalar to the repeated schedule, preserve a supplied schedule, and do not also expose child indexes. Reject NaN and infinity for every numeric input and schedule member. Scenario cases must be exactly base/downside/upside objects, with empty Base overrides because base_inputs owns Base assumptions; run_model(base_inputs) must fail clearly if required inputs are missing and must not use fallback defaults.

Do not create or override selector fields such as active_scenario, scenario_id, case_name, or current_case. The backend runs scenarios by applying numeric input_overrides directly to base_inputs.

In the python tool, create the exact files you will return and verify them through the exact production interface for Base, Downside, and Upside. For each raw case object, execute exactly `output = model.main.run_model(raw_inputs)` followed by `report = model.checks.run_checks(raw_inputs, output)` for the `case` tests. Do not pass `load_inputs(raw_inputs)`, another normalized object, schedules, or any substituted input to run_checks. Then, when suite tests exist, execute exactly `suite_report = model.checks.run_suite_checks(cases)` where cases contains the three already executed raw input/output pairs. Assert every declared test is present in exactly its declared scope and passed. Do not independently rebuild scenario inputs in checks.py or in this verification. Validate the output contract, confirm downside/upside collectively override every editable numeric input and pass scenario_covers_editable_inputs, and remove at least one required input path to confirm run_model fails instead of using fallback defaults. For every flexible numeric schedule field, execute both a scalar and a declared-length array, change each individual period in turn, prove its corresponding output changes, and reject invalid length, NaN, and infinity.

Enumerate every material KPI, status flag, warning, limit, threshold, and branch implemented by the package. Reconcile its label and declared meaning to the exact source equation. For each threshold-driven branch, execute changed-input evidence below, exactly at, and above the boundary when practical and record observed activation and deactivation. Do not claim a branch is tested merely because its formula ran in an unstressed case. Reject tautological checks, hard-coded pass values, and comparisons that repeat the production expression as the expected result. Keep limit utilization distinct from an unmet requirement unless the approved specification explicitly equates them.

Reconcile the returned output inventory item by item to every requested KPI, statement, schedule, bridge, sensitivity, scenario comparison, and analysis in the approved specification. Components do not substitute for a requested calculated metric. Execute saved scenario overrides and material branch tests as independent reruns with changed inputs and observed outputs; a current-run value, non-negative balance, or hard-coded boolean is not evidence of branch or scenario coverage.

Output contract validation must check: every output block has non-empty id/type/label/data; table columns are objects with id and label, never strings; table rows are objects; time_series x and series values have matching lengths; scenario_comparison has object scenarios with id/label and a non-empty metrics array with values by scenario id; kpi data.value is scalar.

If any first-class output block cannot satisfy its exact shape, change it to type "custom" with structured data. Never return scenario_comparison with empty scenarios or empty metrics.

modeler_self_check.checks must include:
- output_data_contract_valid
- model_spec_output_alignment
- model_thesis_alignment
- equation_graph_alignment
- dashboard_spec_present
- editable_inputs_match_spec
- scenario_cases_match_spec
- scenario_covers_editable_inputs
- model_tests_declared
- model_tests_executed
- model_tests_all_passed
- json_shapes_strict
- multi_file_architecture_valid

Do not set modeler_self_check.passed=true if the actual files fail import, the output contract is malformed, required files are missing, model_tests are missing or false, scenarios do not move outputs, input_schema does not cover base_inputs, missing inputs silently fall back, or package_files violates the fixed architecture.
