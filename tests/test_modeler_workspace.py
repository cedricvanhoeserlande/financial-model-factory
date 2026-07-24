from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MODEL_FACTORY_RUNTIME_DIR", str(Path(__file__).resolve().parent / ".tmp" / "test_modeler_workspace"))

from backend.app import model_builder, modeler_workspace
from tests.test_minimal_product_path import (
    stub_base_inputs,
    stub_input_schema,
    stub_package_files,
    stub_scenario_cases,
    stub_model_spec,
)


class ModelerWorkspaceTest(unittest.TestCase):
    def make_session(self, root: Path) -> modeler_workspace.WorkspaceSession:
        (root / "model_tests.json").write_text(
            json.dumps({"model_tests": [{
                "id": "output_blocks_present",
                "label": "Outputs present",
                "test_type": "run_check",
                "execution_scope": "case",
                "purpose": "Verify outputs.",
                "logic_description": "Inspect output blocks.",
                "evidence_expected": "Non-empty blocks.",
                "repair_guidance": "Restore outputs.",
            }]}),
            encoding="utf-8",
        )
        session = model_builder._workspace_session(root, "modeler_package_build", "unit", seed_package=False)
        for item in stub_package_files():
            session.run("write_workspace_artifact", {"path": item["path"], "content": item["content"]})
        session.run("write_workspace_artifact", {"path": "inputs/base_case.json", "content": json.dumps(stub_base_inputs())})
        session.run("write_workspace_artifact", {"path": "inputs/input_schema.json", "content": json.dumps(stub_input_schema())})
        session.run("write_workspace_artifact", {"path": "inputs/scenarios.json", "content": json.dumps({"scenario_cases": stub_scenario_cases()})})
        return session

    def test_path_traversal_binary_size_and_invalid_source_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = self.make_session(root)
            with self.assertRaisesRegex(RuntimeError, "not permitted"):
                session.run("write_workspace_artifact", {"path": "../secret.py", "content": "x = 1"})
            with self.assertRaises((UnicodeEncodeError, RuntimeError)):
                session.run("write_workspace_artifact", {"path": "model/checks.py", "content": "\ud800"})
            with self.assertRaisesRegex(RuntimeError, "1-100000"):
                session.run("write_workspace_artifact", {"path": "model/checks.py", "content": "x" * 100_001})
            before = session.run("read_workspace_artifact", {"path": "model/checks.py"})["content"]
            with self.assertRaises(RuntimeError):
                session.run("write_workspace_artifact", {"path": "model/checks.py", "content": "def broken(:\n"})
            self.assertEqual(session.run("read_workspace_artifact", {"path": "model/checks.py"})["content"], before)

    def test_gate_receipt_is_invalidated_by_an_edit_and_submission_requires_fresh_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(Path(temp))
            gate = session.run("run_workspace_full_gate", {})
            self.assertTrue(gate["passed"], gate)
            session.run("replace_workspace_text", {"path": "model/main.py", "old_text": "def run_model", "new_text": "def run_model"})
            with self.assertRaisesRegex(RuntimeError, "latest passing"):
                session.run("submit_workspace_candidate", {"receipt": gate["receipt"]})
            fresh = session.run("run_workspace_full_gate", {})
            submitted = session.run("submit_workspace_candidate", {"receipt": fresh["receipt"]})
            self.assertTrue(submitted["accepted"])

    def test_canonical_spec_artifacts_are_editable_fingerprinted_and_tests_are_mirrored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            session = self.make_session(root)
            self.assertIn("spec/model_tests.json", session.allowed_paths())
            before = session.fingerprint()
            payload = session.export_spec_artifacts()["spec/model_tests.json"]
            payload["model_tests"][0]["label"] = "Updated authoritative declaration"
            session.run("write_workspace_artifact", {"path": "spec/model_tests.json", "content": json.dumps(payload)})
            self.assertNotEqual(session.fingerprint(), before)
            self.assertEqual(
                json.loads((session.workspace.parent / "model_tests.json").read_text(encoding="utf-8"))["model_tests"][0]["label"],
                "Updated authoritative declaration",
            )

    def test_changed_workspace_model_spec_is_promoted_into_approved_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            approved = {"status": "approved", "path": "model_spec.json", "source_prompt": "Original", "model_spec": stub_model_spec()}
            amended = {**stub_model_spec(), "title": "Amended authoritative specification"}

            promoted = model_builder._promote_workspace_spec_artifacts(
                root,
                {"spec/model_spec.json": amended},
                changed_paths={"spec/model_spec.json"},
                approved_spec=approved,
            )

            saved = model_builder._read_json(root / "model_spec.json")
            self.assertEqual(promoted, ["spec/model_spec.json"])
            self.assertEqual(saved["model_spec"]["title"], "Amended authoritative specification")

    def test_missing_checks_and_declared_test_membership_block_submission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(Path(temp))
            session.run("write_workspace_artifact", {"path": "model/checks.py", "content": "def run_checks(inputs, outputs):\n    return {'checks': []}\n"})
            gate = session.run("run_workspace_full_gate", {})
            self.assertFalse(gate["passed"])
            self.assertIn("checks", json.dumps(gate))
            with self.assertRaisesRegex(RuntimeError, "latest passing"):
                session.run("submit_workspace_candidate", {"receipt": "made-up"})

    def test_scalar_runtime_failure_is_returned_from_authoritative_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(Path(temp))
            source = session.run("read_workspace_artifact", {"path": "model/schedules/core.py"})["content"]
            session.run("write_workspace_artifact", {"path": "model/schedules/core.py", "content": source.replace("primary =", "_bad = inputs['drivers']['primary_value'][0]\n    primary =")})
            with self.assertRaisesRegex(RuntimeError, "not subscriptable"):
                session.run("execute_workspace_model", {"input_overrides": []})

    def test_exact_replace_requires_one_match_and_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session = self.make_session(Path(temp))
            with self.assertRaisesRegex(RuntimeError, "exactly once"):
                session.run("replace_workspace_text", {"path": "model/main.py", "old_text": "missing", "new_text": "x"})

    def test_stateless_api_loop_builds_with_tools_and_returns_no_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "model_tests.json").write_text(
                json.dumps({"model_tests": [{
                    "id": "output_blocks_present", "label": "Outputs", "test_type": "run_check",
                    "execution_scope": "case", "purpose": "Outputs", "logic_description": "Inspect blocks",
                    "evidence_expected": "Blocks", "repair_guidance": "Restore outputs",
                }]}),
                encoding="utf-8",
            )
            writes = [
                {"type": "function_call", "call_id": f"write_{index}", "name": "write_workspace_artifact", "arguments": json.dumps(item)}
                for index, item in enumerate([
                    *stub_package_files(),
                    {"path": "inputs/base_case.json", "content": json.dumps(stub_base_inputs())},
                    {"path": "inputs/input_schema.json", "content": json.dumps(stub_input_schema())},
                    {"path": "inputs/scenarios.json", "content": json.dumps({"scenario_cases": stub_scenario_cases()})},
                ])
            ]
            calls = 0

            def fake_post(_key: str, body: dict) -> dict:
                nonlocal calls
                calls += 1
                usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
                if calls == 1:
                    return {"output": writes, "usage": usage}
                if calls == 2:
                    return {"output": [{"type": "function_call", "call_id": "gate", "name": "run_workspace_full_gate", "arguments": "{}"}], "usage": usage}
                outputs = [item for item in body["input"] if item.get("type") == "function_call_output"]
                if calls == 3:
                    gate = json.loads(outputs[-1]["output"])
                    return {"output": [{"type": "function_call", "call_id": "submit", "name": "submit_workspace_candidate", "arguments": json.dumps({"receipt": gate["receipt"]})}], "usage": usage}
                submit = json.loads(outputs[-1]["output"])
                completion = {"summary": "Passed authoritative execution.", "changed_paths": [], "resolved_issue_ids": [], "gate_receipt": submit["receipt"]}
                return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(completion)}]}], "usage": usage}

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(model_builder, "_post_openai", side_effect=fake_post), patch.object(model_builder, "_record_usage", return_value={"stage": "modeler_package_build", "usage_summary": {}, "cost_summary": {}}):
                package_files, _inputs, _schema, _scenarios, self_check, usage = model_builder._request_workspace_package(
                    "Build a model.", root, stage="modeler_package_build", attempt="test", prompt_id="model_package_build", seed_package=False
                )

            self.assertTrue(self_check["passed"])
            self.assertEqual(self_check["transport"], "workspace_tool_loop")
            self.assertEqual(usage["transport"], "workspace_tool_loop")
            self.assertNotIn("package_files", json.dumps(model_builder._read_json(root / "raw_modeler_workspace_response_modeler_package_build_test.json").get("completion")))
            self.assertEqual({item["path"] for item in package_files}, {item["path"] for item in stub_package_files()})

    def test_stage_turn_limit_stops_nonconverging_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = {"output": [{"type": "function_call", "call_id": "list", "name": "list_workspace_artifacts", "arguments": "{}"}], "usage": {}}
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch.object(model_builder, "_post_openai", return_value=raw), patch.object(model_builder, "_modeler_loop_limits", return_value={"stage_turns": 1, "total_turns": 32, "total_tools": 80, "wall_seconds": 2700}):
                with self.assertRaisesRegex(RuntimeError, "exhausted 1 API turns"):
                    model_builder._request_workspace_package(
                        "Build.", root, stage="modeler_package_build", attempt="limit", prompt_id="model_package_build", seed_package=False
                    )

    def test_multi_turn_usage_transport_is_not_double_counted(self) -> None:
        combined: dict = {}
        for index in range(3):
            combined = model_builder._combine_openai_usage(combined, {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "_transport": {
                    "started_utc": f"start-{index}",
                    "completed_utc": f"end-{index}",
                    "duration_seconds": 1.5,
                    "attempt_count": 1,
                    "retry_count": 0,
                },
            })
        self.assertEqual(combined["input_tokens"], 30)
        self.assertEqual(combined["_transport"]["attempt_count"], 3)
        self.assertEqual(combined["_transport"]["duration_seconds"], 4.5)
        self.assertEqual(len(combined["_transports"]), 3)

    def test_atomic_package_write_preserves_canonical_package_on_staging_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {"model_id": "model_test", "current_version_id": "version_test"}
            model_builder.write_package(
                root, manifest, "Build.", stub_base_inputs(), stub_input_schema(), stub_scenario_cases(),
                stub_package_files(main_py=stub_package_files()[0]["content"] + "\n# canonical\n"),
                {"passed": True}, {}, approved_spec=None,
            )
            canonical = (root / "model_package" / "model" / "main.py").read_text(encoding="utf-8")
            invalid_schema = stub_input_schema()
            invalid_schema["fields"] = []
            with self.assertRaises(RuntimeError):
                model_builder.write_package(
                    root, manifest, "Broken.", stub_base_inputs(), invalid_schema, stub_scenario_cases(),
                    stub_package_files(), {"passed": True}, {}, approved_spec=None,
                )
            self.assertEqual((root / "model_package" / "model" / "main.py").read_text(encoding="utf-8"), canonical)


if __name__ == "__main__":
    unittest.main()
