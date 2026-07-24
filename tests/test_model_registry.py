from __future__ import annotations

import importlib
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "tests" / ".tmp_model_registry_runtime"


class ModelRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)
        self.previous_runtime_dir = os.environ.get("MODEL_FACTORY_RUNTIME_DIR")
        os.environ["MODEL_FACTORY_RUNTIME_DIR"] = str(RUNTIME_DIR)
        from backend.app import model_loop, model_registry

        self.model_registry = importlib.reload(model_registry)
        self.model_loop = importlib.reload(model_loop)

    def tearDown(self) -> None:
        if self.previous_runtime_dir is None:
            os.environ.pop("MODEL_FACTORY_RUNTIME_DIR", None)
        else:
            os.environ["MODEL_FACTORY_RUNTIME_DIR"] = self.previous_runtime_dir
        importlib.reload(self.model_registry)
        importlib.reload(self.model_loop)
        if RUNTIME_DIR.exists():
            shutil.rmtree(RUNTIME_DIR)

    def test_model_create_and_generated_package_build_path_only(self) -> None:
        initial = self.model_loop.list_models_payload()
        self.assertEqual(initial["account"]["account_id"], "local_default")
        self.assertEqual(initial["models"], [])

        created = self.model_loop.create_model_record(
            "Riva Beverages",
            "Five-year operating model for a local beverage retailer.",
        )
        model_id = created["model_manifest"]["model_id"]
        manifest_path = RUNTIME_DIR / "models" / model_id / "model_manifest.json"
        self.assertTrue(manifest_path.exists())
        self.assertEqual(created["model_manifest"]["status"], "draft")
        self.assertFalse(created["model_manifest"]["scope_approved"])
        self.assertFalse(created["model_manifest"]["publish_eligible"])
        self.assertEqual(created["workspace"]["selected_model"]["model_id"], model_id)
        self.assertTrue(created["workspace"]["action_state"]["can_rebuild"])
        self.assertEqual(created["workspace"]["action_state"]["rebuild_reason"], "")

        persisted = self.model_loop.list_models_payload()["models"]
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0]["name"], "Riva Beverages")

        self.assertFalse(hasattr(self.model_loop, "build_model"))

        with self.assertRaisesRegex(RuntimeError, "generated package versions"):
            self.model_loop.publish_model_record(model_id)

    def test_delete_model_removes_manifest_and_index_entry(self) -> None:
        created = self.model_loop.create_model_record("Delete Me", "Temporary model.")
        model_id = created["model_manifest"]["model_id"]
        self.model_loop.read_input_agent_conversation(model_id, mutate=True)
        version_id = self.model_registry.read_model(model_id)["current_version_id"]
        manifest_path = RUNTIME_DIR / "models" / model_id / "model_manifest.json"
        version_path = RUNTIME_DIR / "artifacts" / "model_versions" / model_id / version_id
        self.assertTrue(manifest_path.exists())
        self.assertTrue(version_path.exists())

        deleted = self.model_loop.delete_model_record(model_id)
        self.assertEqual(deleted["models"], [])
        self.assertFalse(manifest_path.exists())
        self.assertFalse(version_path.exists())
        with self.assertRaisesRegex(RuntimeError, "Model not found"):
            self.model_loop.delete_model_record(model_id)

    def test_stale_published_manifest_is_not_listed_as_published(self) -> None:
        created = self.model_loop.create_model_record("Stale Published", "Temporary model.")
        model_id = created["model_manifest"]["model_id"]
        manifest = self.model_registry.read_model(model_id)
        manifest.update(
            {
                "status": "published",
                "current_version_id": "version_20260515_000000_missing",
                "canonical_version_id": "version_20260515_000000_missing",
                "current_build_id": "version_20260515_000000_missing",
                "latest_run_id": "version_20260515_000000_missing",
                "current_version_state": "published",
                "latest_validation_state": "passed",
                "latest_stress_state": "passed",
            }
        )
        self.model_registry.save_model(manifest)

        listed = self.model_loop.list_models_payload()["models"]

        self.assertEqual(listed[0]["model_id"], model_id)
        self.assertEqual(listed[0]["status"], "draft")
        self.assertEqual(listed[0]["current_version_state"], "artifact_missing")
        self.assertFalse(listed[0]["publish_eligible"])
        self.assertIn("missing", listed[0]["publish_blocker"].lower())

    def test_invalid_model_ids_are_rejected_before_path_use(self) -> None:
        for model_id in ("../secret", "nested/model", "nested\\model", "C:\\temp\\model", ""):
            with self.subTest(model_id=model_id):
                with self.assertRaises(ValueError):
                    self.model_registry.read_model(model_id)

    def test_workspace_read_does_not_create_conversation_artifacts(self) -> None:
        created = self.model_loop.create_model_record("Read Only Workspace", "Temporary model.")
        model_id = created["model_manifest"]["model_id"]
        manifest = self.model_registry.read_model(model_id)
        self.assertIsNone(manifest["current_version_id"])

        workspace = self.model_loop.build_workspace_payload(model_id)

        self.assertEqual(workspace["selected_model"]["model_id"], model_id)
        reread = self.model_registry.read_model(model_id)
        self.assertIsNone(reread["current_version_id"])

    def test_workspace_without_model_id_uses_latest_model_not_orphan_run_state(self) -> None:
        created = self.model_loop.create_model_record("Latest Workspace", "Temporary model.")
        model_id = created["model_manifest"]["model_id"]

        workspace = self.model_loop.build_workspace_payload()

        self.assertEqual(workspace["selected_model"]["model_id"], model_id)
        self.assertEqual(workspace["model_library_lazy"]["endpoint"], f"/api/builds?model_id={model_id}")

    def test_agent_trace_records_input_and_review_chat(self) -> None:
        created = self.model_loop.create_model_record("Trace Chat", "Temporary model.")
        model_id = created["model_manifest"]["model_id"]

        with patch.dict(os.environ, {"MODEL_FACTORY_UNIT_STUBS": "1"}):
            self.model_loop.send_input_agent_message_record(model_id, "Build a custom model with editable drivers.")
            self.model_loop.send_review_agent_message_record(model_id, "What is blocking publish?", phase="review")

        manifest = self.model_registry.read_model(model_id)
        version_id = manifest["current_version_id"]
        trace_path = RUNTIME_DIR / "artifacts" / "model_versions" / model_id / version_id / "agent_trace.json"
        self.assertTrue(trace_path.exists())

        import json

        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        event_types = [event["event_type"] for event in trace["events"]]
        self.assertIn("user_to_input_agent", event_types)
        self.assertIn("input_agent_to_user", event_types)
        self.assertIn("user_to_review_chat_agent", event_types)
        self.assertIn("review_chat_agent_to_user", event_types)

    def test_model_library_remains_lazy_and_no_generated_builds_are_listed(self) -> None:
        first = self.model_loop.create_model_record("First Model", "First purpose.")
        second = self.model_loop.create_model_record("Second Model", "Second purpose.")
        first_id = first["model_manifest"]["model_id"]
        second_id = second["model_manifest"]["model_id"]

        first_workspace = self.model_loop.build_workspace_payload(first_id)
        second_workspace = self.model_loop.build_workspace_payload(second_id)

        self.assertEqual(first_workspace["model_library"], [])
        self.assertEqual(second_workspace["model_library"], [])
        self.assertIn(f"model_id={first_id}", first_workspace["model_library_lazy"]["endpoint"])
        self.assertIn(f"model_id={second_id}", second_workspace["model_library_lazy"]["endpoint"])
        self.assertEqual(self.model_loop.list_model_builds(first_id), [])
        self.assertEqual(self.model_loop.list_model_builds(second_id), [])


if __name__ == "__main__":
    unittest.main()
