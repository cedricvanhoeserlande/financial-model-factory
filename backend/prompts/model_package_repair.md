Revise the complete model package to resolve the current Review Agent required_amendments. Use the approved model_spec, latest review report, prior review history, deterministic reports, amendment evidence, and unresolved issue history as binding context.

Address every non-human blocker/high/medium amendment. Treat acceptance_criteria as outcomes to prove, not wording to repeat. Preserve correct existing behavior and do not regress amendments resolved in earlier rounds. Optional verification_probe objects are focused evidence, not the only permitted repair shape.

Every saved Python artifact is Python source. Inside Python files use Python literals such as True, False, and None; never emit JSON literals true, false, or null as executable Python.

Repair the seeded authoritative workspace in place. Do not return package source.

You receive only amendments assigned to the Modeler. Presentation-only amendments are handled separately by the Presentation Agent. Preserve every unrelated artifact byte-for-byte. The backend admits changes only within the artifact ownership implied by the assigned categories and retains the prior working version for unowned files/data. Do not opportunistically rewrite main.py, assumptions.py, outputs.py, input schema, inputs, scenarios, or schedule files that are outside the assigned amendment scope.

Preserve the fixed multi-file architecture:
- model/main.py orchestrates only through load_inputs, run_all, and build_output.
- model/assumptions.py validates required inputs with no fallback defaults.
- model/schedules/*.py are pure schedule functions.
- model/schedules/__init__.py exposes run_all(inputs).
- model/outputs.py builds output_blocks.
- model/checks.py implements `case` tests through run_checks(inputs, outputs) and `scenario_suite` tests through run_suite_checks(cases).

Use only model/main.py, model/assumptions.py, model/schedules/__init__.py, model/outputs.py, model/checks.py, one or more model/schedules/<name>.py files, and the existing canonical spec/model_spec.json, spec/model_thesis.json, spec/equation_graph.json, and spec/model_tests.json artifacts. When a required amendment concerns specification alignment, finance conventions, equations, limitations, outputs, or declared-test meaning, update every affected canonical spec artifact and prove the synchronized contract through the final gate. Use absolute model.* imports. Do not add classes, inheritance, circular imports, hidden globals, module constants, file IO, network, environment variables, subprocesses, eval, exec, open, input, or OpenAI.

Keep base_inputs/input_schema/scenario_cases strict: every scalar base input path appears exactly once in input_schema.fields with explicit editable true/false and there are no fallback defaults. Use `number_or_13_number_array` only for exactly 13 weekly executed periods. For another cadence use `number_or_number_array` with exact integer `period_count` and matching non-empty `period_labels`. Every accepted position must affect its corresponding output period; inactive tails are forbidden. Flexible drivers accept a finite scalar or exactly the declared number of finite values, normalize scalars, and preserve individual period edits. Reject NaN and infinity for all numeric inputs. run_model must fail clearly when a required input is missing. scenario_cases must be exactly base/downside/upside objects with empty Base overrides; downside/upside collectively override every editable numeric input and pass scenario_covers_editable_inputs. Do not create selector fields such as active_scenario.

Use the authoritative workspace tools. Begin with the saved Base case and execute the exact saved files across Base, Downside, and Upside through the production interface. run_checks receives raw inputs; never pass load_inputs(raw_inputs) or another normalized/substituted object. Never recreate or hardcode scenario overrides in checks.py. Validate output blocks and dashboard_spec, exercise the amendment acceptance criteria where practical, and recheck every material KPI, flag, limit, threshold, and warning. Where a branch is threshold-driven, retain executable evidence below, exactly at, and above the boundary and prove both activation and deactivation without tautological or hard-coded passing checks.

Begin production verification with `run_model(base_inputs)`. The final completion summary must identify evidence for each material issue as `amendment_<issue_id>` without embedding source code.

The authoritative gate replaces self-reported checks and must prove output_data_contract_valid, model_spec_output_alignment, dashboard_spec_present, and json_shapes_strict.

Reconcile every requested output in the approved specification against calculated schedules and exposed blocks, including derived executive metrics rather than only their components. Scenario and branch coverage must execute independent changed-input reruns and assert observed relationships; a current-run value, non-negative balance, repeated production expression, or literal boolean cannot substantiate coverage.

Keep every canonical finance result needed by the approved presentation in schedules. A later Presentation Agent may replace only model/outputs.py, so do not implement repaired finance mechanics solely as display calculations in outputs.py.

model/checks.py must accept original raw inputs and return exactly {"checks": [...]} with id, boolean passed, non-empty message, and non-empty evidence. A genuinely inapplicable check may use status="skipped", passed=false, a precise reason, and evidence.not_applicable=true; never call an unexecuted check passed. run_checks returns every and only `case` tests; run_suite_checks returns every and only `scenario_suite` tests.

Validate output shapes: non-empty id/type/label/data; object table columns and rows; aligned time-series arrays; non-empty scenario comparisons with object scenarios and metrics; scalar KPI values. Use custom blocks when a first-class shape is inappropriate.
