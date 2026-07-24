from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def trace_path(root: Path) -> Path:
    return root / "agent_trace.json"


def read_trace(root: Path) -> dict[str, Any]:
    path = trace_path(root)
    if not path.exists():
        return {"events": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        return {"events": []}
    return payload


def append_event(
    root: Path,
    event_type: str,
    *,
    actor: str,
    recipient: str,
    stage: str,
    status: str = "recorded",
    attempt: str = "",
    summary: str = "",
    payload: Any | None = None,
    artifacts: dict[str, str] | None = None,
    usage: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    trace = read_trace(root)
    event = {
        "event_id": f"evt_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}",
        "created_utc": _utc_now(),
        "event_type": event_type,
        "model_id": root.parent.name,
        "version_id": root.name,
        "actor": actor,
        "recipient": recipient,
        "stage": stage,
        "attempt": attempt,
        "status": status,
        "summary": summary,
        "artifacts": artifacts or {},
    }
    if payload is not None:
        event["payload"] = payload
    if usage is not None:
        event["usage"] = usage
    if error:
        event["error"] = error
    trace["events"].append(event)
    path = trace_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    return event


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
