"""Verify the committed accepted paint package without OpenAI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.package_runtime import execute_package, execute_package_checks


ROOT = Path(__file__).resolve().parent / "model_package"


def _all_passed(checks: dict[str, object]) -> bool:
    rows = checks.get("checks")
    if not isinstance(rows, list) or not rows:
        return False
    return all(isinstance(row, dict) and row.get("passed") is True for row in rows)


def main() -> None:
    inputs = json.loads((ROOT / "inputs" / "base_case.json").read_text(encoding="utf-8"))
    output = execute_package(ROOT, inputs)
    checks = execute_package_checks(ROOT, inputs, output)
    if not _all_passed(checks):
        raise SystemExit("The committed paint package checks did not pass.")

    valuation = next(
        block["data"]
        for block in output["output_blocks"]
        if block.get("id") == "valuation"
    )
    print("Paint showcase package verified")
    print(f"Equity value: EUR {valuation['equity_value'] / 1_000_000:.2f}m")
    print("OpenAI calls: 0")


if __name__ == "__main__":
    main()
