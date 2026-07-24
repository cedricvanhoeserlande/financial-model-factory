# `backend/app` Module Map

Naming rule: files that start with `model_` own Model Factory model-workflow behavior or model-package state; files without that prefix are generic app infrastructure, runtime execution, configuration, or HTTP serving.

- `__init__.py`: Marks `backend.app` as the local backend application package.
- `model_builder.py`: Builds, writes, validates, publishes, and reruns generated Python model packages.
- `model_config.py`: Resolves configured OpenAI model choices for backend roles and stages.
- `model_context.py`: Holds shared runtime paths, constants, filesystem helpers, timestamps, and cross-module imports for model workflow modules.
- `model_conversations.py`: Persists and serves Input Agent and Review Agent chat state, scope summaries, and backend OpenAI chat calls.
- `model_lifecycle.py`: Creates, opens, renames, deletes, builds, and publishes model records.
- `model_loop.py`: Exposes the stable public compatibility facade imported by the server and tests.
- `model_registry.py`: Owns local model manifests, model indexes, publish state, and model id validation.
- `model_runs.py`: Reads artifacts and executes regular-mode reruns from saved published model packages.
- `model_spec.py`: Generates, stores, approves, and exposes Modeler-owned model specifications before package build.
- `model_usage.py`: Reports OpenAI configuration status and records token/cost usage ledgers.
- `model_workspace.py`: Builds frontend workspace payloads, workflow state, input review summaries, and model-list summaries.
- `package_runtime.py`: Executes generated model package code in a restricted local Python runtime.
- `server.py`: Serves the local HTTP API and static frontend build.
