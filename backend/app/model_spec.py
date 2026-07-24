from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from backend.ai import prompts
from backend.app import model_builder, model_config, model_registry, model_trace
from backend.app.model_conversations import read_input_agent_conversation


SPEC_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "required": [
        "spec_version",
        "title",
        "purpose",
        "scope_summary",
        "modeled_objects",
        "editable_inputs",
        "assumptions",
        "scenario_design",
        "outputs",
        "dashboard_intent",
        "known_limitations",
        "unresolved_questions",
        "build_readiness",
    ],
    "properties": {
        "spec_version": {"type": "string"},
        "title": {"type": "string"},
        "purpose": {"type": "string"},
        "scope_summary": {"type": "string"},
        "modeled_objects": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "editable_inputs": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "assumptions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "scenario_design": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "outputs": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "dashboard_intent": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "known_limitations": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "build_readiness": {
            "type": "object",
            "additionalProperties": True,
            "required": ["ready_to_build", "blockers"],
            "properties": {
                "ready_to_build": {"type": "boolean"},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


def generate_model_spec_record(model_id: str, prompt: str = "") -> dict[str, Any]:
    manifest = _require_model(model_id)
    version_id, root = model_builder.ensure_version(manifest)
    if not manifest.get("current_version_id"):
        manifest = model_registry.attach_package_version(
            model_id=model_id,
            version_id=version_id,
            state="spec_draft",
            input_params=manifest.get("current_input_params") or model_builder.default_inputs(),
        )
    clean_prompt = _clean_scope_prompt(manifest, prompt)
    try:
        spec, usage_report = request_model_spec(manifest, clean_prompt, root)
        write_model_spec(root, spec, status="draft", prompt=clean_prompt, usage_report=usage_report)
    except Exception as exc:
        code = model_builder._classify_generation_failure(exc, default="spec_failed")
        model_builder._write_failure_report(
            root,
            code=code if code in {"openai_transport_failed", "budget_blocked"} else "spec_failed",
            stage="modeler_spec",
            message=str(exc),
            reasons=[str(exc)],
            status="spec_failed",
            next_actions=model_builder.FAILURE_NEXT_ACTIONS.get("spec_failed"),
            failure_subcode=model_builder._classify_generation_failure_subcode(exc),
        )
        _update_manifest_status(model_id, version_id, "spec_failed")
        raise
    model_trace.append_event(
        root,
        "modeler_spec_parsed",
        actor="backend",
        recipient="trace",
        stage="modeler_spec",
        status="parsed",
        payload={"summary": _spec_summary(spec), "status": "draft"},
        artifacts={"model_spec": "model_spec.json"},
    )
    _update_manifest_status(model_id, version_id, "spec_draft", usage_report=usage_report)
    return {"model_manifest": model_registry.read_model(model_id), "workspace": _workspace_payload(model_id), "package_state": read_spec_state(model_id)}


def approve_model_spec_record(model_id: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = _require_model(model_id)
    version_id, root = _require_version(manifest)
    current = spec if spec is not None else read_model_spec(root).get("model_spec")
    parsed = parse_model_spec(current)
    blockers = _spec_blockers(parsed)
    if blockers:
        raise RuntimeError("Model specification is not ready to build: " + "; ".join(blockers))
    write_model_spec(root, parsed, status="approved", prompt=read_model_spec(root).get("source_prompt") or "")
    model_trace.append_event(
        root,
        "user_model_spec_approved",
        actor="user",
        recipient="backend",
        stage="modeler_spec",
        status="approved",
        payload={"summary": _spec_summary(parsed), "approval": read_model_spec(root).get("approval")},
        artifacts={"model_spec": "model_spec.json"},
    )
    _update_manifest_status(model_id, version_id, "spec_approved")
    return {"model_manifest": model_registry.read_model(model_id), "workspace": _workspace_payload(model_id), "package_state": read_spec_state(model_id)}


def require_approved_model_spec(manifest: dict[str, Any]) -> dict[str, Any]:
    _version_id, root = _require_version(manifest)
    payload = read_model_spec(root)
    if payload.get("status") != "approved":
        raise RuntimeError("Approve the model specification before building the package.")
    spec = parse_model_spec(payload.get("model_spec"))
    blockers = _spec_blockers(spec)
    if blockers:
        raise RuntimeError("Approved model specification is not ready to build: " + "; ".join(blockers))
    return payload


def read_spec_state(model_id: str | None) -> dict[str, Any]:
    if not model_id:
        return {}
    manifest = model_registry.read_model(model_id)
    if not manifest:
        return {}
    version_id = str(manifest.get("current_version_id") or manifest.get("canonical_version_id") or "")
    if not version_id:
        return {}
    root = model_builder.version_dir(str(manifest["model_id"]), version_id)
    return read_model_spec(root)


def read_model_spec(root: Path) -> dict[str, Any]:
    path = root / "model_spec.json"
    if not path.exists():
        return {}
    payload = model_builder._read_json(path)
    if not isinstance(payload, dict):
        return {}
    return payload


def write_model_spec(
    root: Path,
    spec: dict[str, Any],
    *,
    status: str,
    prompt: str,
    usage_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_model_spec(spec)
    existing = read_model_spec(root)
    payload = {
        "status": status,
        "path": "model_spec.json",
        "source_prompt": prompt or existing.get("source_prompt") or "",
        "created_utc": existing.get("created_utc") or model_builder._utc_now(),
        "updated_utc": model_builder._utc_now(),
        "model_spec": parsed,
        "approval": existing.get("approval") if status != "approved" else {"approved_utc": model_builder._utc_now(), "approved_by": "user"},
    }
    if usage_report:
        payload["usage_report"] = usage_report
    model_builder._write_json(root / "model_spec.json", payload)
    return payload


def request_model_spec(manifest: dict[str, Any], prompt: str, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for model specification generation.")
    model = model_config.model_for_stage("modeler_model_spec")
    stage = "modeler_model_spec"
    context = _spec_context(manifest, prompt)
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": prompts.load_prompt("model_spec_design")},
            {"role": "user", "content": json.dumps(context, separators=(",", ":"), default=str)},
        ],
        "text": {"format": {"type": "json_schema", "name": stage, "schema": SPEC_SCHEMA, "strict": False}},
        "reasoning": {"effort": "medium"},
        "store": False,
        "metadata": {
            "model_id": root.parent.name,
            "version_id": root.name,
            "stage": stage,
            "run_id": f"{root.name}_{stage}",
        },
    }
    model_trace.append_event(
        root,
        "modeler_spec_request",
        actor="backend",
        recipient="modeler",
        stage=stage,
        status="sent",
        payload={"system_prompt_id": "model_spec_design", "user_context": context, "request_body": body},
    )
    try:
        raw = model_builder._post_openai(api_key, body)
    except Exception as exc:
        model_trace.append_event(
            root,
            "modeler_spec_raw_response",
            actor="modeler",
            recipient="backend",
            stage=stage,
            status="error",
            error=str(exc),
        )
        raise
    model_trace.append_event(
        root,
        "modeler_spec_raw_response",
        actor="modeler",
        recipient="backend",
        stage=stage,
        status="received",
        payload=raw,
    )
    spec = parse_model_spec(json.loads(model_builder._extract_response_text(raw)))
    usage_report = model_builder._record_usage(root, model, raw.get("usage") or {}, stage=stage)
    return spec, usage_report


def parse_model_spec(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Model specification must be a JSON object.")
    missing = [key for key in SPEC_SCHEMA["required"] if key not in raw]
    if missing:
        raise RuntimeError("Model specification is missing required fields: " + ", ".join(missing))
    parsed = dict(raw)
    for key in ("title", "purpose", "scope_summary", "spec_version"):
        if not isinstance(parsed.get(key), str) or not parsed[key].strip():
            raise RuntimeError(f"Model specification field {key} must be a non-empty string.")
        parsed[key] = parsed[key].strip()
    for key in ("modeled_objects", "editable_inputs", "assumptions", "scenario_design", "outputs", "dashboard_intent"):
        if not isinstance(parsed.get(key), list):
            raise RuntimeError(f"Model specification field {key} must be a list.")
    for key in ("known_limitations", "unresolved_questions"):
        if not isinstance(parsed.get(key), list):
            raise RuntimeError(f"Model specification field {key} must be a list.")
        parsed[key] = [str(item).strip() for item in parsed[key] if str(item).strip()]
    readiness = parsed.get("build_readiness")
    if not isinstance(readiness, dict) or not isinstance(readiness.get("ready_to_build"), bool) or not isinstance(readiness.get("blockers"), list):
        raise RuntimeError("Model specification build_readiness must include ready_to_build and blockers.")
    parsed["build_readiness"] = {
        **readiness,
        "blockers": [str(item).strip() for item in readiness.get("blockers") or [] if str(item).strip()],
    }
    return parsed


def _spec_context(manifest: dict[str, Any], prompt: str) -> dict[str, Any]:
    conversation = read_input_agent_conversation(str(manifest["model_id"]), mutate=False)
    return {
        "model_id": manifest.get("model_id"),
        "model_name": manifest.get("name"),
        "model_description": manifest.get("description"),
        "scope_prompt": prompt,
        "input_agent_scope_summary": conversation.get("scope_summary"),
        "input_agent_open_questions": conversation.get("open_questions") or [],
        "input_agent_ready": bool(conversation.get("ready_to_spec") or conversation.get("ready_to_draft")),
        "input_agent_messages": conversation.get("messages") or [],
        "output_instruction": "Return model_spec.json content only. Do not create code in this step.",
    }


def _spec_summary(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": spec.get("title"),
        "purpose": spec.get("purpose"),
        "ready_to_build": (spec.get("build_readiness") or {}).get("ready_to_build"),
        "unresolved_question_count": len(spec.get("unresolved_questions") or []),
        "blocker_count": len((spec.get("build_readiness") or {}).get("blockers") or []),
    }


def _spec_blockers(spec: dict[str, Any]) -> list[str]:
    readiness = spec.get("build_readiness") or {}
    blockers = [str(item) for item in readiness.get("blockers") or [] if str(item).strip()]
    if readiness.get("ready_to_build") is not True:
        blockers.insert(0, "spec is not marked ready_to_build")
    unresolved = [str(item) for item in spec.get("unresolved_questions") or [] if str(item).strip()]
    return blockers + unresolved


def _clean_scope_prompt(manifest: dict[str, Any], prompt: str) -> str:
    conversation = read_input_agent_conversation(str(manifest["model_id"]), mutate=False)
    return (
        prompt.strip()
        or str(conversation.get("scope_summary") or "").strip()
        or str(manifest.get("description") or "").strip()
        or str(manifest.get("name") or "").strip()
        or "Create a model specification."
    )


def _require_model(model_id: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    return manifest


def _require_version(manifest: dict[str, Any]) -> tuple[str, Path]:
    version_id = str(manifest.get("current_version_id") or "")
    if not version_id:
        raise RuntimeError("Generate and approve a model specification before building the package.")
    return version_id, model_builder.version_dir(str(manifest["model_id"]), version_id)


def _update_manifest_status(
    model_id: str,
    version_id: str,
    status: str,
    *,
    usage_report: dict[str, Any] | None = None,
) -> None:
    root = model_builder.version_dir(model_id, version_id)
    model_builder._update_version_manifest(root, status, usage_report=usage_report)
    model_registry.attach_package_version(
        model_id=model_id,
        version_id=version_id,
        state=status,
        input_params=model_registry.read_model(model_id).get("current_input_params") or model_builder.default_inputs(),
    )


def _workspace_payload(model_id: str) -> dict[str, Any]:
    from backend.app.model_workspace import build_workspace_payload

    return build_workspace_payload(model_id)
