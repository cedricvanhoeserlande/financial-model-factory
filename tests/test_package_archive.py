from __future__ import annotations

import io
import shutil
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.app import model_runs


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "tests" / ".tmp" / "package_archive"


class PackageArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(RUNTIME, ignore_errors=True)
        self.version = RUNTIME / "version_1"
        package = self.version / "model_package"
        (package / "model").mkdir(parents=True)
        (package / "reports").mkdir()
        (package / "outputs").mkdir()
        (package / "model" / "main.py").write_text("def run_model(inputs): return {}\n", encoding="utf-8")
        (package / "outputs" / "output.json").write_text("{}", encoding="utf-8")
        (package / "reports" / "validation_report.json").write_text("{}", encoding="utf-8")
        (package / "reports" / "raw_response.json").write_text("secret trace", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(RUNTIME, ignore_errors=True)

    def test_archive_contains_canonical_package_and_excludes_raw_traces(self) -> None:
        manifest = {"model_id": "paint", "canonical_version_id": "version_1"}
        with patch.object(model_runs.model_registry, "read_model", return_value=manifest), patch.object(
            model_runs.model_builder, "version_dir", return_value=self.version
        ):
            payload = model_runs.build_package_archive("paint")
        with zipfile.ZipFile(io.BytesIO(payload["content"])) as archive:
            names = set(archive.namelist())
        self.assertEqual(payload["openai_called"], False)
        self.assertIn("model/main.py", names)
        self.assertIn("outputs/output.json", names)
        self.assertIn("reports/validation_report.json", names)
        self.assertNotIn("reports/raw_response.json", names)

    def test_missing_model_is_rejected(self) -> None:
        with patch.object(model_runs.model_registry, "read_model", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Model not found"):
                model_runs.build_package_archive("missing")


if __name__ == "__main__":
    unittest.main()
