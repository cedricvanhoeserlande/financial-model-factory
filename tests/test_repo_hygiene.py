from __future__ import annotations

import subprocess
import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepoHygieneTest(unittest.TestCase):
    def test_generated_runtime_and_tooling_paths_are_not_tracked(self) -> None:
        tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        forbidden_fragments = [
            ".venv/",
            "venv/",
            ".tools/",
            "node_modules/",
            "frontend/dist/",
            "dist/",
            "build/",
            ".server/",
            "__pycache__/",
            ".pytest_cache/",
            "playwright-report/",
            "test-results/",
        ]
        forbidden_suffixes = (".pyc", ".pyd", ".dll", ".so", ".dylib", ".exe")
        offenders = []
        for path in tracked:
            normalized = path.replace("\\", "/")
            if normalized.startswith("reference/mf_EXP-B/"):
                offenders.append(normalized)
            if any(fragment in normalized for fragment in forbidden_fragments):
                offenders.append(normalized)
            if normalized.endswith(forbidden_suffixes):
                offenders.append(normalized)

        self.assertEqual([], sorted(set(offenders)))

    def test_current_version_prompt_file_is_not_tracked_or_ignored(self) -> None:
        tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        self.assertNotIn("docs/current_version.md", tracked)
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "docs/current_version.md"],
            cwd=ROOT,
            text=True,
        )
        self.assertNotEqual(0, ignored.returncode)

    def test_runtime_data_is_not_tracked(self) -> None:
        tracked = subprocess.check_output(["git", "ls-files", "data"], cwd=ROOT, text=True).splitlines()
        self.assertEqual([], tracked)

    def test_new_runtime_data_paths_are_ignored_by_default(self) -> None:
        samples = [
            "data/models/runtime_index.json",
            "data/models/new-local-model/model_manifest.json",
            "data/artifacts/model_versions/new-local-model/version_1/model_design.json",
            "data/usage/runtime_openai_usage.jsonl",
            "tests/.tmp/minimal_product_path/local-model/models/index.json",
        ]
        for sample in samples:
            ignored = subprocess.run(["git", "check-ignore", "-q", sample], cwd=ROOT, text=True)
            self.assertEqual(0, ignored.returncode, sample)

    def test_legacy_product_acceptance_harness_is_removed(self) -> None:
        self.assertFalse((ROOT / "tests" / "product_acceptance").exists())
        self.assertFalse((ROOT / "tests" / "e2e").exists())

    def test_model_data_paths_are_ignored(self) -> None:
        samples = [
            "data/models/index.json",
            "data/models/live-vet-rollup-qa-20260507-014724-398bd166/model_manifest.json",
            "data/artifacts/build_index.json",
            "data/artifacts/model_versions/live-vet-rollup-qa-20260507-014724-398bd166/version_placeholder/model_design.json",
            "data/usage/openai_usage.jsonl",
        ]
        for sample in samples:
            ignored = subprocess.run(["git", "check-ignore", "-q", sample], cwd=ROOT, text=True)
            self.assertEqual(0, ignored.returncode, sample)

    def test_legacy_seed_workspace_fixture_is_removed(self) -> None:
        tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        forbidden = {
            "data/workspaces/.gitkeep",
            "data/workspaces/seed_workspace.json",
            "data/runs/latest_seed_run.json",
        }
        self.assertTrue(forbidden.isdisjoint(set(tracked)))
        for path in (ROOT / "backend").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("seed_workspace", text, path.relative_to(ROOT).as_posix())
            self.assertNotIn("WORKSPACE_FIXTURE", text, path.relative_to(ROOT).as_posix())

    def test_app_orchestration_has_no_embedded_standard_finance_labels(self) -> None:
        forbidden = {
            "finance": r"\bfinance\b",
            "financial": r"\bfinancial\b",
            "economic": r"\beconomic(?:s)?\b",
            "asset": r"\bassets?\b",
            "revenue": r"\brevenue\b",
            "ebitda": r"\bebitda\b",
            "dcf": r"\bdcf\b",
            "valuation": r"\bvaluation\b",
            "debt": r"\bdebt\b",
            "capex": r"\bcapex\b",
            "opex": r"\bopex\b",
            "working capital": r"\bworking\s+capital\b",
            "balance sheet": r"\bbalance\s+sheet\b",
            "income statement": r"\bincome\s+statement\b",
            "cash flow": r"\bcash\s+flow\b",
            "equity": r"\bequity\b",
            "liability": r"\bliabilit(?:y|ies)\b",
        }
        offenders = []
        for path in (ROOT / "backend" / "app").glob("*"):
            if path.suffix not in {".py", ".md"}:
                continue
            text = path.read_text(encoding="utf-8-sig")
            hits = [term for term, pattern in forbidden.items() if re.search(pattern, text, flags=re.IGNORECASE)]
            if hits:
                offenders.append({"path": path.relative_to(ROOT).as_posix(), "terms": hits})
        self.assertEqual([], offenders)

    def test_standard_three_statement_fallback_is_not_present(self) -> None:
        self.assertFalse((ROOT / "backend" / "finance").exists())
        removed_paths = [
            "backend/app/unit_stub_fixtures.py",
            "backend/prompts/legacy_model_build.md",
        ]
        for relative in removed_paths:
            self.assertFalse((ROOT / relative).exists(), relative)

        forbidden = [
            "standard_runtime",
            "deterministic_main_py",
            "default_validation_contract",
            "legacy_model_build",
            "UNIT_STUB_MODEL_CODE",
            "_generated_code_contract_error",
        ]
        offenders = []
        for path in (ROOT / "backend").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            hits = [term for term in forbidden if term in text]
            if hits:
                offenders.append({"path": path.relative_to(ROOT).as_posix(), "terms": hits})
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
