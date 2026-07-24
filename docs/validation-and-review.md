# Validation and review

Model Factory separates several kinds of evidence.

| Layer | Examples | What it establishes |
| --- | --- | --- |
| Structural validation | required files, schema validity, imports, required interfaces | The package conforms to the technical contract |
| Execution validation | saved inputs run; invalid inputs fail clearly; deterministic rerun | The code executes in the package runtime |
| Mechanical financial checks | balance sheet, cash/debt/PP&E/retained-earnings roll-forwards, bridge checks | Implemented identities and invariants reconcile |
| Input stress testing | Material driver changes and targeted branch probes | Defined stress cases execute and behave according to claimed checks |
| Separate AI review | artifact reads, executions, evidence citations, bounded amendments | An additional role has challenged the package |

The Review Agent has a distinct prompt and evidence set from the Modeler. It is
expected to inspect outputs and packaged tests, distinguish defects from
disclosed limitations, and issue evidence-cited findings. Findings can route
back to a bounded Modeler repair loop.

Neither mechanical checks nor AI review is an audit, an investment opinion, or
proof of economic correctness. Passing technical checks means implemented
checks passed; professional human review remains mandatory.
