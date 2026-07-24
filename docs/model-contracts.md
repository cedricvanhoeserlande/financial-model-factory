# Model contracts

Each generated package is model-local but must satisfy technical interfaces.

## Required package artifacts

```text
model_package/
  run.py
  inputs/base_case.json
  inputs/input_schema.json
  inputs/scenarios.json
  model/main.py
  model/checks.py
  model/outputs.py
  spec/model_spec.json
  spec/model_thesis.json
  spec/equation_graph.json
  spec/model_tests.json
```

## Runtime interfaces

Generated packages expose a stable execution shape, including:

```python
run_model(inputs)
run_checks(inputs, outputs)
run_suite_checks(cases)
```

The runtime and admission gate validate structure, importability, JSON/schema
shapes, declared test membership, and output envelopes. The package—not the
frontend—owns model-specific finance equations and checks.

`inputs/scenarios.json` stores the defined input stress cases used by the
admission gate. The filename is part of the current package contract; these
cases are test evidence rather than dashboard modes.

## Input and output contracts

Input schemas express type, units, editability, and where provided, numeric
bounds. Packages may accept scalar or explicitly declared time-series inputs.
Output packages produce a versioned envelope containing `output_blocks`, a
`dashboard_spec`, and metadata. Numerical presentation data should bind to
calculated output blocks rather than untraceable inline claims.

Explicit contracts improve traceability, testing, repeatability, and review.
They do not guarantee that an economic model is appropriate or correct.
