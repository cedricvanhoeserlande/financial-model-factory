# Executed example

This curated showcase uses a fictional EUR paint-manufacturing and tools-distribution company. All company facts and amounts are synthetic.

The end-to-end flow is deliberately inspectable:

1. A `gpt-5.6-terra` Modeler designed and wrote the model-specific Python package through the authoritative workspace tools.
2. Model Factory varied material inputs under base, downside and upside stress conditions, validated the package contract, and ran the model-local checks.
3. A production Review Agent, selectively using `gpt-5.6-luna` for the final critical review, challenged the finance mechanics, outputs and test evidence.
4. The Modeler repaired the cited issues and resubmitted the package through the same deterministic gate.
5. A separate manual verification pass reconciled the statements, financing, PP&E, working capital and valuation before this snapshot was accepted.
6. The ad hoc showcase UI operates the accepted package locally. Assumption-only reruns make zero OpenAI calls.

The dashboard is a case-specific presentation layer built separately from the generated package. It does not change the generated model mechanics.

## Run the showcase

Build and start Model Factory, then open:

```text
http://127.0.0.1:<port>/showcase/paint
```

The workspace provides:

- **Input:** grouped editable operating, working-capital, investment, financing and valuation assumptions with package-defined bounds;
- **Model:** the generated Python package tree, source preview and sanitized ZIP download;
- **Output:** linked statements, operating analysis, cash and debt behavior, an exit-multiple FCFF DCF and equity-value sensitivity; and
- **Checks:** current model-local check results, synchronized after every local rerun.

The stored input stress cases support automated package testing. The dashboard executes one complete current input set and does not expose them as user modes.

## Curated evidence

- [`model_package/`](model_package/) is the accepted package used by the showcase; its Python source was mechanically formatted with Black after acceptance and revalidated without changing calculated outputs or checks.
- [`verification_record.md`](verification_record.md) records the manual reconciliation work and remaining limitations.
- [`rerun_evidence.json`](rerun_evidence.json) records an edited-WACC local rerun with changed valuation and zero OpenAI calls.
- [`screenshots/`](screenshots/) contains fresh-browser captures of the accepted Input, Model and Output workspaces.
- The package includes selected deterministic and Review Agent reports, but excludes raw API responses, encrypted reasoning, credentials, traces and private runtime indexes.

## Scope and limitations

This is directional product evidence, not proof that arbitrary generated financial models are always correct. The model is annual, uses synthetic assumptions, excludes covenants and advanced tax accounting, and relies materially on an exit-multiple terminal value. Technical checks passed; business review is still required.
