Repair the package against the exact backend_failure_report, backend validation, scenario stress, or model_tests failure reports.

Every saved Python artifact is Python source, not JSON source. Inside Python files use Python literals such as True, False, and None; never emit JSON literals true, false, or null as executable Python.

Repair the seeded authoritative workspace in place and submit it only after the full gate passes. Do not return source code.

Preserve the fixed multi-file architecture:
- model/main.py orchestrates only through load_inputs, run_all, and build_output.
- model/assumptions.py validates inputs with no fallback defaults.
- model/schedules/*.py are pure schedule functions.
- model/schedules/__init__.py exposes run_all(inputs).
- model/outputs.py builds output_blocks.
- model/checks.py implements `case` model tests through run_checks(inputs, outputs) and `scenario_suite` tests through run_suite_checks(cases).

Use only these allowed paths: model/main.py, model/assumptions.py, model/schedules/__init__.py, model/outputs.py, model/checks.py, and one or more model/schedules/<name>.py files. Do not include model/__init__.py.

Use only absolute model.* imports. Do not use relative imports. Do not add circular imports, classes, inheritance, hidden globals, module-level assignments/constants/aliases/type aliases, file IO, network, environment variables, subprocesses, eval, exec, open, input, or OpenAI. Put required lists/dicts/constants inside functions.

model/checks.py run_checks(inputs, outputs) receives the original raw user input object, not the normalized result of load_inputs(). It returns every and only `case` tests. run_suite_checks(cases) receives the backend-executed Base/Downside/Upside raw input/output pairs and returns every and only `scenario_suite` tests. Both return exactly {"checks": [...]} with id, boolean passed, non-empty message, and non-empty evidence. A genuinely inapplicable check may use status="skipped", passed=false, a precise reason, and evidence.not_applicable=true; never call an unexecuted check passed. If case checks need normalized schedules, use executed outputs or normalize internally. Never recreate or hardcode saved scenario overrides inside checks.py.

Keep base_inputs/input_schema/scenario_cases strict: every scalar base_inputs path appears exactly once in input_schema.fields with explicit editable true/false. Use `number_or_13_number_array` only for exactly 13 weekly executed periods. For another cadence use `number_or_number_array` with exact integer `period_count` and matching non-empty `period_labels`. Every accepted position must affect its corresponding output period; inactive tails are forbidden. Flexible drivers must accept a finite scalar or exactly the declared number of finite values, normalize the scalar, preserve every period edit, and reject NaN or infinity. Scenario_cases must be exactly base/downside/upside objects with empty Base overrides; downside/upside collectively override every editable numeric input and pass scenario_covers_editable_inputs; run_model must fail clearly if required inputs are missing and must not use fallback defaults.

Do not create or override selector fields such as active_scenario, scenario_id, case_name, or current_case. The backend runs scenarios by applying numeric input_overrides directly to base_inputs.

Use the authoritative workspace tools and reproduce the backend's exact production invocation across Base, Downside, and Upside. Never test run_checks with normalized or substituted inputs. Validate exact scope membership, output blocks and model tests, confirm the reported backend failure is resolved, and submit only the passing production gate receipt. A result from a different harness does not resolve backend_failure_report.

Begin with `run_model(base_inputs)` and assert type(run_model(base_inputs)) is dict through the authoritative execution result before submission.

The production sequence is `output = run_model(raw_inputs)` followed by `report = run_checks(raw_inputs, output)` for each case; never substitute normalized inputs.

Never test `run_checks(load_inputs(raw_inputs), output)` or pass another substituted input object.

Treat the passing fingerprint-bound full gate as backend_failure_resolved evidence; never self-report that status before the gate passes.

Output contract validation must check: every output block has non-empty id/type/label/data; table columns are objects with id and label, never strings; table rows are objects; time_series x and series values have matching lengths; scenario_comparison has object scenarios with id/label and a non-empty metrics array with values by scenario id; kpi data.value is scalar.

When backend_failure_report includes output_contract_report errors, repair those exact output paths before anything else. If any first-class output block cannot satisfy its exact shape, change it to type "custom" with structured data. Never return scenario_comparison with empty scenarios or empty metrics.
