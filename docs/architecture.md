# Architecture

## Implemented product boundary

Model Factory is a local Python financial-modelling workspace with a React
frontend. Its demonstrated path is:

```text
finance request -> structured specification -> isolated model workspace
-> generated model package -> deterministic gate -> separate review
-> bounded repair -> human publish decision -> local rerun
```

The application does not contain a deterministic catalogue of finance-model
templates. Finance schedules, equations, model-local checks, and package files
are model-specific artifacts proposed by the Modeler and admitted only after
backend validation.

## Components

| Component | Responsibility | Boundary |
| --- | --- | --- |
| `frontend/` | Development workspace and curated showcase UI | Never calls OpenAI directly |
| `backend/app/server.py` | Local HTTP server and routes | Receives browser requests |
| `backend/app/model_loop.py` | Workflow/lifecycle facade | Coordinates stages and persisted state |
| `backend/app/modeler_workspace.py` | Restricted workspace tools | Permitted package files, reads, writes, executions, validation receipts |
| `backend/app/model_builder.py` | Structured request/response contracts and repair orchestration | Does not embed a finance-model template |
| `backend/app/package_runtime.py` | Executes a saved package and its checks | Deterministic local execution |
| `backend/output/` | Output/dashboard contract validation | Structural presentation contract only |
| `examples/` | Curated, synthetic recorded evidence | No raw API responses, credentials, or runtime indexes |

## Authoritative workspace Modeler

Earlier prototype iterations exchanged full package source as a response object.
The current Modeler transport instead starts from a finance-neutral package
skeleton in an isolated workspace. The Modeler can list, read, write, replace,
execute, and validate only permitted artifacts. Parser, runtime, and contract
failures are returned as tool results so a targeted correction can be made in
the same workspace.

A package is eligible for promotion only when a fresh full-gate receipt matches
the workspace fingerprint. Any later edit invalidates the receipt. This makes
the backend's actual files and actual execution authoritative; it does not make
the financial content automatically correct.

## API boundary

OpenAI requests, when enabled, originate only in the Python backend. The
frontend does not receive or store API credentials. The committed showcase and
normal deterministic tests run without OpenAI.

## Curated showcase

`/showcase/paint` runs the accepted synthetic package under
`examples/paint_showcase/model_package`. It exposes grouped inputs, Python
source preview/download, statements, outputs, and synchronized model-local
checks. The dashboard is a curated demonstration layer, separate from the
generated model package.
