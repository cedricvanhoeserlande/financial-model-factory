from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any


EXECUTION_TIMEOUT_SECONDS = 5
REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_IMPORT_ROOTS = {
    "__future__",
    "_collections_abc",
    "_io",
    "_weakref",
    "_weakrefset",
    "abc",
    "collections",
    "contextlib",
    "copy",
    "decimal",
    "functools",
    "itertools",
    "math",
    "model",
    "operator",
    "re",
    "statistics",
    "types",
    "typing",
    "warnings",
    "weakref",
}
BLOCKED_CALL_NAMES = {"eval", "exec", "open", "input", "__import__", "compile", "breakpoint"}


def execute_package(package_dir: Path, input_params: dict[str, Any]) -> dict[str, Any]:
    main_path = package_dir / "model" / "main.py"
    if not main_path.exists():
        raise RuntimeError("Generated package missing model/main.py.")
    for source_path in sorted((package_dir / "model").rglob("*.py")):
        _validate_generated_source(source_path)
    raw_output = _execute_model_file(main_path, package_dir, input_params)
    if not isinstance(raw_output, dict):
        raise RuntimeError("Generated package must return an output data dictionary.")
    return raw_output


def execute_package_checks(package_dir: Path, input_params: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    main_path = package_dir / "model" / "main.py"
    checks_path = package_dir / "model" / "checks.py"
    if not main_path.exists():
        raise RuntimeError("Generated package missing model/main.py.")
    if not checks_path.exists():
        raise RuntimeError("Generated package missing model/checks.py.")
    for source_path in sorted((package_dir / "model").rglob("*.py")):
        _validate_generated_source(source_path)
    raw_report = _execute_model_tests_file(
        checks_path,
        package_dir,
        function_name="run_checks",
        payload={"inputs": input_params, "output": output},
    )
    if not isinstance(raw_report, dict):
        raise RuntimeError("Generated package checks must return a dictionary.")
    return raw_report


def execute_package_suite_checks(package_dir: Path, cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    checks_path = package_dir / "model" / "checks.py"
    if not checks_path.exists():
        raise RuntimeError("Generated package missing model/checks.py.")
    for source_path in sorted((package_dir / "model").rglob("*.py")):
        _validate_generated_source(source_path)
    raw_report = _execute_model_tests_file(
        checks_path,
        package_dir,
        function_name="run_suite_checks",
        payload={"cases": cases},
    )
    if not isinstance(raw_report, dict):
        raise RuntimeError("Generated package suite checks must return a dictionary.")
    return raw_report


def _execute_model_file(main_path: Path, import_root: Path, input_params: dict[str, Any]) -> Any:
    _validate_generated_source(main_path)
    runner = textwrap.dedent(
        """
        import builtins
        import importlib.util
        import json
        import sys
        from pathlib import Path

        ALLOWED_IMPORT_ROOTS = {
            "__future__",
            "_collections_abc",
            "_io",
            "_weakref",
            "_weakrefset",
            "abc",
            "collections",
            "contextlib",
            "copy",
            "decimal",
            "functools",
            "itertools",
            "math",
            "model",
            "operator",
            "re",
            "statistics",
            "types",
            "typing",
            "warnings",
            "weakref",
        }
        TYPING_DEP_IMPORT_ROOTS = {"_typing", "copyreg", "sys"}
        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                caller = globals.get("__name__", "") if isinstance(globals, dict) else ""
                if caller == "typing" and root in TYPING_DEP_IMPORT_ROOTS:
                    return real_import(name, globals, locals, fromlist, level)
                if caller and caller != "generated_model_sandbox":
                    return real_import(name, globals, locals, fromlist, level)
                raise RuntimeError(f"Import not allowed in generated package: {name}")
            return real_import(name, globals, locals, fromlist, level)

        def blocked_open(*args, **kwargs):
            raise RuntimeError("File access is not allowed in generated package execution.")

        builtins.__import__ = guarded_import
        builtins.open = blocked_open
        builtins.input = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Input is not allowed in generated package execution."))

        main_path = Path(sys.argv[1]).resolve()
        import_root = Path(sys.argv[2]).resolve()
        input_params = json.loads(sys.stdin.read())
        sys.path.insert(0, str(import_root))
        spec = importlib.util.spec_from_file_location("model.main", main_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Generated package main.py could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        run_model = getattr(module, "run_model", None)
        if not callable(run_model):
            raise RuntimeError("Generated package must expose run_model(inputs).")
        print(json.dumps(run_model(input_params)))
        """
    )
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    command = [sys.executable, "-I", "-S"]
    pycache_prefix = os.environ.get("PYTHONPYCACHEPREFIX")
    if pycache_prefix:
        command.extend(["-X", f"pycache_prefix={str((REPO_ROOT / pycache_prefix).resolve())}"])
    command.extend(["-c", runner, str(main_path.resolve()), str(import_root.resolve())])
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(input_params),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=env,
            timeout=EXECUTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Generated package execution timed out after {EXECUTION_TIMEOUT_SECONDS}s.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Unknown generated package execution error.").strip()
        raise RuntimeError(f"Generated package execution failed in sandbox: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Generated package did not return valid JSON from sandbox.") from exc


def _execute_model_tests_file(
    checks_path: Path,
    import_root: Path,
    *,
    function_name: str,
    payload: dict[str, Any],
) -> Any:
    _validate_generated_source(checks_path)
    runner = textwrap.dedent(
        """
        import builtins
        import importlib.util
        import json
        import sys
        from pathlib import Path

        ALLOWED_IMPORT_ROOTS = {
            "__future__",
            "_collections_abc",
            "_io",
            "_weakref",
            "_weakrefset",
            "abc",
            "collections",
            "contextlib",
            "copy",
            "decimal",
            "functools",
            "itertools",
            "math",
            "model",
            "operator",
            "re",
            "statistics",
            "types",
            "typing",
            "warnings",
            "weakref",
        }
        TYPING_DEP_IMPORT_ROOTS = {"_typing", "copyreg", "sys"}
        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            root = name.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                caller = globals.get("__name__", "") if isinstance(globals, dict) else ""
                if caller == "typing" and root in TYPING_DEP_IMPORT_ROOTS:
                    return real_import(name, globals, locals, fromlist, level)
                if caller and caller != "generated_model_sandbox":
                    return real_import(name, globals, locals, fromlist, level)
                raise RuntimeError(f"Import not allowed in generated package: {name}")
            return real_import(name, globals, locals, fromlist, level)

        def blocked_open(*args, **kwargs):
            raise RuntimeError("File access is not allowed in generated package execution.")

        builtins.__import__ = guarded_import
        builtins.open = blocked_open
        builtins.input = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Input is not allowed in generated package execution."))

        checks_path = Path(sys.argv[1]).resolve()
        import_root = Path(sys.argv[2]).resolve()
        payload = json.loads(sys.stdin.read())
        function_name = sys.argv[3]
        sys.path.insert(0, str(import_root))
        spec = importlib.util.spec_from_file_location("model.checks", checks_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Generated package checks.py could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check_function = getattr(module, function_name, None)
        if not callable(check_function):
            if function_name == "run_suite_checks":
                raise RuntimeError("Generated package model/checks.py must expose run_suite_checks(cases) for scenario-suite tests.")
            raise RuntimeError("Generated package model/checks.py must expose run_checks(inputs, outputs).")
        if function_name == "run_suite_checks":
            result = check_function(payload["cases"])
        else:
            result = check_function(payload["inputs"], payload["output"])
        print(json.dumps(result))
        """
    )
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    command = [sys.executable, "-I", "-S"]
    pycache_prefix = os.environ.get("PYTHONPYCACHEPREFIX")
    if pycache_prefix:
        command.extend(["-X", f"pycache_prefix={str((REPO_ROOT / pycache_prefix).resolve())}"])
    command.extend(["-c", runner, str(checks_path.resolve()), str(import_root.resolve()), function_name])
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=env,
            timeout=EXECUTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Generated package check execution timed out after {EXECUTION_TIMEOUT_SECONDS}s.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Unknown generated package check execution error.").strip()
        raise RuntimeError(f"Generated package check execution failed in sandbox: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Generated package checks did not return valid JSON from sandbox.") from exc


def _validate_generated_source(source_path: Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        raise RuntimeError(f"Generated package source has invalid syntax in {source_path.name}: {exc}") from exc
    hidden_state = _top_level_state_errors(tree, source_path.name)
    if hidden_state:
        raise RuntimeError("; ".join(hidden_state))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module] if node.module else [])
            blocked = sorted({name for name in imports if name and name.split(".")[0] not in ALLOWED_IMPORT_ROOTS})
            if blocked:
                raise RuntimeError(f"Blocked import in generated package: {', '.join(blocked)}")
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in BLOCKED_CALL_NAMES:
                raise RuntimeError(f"Blocked call in generated package: {name}")


def _top_level_state_errors(tree: ast.Module, filename: str) -> list[str]:
    errors: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Global, ast.Nonlocal)):
            errors.append(f"Generated package must not define hidden module-level state in {filename}.")
            continue
        if isinstance(node, ast.Pass):
            continue
        errors.append(f"Generated package must not execute module-level code in {filename}.")
    return errors

