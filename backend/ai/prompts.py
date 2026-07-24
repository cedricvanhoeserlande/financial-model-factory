from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = ROOT_DIR / "backend" / "prompts"


@lru_cache(maxsize=None)
def load_prompt(prompt_id: str) -> str:
    safe_id = prompt_id.strip().replace("\\", "/")
    if "/" in safe_id or not safe_id:
        raise ValueError(f"Invalid prompt id: {prompt_id!r}")
    path = PROMPT_DIR / f"{safe_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_id}")
    return path.read_text(encoding="utf-8-sig").strip()
