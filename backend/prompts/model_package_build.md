Build the complete package in the authoritative workspace. Save Python under model/, base inputs under inputs/base_case.json, the input schema under inputs/input_schema.json, and {"scenario_cases": [...]} under inputs/scenarios.json.

Build from approved_model_spec, model_thesis, equation_graph, and model_tests supplied in the user message. Treat the raw user prompt as context, not as a replacement for those artifacts.

The workspace must contain the complete generated Python package. Required paths:
Every Python artifact is Python source, not JSON source. Inside Python files use Python literals such as True, False, and None; never emit JSON literals true, false, or null as executable Python.

- model/main.py
- model/assumptions.py
- model/schedules/__init__.py
- model/outputs.py
- model/checks.py
- at least one model/schedules/<name>.py

Create only those allowed paths. Do not include model/__init__.py, README files, tests, helpers outside model/schedules/, or any other package file.

Use only this boring functional architecture:
- model/main.py orchestrates only: call assumptions.load_inputs(), schedules.run_all(), and outputs.build_output(); expose run_model(inputs).
- model/assumptions.py reads and validates required inputs; no finance calculations and no fallback defaults.
- model/schedules/*.py are pure functions: inputs -> schedule dictionaries.
- model/schedules/__init__.py exposes run_all(inputs) and calls the schedule modules.
- model/outputs.py exposes build_output(inputs, schedules) and returns the hard output contract.
- model/checks.py exposes run_checks(inputs, outputs) for every `case` model test and, when declared, run_suite_checks(cases) for every `scenario_suite` model test.

Do not use circular imports, classes, inheritance, hidden globals, module-level assignments/constants/aliases/type aliases, file IO, network, environment variables, subprocesses, eval, exec, open, input, or OpenAI. Put required lists/dicts/constants inside functions. Use absolute model.* imports only. Do not use relative imports. Do not return files outside the exact allowed paths above.

model/checks.py run_checks(inputs, outputs) receives the original raw user input object, not the normalized result of load_inputs(). It must return exactly {"checks": [...]} containing every and only model_tests items with execution_scope `case`. Each check object has id, passed, message, and evidence, and may include status. passed must be boolean. message must be a non-empty string. evidence must be a non-empty object. By default passed=true means status passed and passed=false means status failed. A check that genuinely does not apply to the submitted case may instead return status="skipped", passed=false, a precise reason in message, and evidence.not_applicable=true. Never report an unexecuted or inapplicable check as passed. If a case check needs normalized schedules, derive them from outputs or explicitly normalize inside run_checks; never assume scalar raw inputs are already arrays.

If any model test has execution_scope `scenario_suite`, model/checks.py must also expose run_suite_checks(cases). The backend calls it once with exactly `{"base": {"inputs": raw_inputs, "output": output}, "downside": {...}, "upside": {...}}` after applying the saved scenario overrides and executing run_model for each case. It returns exactly {"checks": [...]} containing every and only `scenario_suite` test. Use those supplied cases for cross-scenario comparisons. Do not import run_model, recreate scenario definitions, or hardcode scenario override values in checks.py.

base_inputs is the complete runnable input state. input_schema is metadata for every scalar base_inputs path. Every scalar value in base_inputs must appear exactly once in input_schema.fields. Use `number_or_13_number_array` only for exactly 13 weekly modeled periods. For another repeated numeric cadence, use `number_or_number_array` with integer `period_count` and exactly that many non-empty `period_labels` (for example five annual labels). Every accepted position must map to an executed output period; never expose an inactive tail. A flexible numeric driver may be a finite scalar or exactly `period_count` finite numbers, and the generated package must normalize a scalar to the repeated schedule while preserving a supplied array. Do not emit separate child fields for the same flexible parent. Every field must include a non-empty string path, non-empty label, non-empty type, and explicit editable:true or editable:false. Include numeric min_value/max_value where economically meaningful. If a value can be changed by the user, mark editable:true and include it in scenario stress when numeric. Fixed required inputs must be editable:false. Implied/calculated values should be computed inside schedules or exposed as outputs, not hidden as fallback defaults. Reject NaN and infinity for every numeric input and schedule member. run_model(inputs) must fail clearly if a required input path is missing.

Input bounds are part of the executable model contract, not decorative UI metadata. assumptions.py must enforce each declared minimum and maximum for both scalar and scheduled values. Nonnegative business quantities, prices, costs, capital spending, and balance-sheet amounts must never become negative through either starting inputs or compounded drivers. Design zero-safe calculations: a legitimate zero input must either execute with a clearly defined result (using null/not-applicable for undefined ratios) or fail with a precise validation message where zero is economically impossible, never with ZeroDivisionError, NaN, infinity, or an unrelated exception.

Reusable case checks must validate the submitted current inputs and outputs, not memorize the original Base fixture. Do not hardcode requested opening totals, leverage ratios, no-draw states, fixed scenario values, or other build-time anchors inside run_checks. If the original request requires a particular Base opening condition, demonstrate it through the saved Base inputs and build-acceptance evidence. Reconstruct accounting identities and roll-forwards independently from current inputs and reported schedule components. A valid changed case must not fail merely because it differs from the original Base assumptions.

scenario_cases must be a JSON array with exactly base/downside/upside objects. Each object must have exactly id, label, description, and input_overrides. Downside and upside must collectively override every editable numeric input_schema.fields[].path at least once using coherent business cases. Overrides must use input_schema paths and numeric values only. Your draft must be able to pass scenario_covers_editable_inputs.

The base scenario input_overrides must be empty; base_inputs is the single source of Base assumptions.

Do not create or override selector fields such as active_scenario, scenario_id, case_name, or current_case. The backend runs scenarios by applying numeric input_overrides directly to base_inputs.

run_model must return:
{
  "output_version": "2026-05-25",
  "output_blocks": [],
  "dashboard_spec": {},
  "metadata": {"openai_called": false}
}

output_blocks must be non-empty and use only kpi, table, time_series, scenario_comparison, or custom. Every block must have non-empty id, type, label, and data. For table blocks, data.columns must be an array of objects such as {"id":"period","label":"Period"} and data.rows must be an array of row objects. Do not use string-only table columns. For time_series, data.x and each series.values must have matching lengths. For scenario_comparison, data.scenarios must be objects with id and label, and data.metrics must be a non-empty array of metric objects with values by scenario id. kpi data.value must be scalar.

If you cannot populate a valid first-class block shape, use type "custom" with structured data instead of returning a malformed table/time_series/scenario_comparison. Never return scenario_comparison with empty scenarios or empty metrics.

dashboard_spec is flexible display intent. Do not add review flags or warning blocks unless the approved model_spec explicitly requires them as modeled outputs.

A later Presentation Agent may replace only model/outputs.py. Therefore schedules must expose every canonical calculated fact needed for the approved statements, KPIs, valuation, sensitivities, and charts. Do not hide material finance calculations solely inside outputs.py. outputs.py may format and aggregate schedules for display, but finance mechanics and sensitivity recomputation belong in schedules.

Before returning, make an explicit inventory of every output, KPI, statement, schedule, sensitivity, bridge, scenario comparison, and analysis requested by the approved specification. Ensure each item is calculated in schedules and exposed through a correctly labelled output block; do not silently omit a requested executive metric such as net debt merely because its components are present.

Use the authoritative workspace execution and gate tools. Do not use Code Interpreter and do not return source code in the final completion object.
