from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable


MAX_ARTIFACT_BYTES = 100_000
REQUIRED_PYTHON_PATHS = {
    "model/main.py",
    "model/assumptions.py",
    "model/schedules/__init__.py",
    "model/outputs.py",
    "model/checks.py",
}
JSON_PATHS = {
    "inputs/base_case.json",
    "inputs/input_schema.json",
    "inputs/scenarios.json",
}
OPTIONAL_SPEC_JSON_PATHS = {
    "spec/model_spec.json",
    "spec/model_thesis.json",
    "spec/equation_graph.json",
    "spec/model_tests.json",
}


def workspace_tool_definitions() -> list[dict[str, Any]]:
    string = {"type": "string"}
    return [
        {
            "type": "function",
            "name": "list_workspace_artifacts",
            "description": "List the generated-model artifacts in the authoritative workspace.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "read_workspace_artifact",
            "description": "Read one permitted authoritative workspace artifact.",
            "parameters": {"type": "object", "properties": {"path": string}, "required": ["path"], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "write_workspace_artifact",
            "description": "Atomically replace one permitted Python or JSON artifact. Invalid Python/JSON is rejected without changing the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": string, "content": string},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "replace_workspace_text",
            "description": "Replace one exact, unique text fragment in a permitted artifact. The resulting artifact must remain valid.",
            "parameters": {
                "type": "object",
                "properties": {"path": string, "old_text": string, "new_text": string},
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "execute_workspace_model",
            "description": "Execute the authoritative workspace model using saved base inputs plus optional dotted-path overrides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_overrides": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": string,
                                "value": {
                                    "anyOf": [
                                        {"type": "number"},
                                        {"type": "string"},
                                        {"type": "boolean"},
                                        {"type": "array", "items": {"type": "number"}},
                                    ]
                                },
                            },
                            "required": ["path", "value"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["input_overrides"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "run_workspace_preflight",
            "description": "Run required-file, Python-source, JSON, schema, import, startup, and base execution checks.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "run_workspace_full_gate",
            "description": "Run the complete production Base/Downside/Upside, output-contract, mechanical-stress, and declared model-test gates. A pass creates a fingerprint-bound receipt.",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "submit_workspace_candidate",
            "description": "Submit the candidate using the current passing full-gate receipt. This never bypasses backend validation.",
            "parameters": {
                "type": "object",
                "properties": {"receipt": string},
                "required": ["receipt"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


class WorkspaceSession:
    def __init__(
        self,
        workspace: Path,
        *,
        validate_source: Callable[[Path], None],
        validate_input_schema: Callable[[Any, dict[str, Any]], dict[str, Any]],
        parse_scenarios: Callable[[Any], list[dict[str, Any]]],
        validate_package: Callable[[Path, dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]],
        run_stress: Callable[[Path], dict[str, Any]],
        run_tests: Callable[[Path, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]],
        execute_package: Callable[[Path, dict[str, Any]], dict[str, Any]],
        set_path: Callable[[dict[str, Any], str, Any], None],
    ) -> None:
        self.workspace = workspace.resolve()
        self.validate_source = validate_source
        self.validate_input_schema = validate_input_schema
        self.parse_scenarios = parse_scenarios
        self.validate_package = validate_package
        self.run_stress = run_stress
        self.run_tests = run_tests
        self.execute_package = execute_package
        self.set_path = set_path
        self.revision = 0
        self.last_receipt = ""
        self.last_gate: dict[str, Any] = {}
        self.submitted = False
        self.changed_paths: set[str] = set()
        self.tool_calls = 0
        self._last_failure_signature = ""
        self._last_failure_revision = -1
        self._same_failure_without_edit = 0

    def initialize_fresh(self) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        skeleton = {
            "model/__init__.py": "",
            "model/main.py": "from model.assumptions import load_inputs\nfrom model.schedules import run_all\nfrom model.outputs import build_output\n\n\ndef run_model(inputs):\n    clean = load_inputs(inputs)\n    return build_output(clean, run_all(clean))\n",
            "model/assumptions.py": "def load_inputs(inputs):\n    if not isinstance(inputs, dict):\n        raise ValueError('inputs must be an object')\n    return dict(inputs)\n",
            "model/schedules/__init__.py": "def run_all(inputs):\n    return {}\n",
            "model/outputs.py": "def build_output(inputs, schedules):\n    return {'output_version': '2026-05-25', 'output_blocks': [], 'dashboard_spec': {}, 'metadata': {'openai_called': False}}\n",
            "model/checks.py": "def run_checks(inputs, outputs):\n    return {'checks': []}\n",
            "inputs/base_case.json": "{}\n",
            "inputs/input_schema.json": "{\"type\":\"object\",\"groups\":[],\"fields\":[]}\n",
            "inputs/scenarios.json": "{\"scenario_cases\":[]}\n",
        }
        for relative, content in skeleton.items():
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def initialize_from_package(self, package_dir: Path) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        for source in sorted((package_dir / "model").rglob("*.py")):
            relative = source.relative_to(package_dir)
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for name in ("base_case.json", "input_schema.json", "scenarios.json"):
            source = package_dir / "inputs" / name
            target = self.workspace / "inputs" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if (package_dir / "spec").exists():
            shutil.copytree(package_dir / "spec", self.workspace / "spec", dirs_exist_ok=True)

    def allowed_paths(self) -> list[str]:
        paths = set(REQUIRED_PYTHON_PATHS | JSON_PATHS)
        for relative in OPTIONAL_SPEC_JSON_PATHS:
            target = self.workspace / relative
            if target.is_file() and not target.is_symlink():
                paths.add(relative)
        schedules = self.workspace / "model" / "schedules"
        if schedules.exists():
            for item in schedules.glob("*.py"):
                if item.is_file() and not item.is_symlink():
                    paths.add(item.relative_to(self.workspace).as_posix())
        return sorted(paths)

    def fingerprint(self) -> str:
        digest = hashlib.sha256()
        for relative in self.allowed_paths():
            target = self._target(relative, must_exist=True)
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(target.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def run(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.tool_calls += 1
        if name == "list_workspace_artifacts":
            self._args(args, set(), set())
            return {"ok": True, "artifacts": [{"path": path, "bytes": self._target(path, must_exist=True).stat().st_size} for path in self.allowed_paths()]}
        if name == "read_workspace_artifact":
            self._args(args, {"path"}, {"path"})
            path = str(args["path"])
            target = self._target(path, must_exist=True)
            return {"ok": True, "path": path, "content": target.read_text(encoding="utf-8"), "revision": self.revision}
        if name == "write_workspace_artifact":
            self._args(args, {"path", "content"}, {"path", "content"})
            return self._write(str(args["path"]), str(args["content"]))
        if name == "replace_workspace_text":
            self._args(args, {"path", "old_text", "new_text"}, {"path", "old_text", "new_text"})
            path = str(args["path"])
            target = self._target(path, must_exist=True)
            current = target.read_text(encoding="utf-8")
            old = str(args["old_text"])
            count = current.count(old)
            if not old or count != 1:
                raise RuntimeError(f"old_text must match exactly once; matched {count} time(s).")
            return self._write(path, current.replace(old, str(args["new_text"]), 1))
        if name == "execute_workspace_model":
            self._args(args, {"input_overrides"}, {"input_overrides"})
            inputs = self._json("inputs/base_case.json")
            overrides = args["input_overrides"]
            if not isinstance(overrides, list):
                raise RuntimeError("input_overrides must be an array of path/value objects.")
            for override in overrides:
                if not isinstance(override, dict) or set(override) != {"path", "value"}:
                    raise RuntimeError("Each input override must contain exactly path and value.")
                self.set_path(inputs, str(override["path"]), override["value"])
            output = self.execute_package(self.workspace, inputs)
            return {"ok": True, "workspace_fingerprint": self.fingerprint(), "output": output}
        if name == "run_workspace_preflight":
            self._args(args, set(), set())
            return self._preflight(include_output=False)
        if name == "run_workspace_full_gate":
            self._args(args, set(), set())
            return self._full_gate()
        if name == "submit_workspace_candidate":
            self._args(args, {"receipt"}, {"receipt"})
            receipt = str(args["receipt"])
            current = self.fingerprint()
            if not receipt or receipt != self.last_receipt or self.last_gate.get("passed") is not True:
                raise RuntimeError("Submission requires the latest passing full-gate receipt.")
            if self.last_gate.get("workspace_fingerprint") != current:
                raise RuntimeError("Workspace changed after the passing full gate; rerun it before submission.")
            self.submitted = True
            return {"ok": True, "accepted": True, "receipt": receipt, "workspace_fingerprint": current}
        raise RuntimeError(f"Unknown Modeler workspace tool: {name}")

    def export(self) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        if not self.submitted:
            raise RuntimeError("Authoritative workspace was not submitted.")
        files = []
        for relative in self.allowed_paths():
            if relative.startswith("model/"):
                files.append({"path": relative, "content": self._target(relative, must_exist=True).read_text(encoding="utf-8")})
        scenarios_payload = self._json("inputs/scenarios.json")
        scenarios = scenarios_payload.get("scenario_cases") if isinstance(scenarios_payload, dict) else None
        if not isinstance(scenarios, list):
            raise RuntimeError("inputs/scenarios.json must contain scenario_cases.")
        return files, self._json("inputs/base_case.json"), self._json("inputs/input_schema.json"), scenarios

    def export_spec_artifacts(self) -> dict[str, dict[str, Any]]:
        return {
            relative: self._json(relative)
            for relative in sorted(OPTIONAL_SPEC_JSON_PATHS)
            if (self.workspace / relative).is_file()
        }

    def _write(self, path: str, content: str) -> dict[str, Any]:
        encoded = content.encode("utf-8")
        if not content.strip() or len(encoded) > MAX_ARTIFACT_BYTES:
            raise RuntimeError(f"Artifact must contain 1-{MAX_ARTIFACT_BYTES} UTF-8 bytes.")
        target = self._target(path, must_exist=False)
        if path.endswith(".json"):
            json.loads(content)
        else:
            temp = target.with_name(target.name + ".validation.tmp")
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(content, encoding="utf-8")
            try:
                self.validate_source(temp)
            finally:
                temp.unlink(missing_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(target.name + ".write.tmp")
        temp_target.write_text(content, encoding="utf-8")
        temp_target.replace(target)
        if path == "spec/model_tests.json":
            mirror = self.workspace.parent / "model_tests.json"
            mirror.write_text(content, encoding="utf-8")
        self.revision += 1
        self.changed_paths.add(path)
        self.last_receipt = ""
        self.last_gate = {}
        return {"ok": True, "path": path, "bytes": len(encoded), "revision": self.revision, "workspace_fingerprint": self.fingerprint()}

    def _preflight(self, *, include_output: bool) -> dict[str, Any]:
        try:
            missing = [path for path in REQUIRED_PYTHON_PATHS | JSON_PATHS if not self._target(path, must_exist=False).exists()]
            schedule_files = [path for path in self.allowed_paths() if path.startswith("model/schedules/") and path != "model/schedules/__init__.py"]
            if missing:
                raise RuntimeError("Missing required workspace artifacts: " + ", ".join(sorted(missing)))
            if not schedule_files:
                raise RuntimeError("At least one model/schedules/<name>.py artifact is required.")
            for path in self.allowed_paths():
                target = self._target(path, must_exist=True)
                if path.endswith(".py"):
                    self.validate_source(target)
            inputs = self._json("inputs/base_case.json")
            self.validate_input_schema(self._json("inputs/input_schema.json"), inputs)
            scenarios_payload = self._json("inputs/scenarios.json")
            self.parse_scenarios(scenarios_payload.get("scenario_cases") if isinstance(scenarios_payload, dict) else None)
            validation, output = self.validate_package(self.workspace, inputs)
            result = {
                "ok": True,
                "passed": validation.get("passed") is True,
                "workspace_fingerprint": self.fingerprint(),
                "validation_report": validation,
                "output_summary": {
                    "output_version": output.get("output_version") if isinstance(output, dict) else None,
                    "block_count": len(output.get("output_blocks") or []) if isinstance(output, dict) else 0,
                    "block_ids": [item.get("id") for item in (output.get("output_blocks") or []) if isinstance(item, dict)] if isinstance(output, dict) else [],
                },
            }
            if include_output:
                result["output"] = output
            return result
        except Exception as exc:
            return {"ok": True, "passed": False, "workspace_fingerprint": self._safe_fingerprint(), "error": str(exc)}

    def _full_gate(self) -> dict[str, Any]:
        fingerprint = self._safe_fingerprint()
        try:
            preflight = self._preflight(include_output=True)
            if preflight.get("passed") is not True:
                raise RuntimeError(str(preflight.get("error") or preflight.get("validation_report") or "Preflight failed."))
            inputs = self._json("inputs/base_case.json")
            validation = preflight["validation_report"]
            output = preflight["output"]
            stress = self.run_stress(self.workspace)
            tests = self.run_tests(self.workspace, output, stress, inputs)
            passed = validation.get("passed") is True and stress.get("passed") is True and tests.get("passed") is True
            result = {
                "ok": True,
                "passed": passed,
                "workspace_fingerprint": fingerprint,
                "validation_report": validation,
                "mechanical_stress_report": stress,
                "model_tests_report": tests,
            }
            if not passed:
                result["failure_reasons"] = self._failure_reasons(validation, stress, tests)
                self._record_failure(result)
                return result
            receipt = hashlib.sha256(f"{fingerprint}:{self.revision}:{time.time_ns()}".encode("utf-8")).hexdigest()
            result["receipt"] = receipt
            self.last_receipt = receipt
            self.last_gate = dict(result)
            self._same_failure_without_edit = 0
            return result
        except Exception as exc:
            result = {"ok": True, "passed": False, "workspace_fingerprint": fingerprint, "error": str(exc)}
            self._record_failure(result)
            return result

    def _record_failure(self, result: dict[str, Any]) -> None:
        signature = hashlib.sha256(json.dumps({"error": result.get("error"), "failure_reasons": result.get("failure_reasons")}, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        if signature == self._last_failure_signature and self.revision == self._last_failure_revision:
            self._same_failure_without_edit += 1
        else:
            self._same_failure_without_edit = 1
        self._last_failure_signature = signature
        self._last_failure_revision = self.revision
        if self._same_failure_without_edit >= 2:
            raise RuntimeError("The same deterministic failure was repeated twice without a relevant workspace edit.")

    def _target(self, relative: str, *, must_exist: bool) -> Path:
        normalized = relative.replace("\\", "/").strip()
        parts = Path(normalized).parts
        allowed = normalized in REQUIRED_PYTHON_PATHS or normalized in JSON_PATHS or normalized in OPTIONAL_SPEC_JSON_PATHS or (
            normalized.startswith("model/schedules/")
            and normalized.endswith(".py")
            and len(parts) == 3
            and parts[-1] not in {"", ".", ".."}
        )
        if not allowed or Path(normalized).is_absolute() or ".." in parts:
            raise RuntimeError(f"Workspace artifact path is not permitted: {relative}")
        target = (self.workspace / normalized).resolve()
        try:
            target.relative_to(self.workspace)
        except ValueError as exc:
            raise RuntimeError(f"Workspace artifact escapes the isolated workspace: {relative}") from exc
        if target.exists() and target.is_symlink():
            raise RuntimeError("Workspace symlinks are not permitted.")
        if must_exist and (not target.exists() or not target.is_file()):
            raise RuntimeError(f"Workspace artifact does not exist: {relative}")
        return target

    def _json(self, relative: str) -> dict[str, Any]:
        value = json.loads(self._target(relative, must_exist=True).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"{relative} must contain a JSON object.")
        return value

    def _safe_fingerprint(self) -> str:
        try:
            return self.fingerprint()
        except Exception:
            return ""

    @staticmethod
    def _args(args: dict[str, Any], allowed: set[str], required: set[str]) -> None:
        if not isinstance(args, dict) or set(args) - allowed or required - set(args):
            raise RuntimeError(f"Invalid tool arguments; allowed={sorted(allowed)}, required={sorted(required)}")

    @staticmethod
    def _failure_reasons(validation: dict[str, Any], stress: dict[str, Any], tests: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        for report in (validation, stress, tests):
            reasons.extend(str(item) for item in report.get("failure_reasons") or [])
            if report.get("passed") is not True and report.get("message"):
                reasons.append(str(report["message"]))
            for check in report.get("checks") or []:
                if isinstance(check, dict) and check.get("passed") is not True:
                    reasons.append(f"{check.get('id')}: {check.get('message') or check.get('error') or 'failed'}")
        return list(dict.fromkeys(reasons)) or ["One or more deterministic gates failed."]
