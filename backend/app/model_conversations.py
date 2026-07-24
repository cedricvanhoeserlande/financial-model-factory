from __future__ import annotations

from backend.app import model_trace
from backend.app.model_context import *
from backend.app.model_usage import _record_openai_usage, _use_unit_stubs
from backend.app.model_workspace import (
    _workspace_input_params,
    build_input_review_summary,
    build_workspace_payload,
    default_input_params,
)

def _conversation_root(manifest: dict[str, Any], *, create: bool = True) -> tuple[str, Path]:
    if not create:
        version_id = str(manifest.get("current_version_id") or "")
        if not version_id:
            return "", model_builder.versions_root() / str(manifest["model_id"]) / "__no_current_version__"
        return version_id, model_builder.version_dir(str(manifest["model_id"]), version_id)
    version_id, root = model_builder.ensure_version(manifest)
    if not manifest.get("current_version_id"):
        model_registry.attach_package_version(
            model_id=str(manifest["model_id"]),
            version_id=version_id,
            state="draft",
            input_params=manifest.get("current_input_params") or default_input_params(),
        )
        manifest["current_version_id"] = version_id
    return version_id, root

def _conversation_path(manifest: dict[str, Any], *, create: bool = True) -> Path:
    _, root = _conversation_root(manifest, create=create)
    return root / INPUT_AGENT_CONVERSATION

def _scope_history_path(manifest: dict[str, Any], *, create: bool = True) -> Path:
    _, root = _conversation_root(manifest, create=create)
    return root / INPUT_AGENT_SCOPE_HISTORY

def _review_conversation_path(manifest: dict[str, Any], *, create: bool = True) -> Path:
    _, root = _conversation_root(manifest, create=create)
    return root / REVIEW_AGENT_CONVERSATION

def _initial_conversation(model_name: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": INITIAL_INPUT_AGENT_MESSAGE,
                "created_utc": _utc_now(),
            }
        ],
        "ready_to_draft": False,
        "ready_to_spec": False,
        "scope_summary_version": 0,
        "scope_summary": "No scope captured yet.",
        "locked_decisions": [],
        "editable_placeholders": [],
        "open_questions": list(SCOPE_CHECKLIST_QUESTIONS),
        "updated_utc": _utc_now(),
        "last_scope_update_utc": _utc_now(),
        "model_name": model_name,
    }

def _initial_review_conversation(model_name: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "assistant",
                "content": (
                    "I can explain the current model specification, mappings, inputs, build blockers, "
                    "and checks. I will point you to structured actions for any model changes."
                ),
                "created_utc": _utc_now(),
            }
        ],
        "ready_to_draft": False,
        "ready_to_spec": False,
        "scope_summary_version": 0,
        "scope_summary": "Review chat is separate from scoping.",
        "locked_decisions": [],
        "editable_placeholders": [],
        "open_questions": [],
        "updated_utc": _utc_now(),
        "last_scope_update_utc": _utc_now(),
        "model_name": model_name,
        "review_only": True,
    }

def read_input_agent_conversation(model_id: str | None, *, mutate: bool = False) -> dict[str, Any]:
    if not model_id:
        return _initial_conversation("new model")
    manifest = model_registry.read_model(model_id)
    if not manifest:
        return _initial_conversation("new model")
    path = _conversation_path(manifest, create=mutate)
    if not path.exists():
        conversation = _initial_conversation(str(manifest.get("name") or "this model"))
        if mutate:
            _write_json(path, conversation)
        return conversation
    payload = _read_json(path)
    if not isinstance(payload.get("messages"), list) or not payload["messages"]:
        payload = _initial_conversation(str(manifest.get("name") or "this model"))
        if mutate:
            _write_json(path, payload)
    historic_open_questions = " ".join(str(question) for question in payload.get("open_questions") or [])
    if "scope_summary" not in payload or payload.get("editable_placeholders") or "Describe the business model" in historic_open_questions:
        payload = _with_scope_summary(payload)
        if mutate:
            _write_json(path, payload)
    messages = list(payload.get("messages") or [])
    user_messages = _conversation_user_messages(messages)
    open_questions = _reconcile_open_scope_questions(
        [str(question).strip() for question in payload.get("open_questions") or [] if str(question).strip()],
        user_messages,
    )
    ready = _conversation_ready_to_draft(messages) and not open_questions
    if payload.get("open_questions") != open_questions or bool(payload.get("ready_to_draft")) != ready:
        payload["open_questions"] = open_questions
        payload["ready_to_draft"] = ready
        payload["ready_to_spec"] = ready
        if mutate:
            _write_json(path, payload)
    if mutate:
        _append_scope_history(manifest, payload)
    return payload

def read_review_agent_conversation(model_id: str | None, *, mutate: bool = False) -> dict[str, Any]:
    if not model_id:
        return _initial_review_conversation("new model")
    manifest = model_registry.read_model(model_id)
    if not manifest:
        return _initial_review_conversation("new model")
    path = _review_conversation_path(manifest, create=mutate)
    if not path.exists():
        conversation = _initial_review_conversation(str(manifest.get("name") or "this model"))
        if mutate:
            _write_json(path, conversation)
        return conversation
    payload = _read_json(path)
    if not isinstance(payload.get("messages"), list) or not payload["messages"]:
        payload = _initial_review_conversation(str(manifest.get("name") or "this model"))
        if mutate:
            _write_json(path, payload)
    payload["review_only"] = True
    return payload

def _write_input_agent_conversation(manifest: dict[str, Any], conversation: dict[str, Any]) -> None:
    conversation["updated_utc"] = _utc_now()
    conversation["model_name"] = manifest.get("name") or "this model"
    _write_json(_conversation_path(manifest, create=True), conversation)
    _append_scope_history(manifest, conversation)

def _write_review_agent_conversation(manifest: dict[str, Any], conversation: dict[str, Any]) -> None:
    conversation["updated_utc"] = _utc_now()
    conversation["model_name"] = manifest.get("name") or "this model"
    conversation["review_only"] = True
    _write_json(_review_conversation_path(manifest, create=True), conversation)

def _append_scope_history(manifest: dict[str, Any], conversation: dict[str, Any]) -> None:
    path = _scope_history_path(manifest, create=True)
    existing = _read_json(path) if path.exists() else {}
    snapshots = existing.get("snapshots") if isinstance(existing, dict) else []
    if not isinstance(snapshots, list):
        snapshots = []
    messages = list(conversation.get("messages") or [])
    user_messages = [message for message in messages if isinstance(message, dict) and message.get("role") == "user"]
    snapshot = {
        "captured_utc": conversation.get("updated_utc") or _utc_now(),
        "model_id": manifest.get("model_id"),
        "model_name": manifest.get("name") or conversation.get("model_name") or "this model",
        "message_count": len(messages),
        "user_message_count": len(user_messages),
        "latest_user_message": str((user_messages[-1] if user_messages else {}).get("content") or ""),
        "scope_summary_version": conversation.get("scope_summary_version"),
        "scope_summary": conversation.get("scope_summary"),
        "scope_summary_source": conversation.get("scope_summary_source"),
        "open_questions": list(conversation.get("open_questions") or []),
        "locked_decisions": list(conversation.get("locked_decisions") or []),
        "ready_to_draft": bool(conversation.get("ready_to_draft")),
        "ready_to_spec": bool(conversation.get("ready_to_spec") or conversation.get("ready_to_draft")),
    }
    last = snapshots[-1] if snapshots and isinstance(snapshots[-1], dict) else None
    if last and all(last.get(key) == snapshot.get(key) for key in ("message_count", "scope_summary", "open_questions", "ready_to_draft", "ready_to_spec")):
        return
    snapshots.append(snapshot)
    _write_json(path, {"snapshots": snapshots})

def _unit_stub_input_agent_reply(messages: list[dict[str, Any]]) -> str:
    questions = [
        "What decision should this model support?",
        "Which modeled objects, editable drivers, and output views should the package include?",
    ]
    user_count = sum(1 for message in messages if message.get("role") == "user")
    if user_count >= 2:
        return "Enough to draft the specification. Optional refinements can be handled as inputs unless they change the model architecture."
    return "I understand the direction. Please answer the blocking questions by number: " + " ".join(f"{index + 1}. {question}" for index, question in enumerate(questions[:2]))

def _unit_stub_review_agent_reply(message: str, context: dict[str, Any]) -> str:
    phase = str(context.get("phase") or "review").replace("_", " ")
    blockers = context.get("blockers") if isinstance(context.get("blockers"), list) else []
    if blockers:
        return f"In {phase}, the blocking item is: {blockers[0]}. Use the structured controls on the left to resolve it; I will not change artifacts from chat."
    if "change" in message.lower() or "editable" in message.lower():
        return "That is a model change request. Use Return to scoping or create a draft version so the structured artifacts can be revised."
    return f"I can explain the current {phase} state. This answer is review-only; approved artifacts are not changed from chat."

def _clean_input_agent_reply(text: str) -> str:
    return text.replace("**", "").replace("Ã¢â‚¬â€", "-").replace("Ã¢â‚¬â€œ", "-").strip()

def _contains_model_setup_question(text: str) -> bool:
    return bool(MODEL_SETUP_QUESTION_RE.search(text))

def _is_optional_scope_refinement_question(question: str, user_messages: list[str]) -> bool:
    text = str(question or "").strip()
    if not text or not OPTIONAL_REFINEMENT_RE.search(text):
        return False
    deterministic = _derive_scope_summary(user_messages)
    return not bool(deterministic.get("open_questions") or [])

def _strip_model_setup_questions(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    removed = 0
    for line in lines:
        clean = line.strip()
        numbered = re.match(r"^\d+[\.)]\s*(.+)$", clean)
        question_text = numbered.group(1) if numbered else clean
        if _contains_model_setup_question(question_text) and ("?" in question_text or numbered or question_text.lower().startswith("confirm ")):
            removed += 1
            continue
        if removed and re.match(r"^(one|two|\d+)\s+(quick\s+)?(blocking\s+)?(input|inputs|question|questions)\s*:?\s*$", clean, re.IGNORECASE):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if not cleaned:
        return "I have enough to continue. Please provide any model-specific objects, drivers, logic, or output details that would change the package architecture."
    counter = 0
    renumbered: list[str] = []
    for line in cleaned.splitlines():
        match = re.match(r"^(\s*)\d+[\.)]\s*(.+)$", line)
        if match:
            counter += 1
            renumbered.append(f"{match.group(1)}{counter}. {match.group(2)}")
        else:
            renumbered.append(line)
    return "\n".join(renumbered).strip()

def _strip_chat_summary(text: str) -> str:
    lines = text.splitlines()
    kept = []
    skipping = False
    for line in lines:
        clean = line.strip()
        if clean.lower() in {"summary:", "brief summary:"}:
            skipping = True
            continue
        if skipping and (clean.startswith(("1.", "2.", "3.")) or "question" in clean.lower() or "clarif" in clean.lower()):
            skipping = False
        if not skipping:
            kept.append(line)
    result = "\n".join(kept).strip()
    return _strip_model_setup_questions(result or "Enough to draft the specification. Optional refinements can be handled as inputs.")

def _conversation_ready_to_draft(messages: list[dict[str, Any]]) -> bool:
    user_messages = _conversation_user_messages(messages)
    latest_questions = _reconcile_open_scope_questions(_latest_assistant_open_questions(messages), user_messages)
    if latest_questions:
        return False
    return any(
        message.get("role") == "user" and len(str(message.get("content") or "").strip()) >= 40
        for message in messages
    )

def _conversation_user_messages(messages: list[dict[str, Any]]) -> list[str]:
    return [
        str(message.get("content") or "").strip()
        for message in messages
        if isinstance(message, dict) and message.get("role") == "user" and str(message.get("content") or "").strip()
    ]

def _latest_assistant_signals_ready(messages: list[dict[str, Any]]) -> bool:
    latest = None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            latest = str(message.get("content") or "")
            break
    if not latest:
        return False
    lower = latest.lower()
    return any(
        phrase in lower
        for phrase in (
            "enough to build",
            "enough to draft",
            "enough to continue",
            "enough to proceed",
            "ready to confirm",
            "ready to draft",
            "no remaining",
        )
    )

def _latest_assistant_open_questions(messages: list[dict[str, Any]]) -> list[str]:
    latest = None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            latest = str(message.get("content") or "")
            break
    if not latest or "?" not in latest:
        return []
    if _latest_assistant_signals_ready(messages):
        return []
    return _extract_open_business_questions(latest)

def _extract_open_business_questions(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    matches = list(re.finditer(r"(?<![\w-])\d+[\.)]\s+", normalized))
    candidates: list[str] = []
    if matches:
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
            candidates.append(normalized[start:end].strip())
    else:
        candidates.extend(part.strip() + "?" for part in re.findall(r"([^?\n]{12,}\?)", normalized))

    questions: list[str] = []
    for candidate in candidates:
        candidate = _clean_input_agent_reply(candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip(" -")
        if "?" not in candidate:
            continue
        candidate = _strip_model_setup_questions(candidate).strip()
        if not candidate or _contains_model_setup_question(candidate):
            continue
        if candidate not in questions:
            questions.append(candidate)
    return questions[:2]

def _with_scope_summary(conversation: dict[str, Any], manifest: dict[str, Any] | None = None, use_live_summary: bool = False) -> dict[str, Any]:
    messages = list(conversation.get("messages") or [])
    user_messages = _conversation_user_messages(messages)
    deterministic_summary = _derive_scope_summary(user_messages)
    summary = deterministic_summary
    summary_usage_report = None
    if use_live_summary and manifest and user_messages and not _use_unit_stubs():
        try:
            summary, summary_usage_report = _live_scope_summary(messages, manifest, summary)
        except Exception:
            summary_usage_report = {
                "status": "failed",
                "error": traceback.format_exc(limit=1).strip(),
            }
    summary = _reconcile_scope_summary_questions(summary, deterministic_summary, user_messages)
    assistant_questions = _reconcile_open_scope_questions(_latest_assistant_open_questions(messages), user_messages)
    open_questions = list(assistant_questions)
    if not _latest_assistant_signals_ready(messages):
        for question in summary["open_questions"]:
            if question not in open_questions:
                open_questions.append(question)
    return {
        **conversation,
        "scope_summary_version": max(int(conversation.get("scope_summary_version") or 0), len(user_messages)),
        "scope_summary": summary["scope_summary"],
        "locked_decisions": summary["locked_decisions"],
        "editable_placeholders": summary["editable_placeholders"],
        "open_questions": open_questions[:2],
        "ready_to_draft": _conversation_ready_to_draft(messages) and not open_questions,
        "ready_to_spec": _conversation_ready_to_draft(messages) and not open_questions,
        "scope_summary_source": "ai" if summary_usage_report and summary_usage_report.get("status") == "completed" else "deterministic",
        "last_scope_summary_usage_report": summary_usage_report,
        "last_scope_update_utc": _utc_now(),
    }

def _derive_scope_summary(user_messages: list[str]) -> dict[str, Any]:
    if not user_messages:
        return {
            "scope_summary": "No scope captured yet.",
            "locked_decisions": [],
            "editable_placeholders": [],
            "open_questions": list(SCOPE_CHECKLIST_QUESTIONS),
        }
    combined = " ".join(user_messages)
    lower = combined.lower()
    locked = []
    if "annual" in lower:
        locked.append("Annual cadence")
    if "10 year" in lower or "10-year" in lower or "10 years" in lower:
        locked.append("10-year horizon")
    summary_text = combined.strip()
    if len(summary_text) > 650:
        summary_text = summary_text[:647].rstrip() + "..."
    questions = []
    business_captured = any(word in lower for word in ("model", "purpose", "business", "project", "build", "decision"))
    entities_captured = any(word in lower for word in ("entity", "entities", "object", "objects", "segment", "segments", "item", "items", "site", "sites"))
    drivers_captured = any(word in lower for word in ("driver", "drivers", "input", "inputs", "assumption", "assumptions", "rate", "amount", "volume"))
    outputs_captured = any(word in lower for word in ("output", "outputs", "table", "tables", "kpi", "dashboard", "chart", "summary", "schedule"))
    if not business_captured:
        questions.append("Model purpose")
    if not entities_captured:
        questions.append("Modeled objects")
    if not drivers_captured:
        questions.append("Editable drivers")
    if not outputs_captured:
        questions.append("Required outputs")
    return {
        "scope_summary": summary_text,
        "locked_decisions": locked or ["Initial model direction captured"],
        "editable_placeholders": [],
        "open_questions": questions,
    }

def _normalize_scope_question(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

def _reconcile_open_scope_questions(questions: list[str], user_messages: list[str]) -> list[str]:
    deterministic_summary = _derive_scope_summary(user_messages)
    summary = {**deterministic_summary, "open_questions": questions}
    return _reconcile_scope_summary_questions(summary, deterministic_summary, user_messages)["open_questions"]

def _reconcile_scope_summary_questions(
    summary: dict[str, Any],
    deterministic_summary: dict[str, Any],
    user_messages: list[str] | None = None,
) -> dict[str, Any]:
    core_questions = {_normalize_scope_question(question) for question in SCOPE_CHECKLIST_QUESTIONS}
    deterministic_open = {_normalize_scope_question(question) for question in deterministic_summary.get("open_questions") or []}
    user_messages = user_messages or []
    reconciled: list[str] = []
    for question in summary.get("open_questions") or []:
        text = str(question).strip()
        if not text:
            continue
        normalized = _normalize_scope_question(text)
        if normalized in core_questions and normalized not in deterministic_open:
            continue
        if _is_optional_scope_refinement_question(text, user_messages):
            continue
        if text not in reconciled:
            reconciled.append(text)
    return {**summary, "open_questions": reconciled}

def _extract_response_text(raw: dict[str, Any]) -> str:
    if isinstance(raw.get("output_text"), str) and raw["output_text"].strip():
        return raw["output_text"].strip()
    chunks: list[str] = []
    for item in raw.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks).strip()

def _parse_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object.")
    return parsed

def _live_scope_summary(messages: list[dict[str, Any]], manifest: dict[str, Any], fallback: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for live scope summaries.")
    model = model_config.model_for_role("input_agent")
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": prompts.load_prompt("input_agent_scope_summary"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "model_name": manifest.get("name"),
                        "messages": messages[-16:],
                        "fallback": fallback,
                    },
                    indent=2,
                ),
            },
        ],
        "reasoning": {"effort": "low"},
        "store": False,
    }
    version_id, root = _conversation_root(manifest)
    body["metadata"] = {
        "model_id": str(manifest.get("model_id") or ""),
        "version_id": version_id,
        "stage": "input_agent_scope_summary",
    }
    model_trace.append_event(
        root,
        "input_agent_scope_summary_request",
        actor="backend",
        recipient="input_agent",
        stage="input_agent_scope_summary",
        status="sent",
        payload=body,
    )
    raw = model_builder._post_openai(api_key, body)
    model_trace.append_event(
        root,
        "input_agent_scope_summary_response",
        actor="input_agent",
        recipient="backend",
        stage="input_agent_scope_summary",
        status="received",
        payload=raw,
    )
    parsed = _parse_json_object(_extract_response_text(raw))
    scope_summary = _strip_model_setup_questions(_clean_input_agent_reply(str(parsed.get("scope_summary") or ""))).strip()
    if not scope_summary:
        scope_summary = fallback["scope_summary"]
    open_questions = parsed.get("open_questions")
    if not isinstance(open_questions, list):
        open_questions = fallback.get("open_questions") or []
    clean_questions = []
    for question in open_questions[:2]:
        question_text = _clean_input_agent_reply(str(question)).strip()
        if not question_text or _contains_model_setup_question(question_text):
            continue
        clean_questions.append(_strip_model_setup_questions(question_text).strip())
    summary = {
        **fallback,
        "scope_summary": scope_summary,
        "editable_placeholders": [],
        "open_questions": [question for question in clean_questions if question],
    }
    usage_report = _record_openai_usage(
        build_run_id=f"{version_id}_input_agent_summary_{uuid.uuid4().hex[:8]}",
        model=model,
        status="completed",
        usage=raw.get("usage") or {},
        artifact_dir=root,
    )
    model_trace.append_event(
        root,
        "input_agent_scope_summary_response",
        actor="backend",
        recipient="trace",
        stage="input_agent_scope_summary",
        status="parsed",
        payload=summary,
        usage=usage_report,
    )
    return summary, usage_report

def _live_input_agent_reply(messages: list[dict[str, Any]], manifest: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for live Input Agent chat. Unit-test stubs are available only through MODEL_FACTORY_UNIT_STUBS=1.")
    model = model_config.model_for_role("input_agent")
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": prompts.load_prompt("input_agent_chat"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "model_name": manifest.get("name"),
                        "messages": messages[-12:],
                    },
                    indent=2,
                ),
            },
        ],
        "reasoning": {"effort": "low"},
        "store": False,
    }
    version_id, root = _conversation_root(manifest)
    body["metadata"] = {
        "model_id": str(manifest.get("model_id") or ""),
        "version_id": version_id,
        "stage": "input_agent_chat",
    }
    model_trace.append_event(
        root,
        "input_agent_scope_summary_request",
        actor="backend",
        recipient="input_agent",
        stage="input_agent_chat",
        status="sent",
        payload=body,
    )
    raw = model_builder._post_openai(api_key, body)
    model_trace.append_event(
        root,
        "input_agent_scope_summary_response",
        actor="input_agent",
        recipient="backend",
        stage="input_agent_chat",
        status="received",
        payload=raw,
    )
    text = _strip_chat_summary(_clean_input_agent_reply(_extract_response_text(raw)))
    if not text:
        text = "I have enough to continue. Which model-specific objects, drivers, outputs, or validation details should I lock into the specification?"
    usage = raw.get("usage") or {}
    usage_report = _record_openai_usage(
        build_run_id=f"{version_id}_input_agent_chat_{uuid.uuid4().hex[:8]}",
        model=model,
        status="completed",
        usage=usage,
        artifact_dir=root,
    )
    return text, usage_report

def _review_agent_context(manifest: dict[str, Any], phase: str) -> dict[str, Any]:
    package_state = model_builder.read_state(manifest) if model_builder.is_model_package_version(manifest) else {}
    input_review = build_input_review_summary(
        _workspace_input_params(manifest.get("current_input_params"), package_state.get("resolved_input_params"))
        or manifest.get("current_input_params")
        or default_input_params()
    )
    validation_report = package_state.get("validation_report") if isinstance(package_state.get("validation_report"), dict) else {}
    input_items = input_review.get("items") if isinstance(input_review, dict) else []
    provenance_counts: dict[str, int] = {}
    if isinstance(input_items, list):
        for item in input_items:
            if isinstance(item, dict):
                source = str(item.get("source") or item.get("provenance") or "unknown")
                provenance_counts[source] = provenance_counts.get(source, 0) + 1
    blockers: list[str] = []
    if package_state.get("status") == "failed_checks":
        blockers.append(str(package_state.get("status_label") or "Checks failed"))
    return {
        "phase": phase,
        "model_name": manifest.get("name"),
        "model_status": manifest.get("status") or manifest.get("current_version_state"),
        "package_state_status": package_state.get("status"),
        "package_state_status_label": package_state.get("status_label"),
        "build_summary": {
            "source": package_state.get("build_source"),
            "package_entrypoint": package_state.get("package_entrypoint"),
            "review_required": package_state.get("human_review_required"),
        },
        "input_provenance_counts": provenance_counts,
        "validation_passed": validation_report.get("passed") if validation_report else None,
        "blockers": blockers[:8],
        "allowed_behavior": (
            "Answer questions and suggest structured next actions only. Do not mutate specification, "
            "input schema, package logic, or published artifacts from chat."
        ),
    }

def _suggested_review_actions(phase: str, context: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if phase != "scope_chat":
        actions.append({"label": "Return to scoping for model changes", "target_phase": "scope_chat"})
    if context.get("package_state_status") == "failed_checks":
        actions.append({"label": "Open Build / Review", "target_phase": "review"})
    return actions[:3]

def _live_review_agent_reply(messages: list[dict[str, Any]], manifest: dict[str, Any], phase: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for live Review Agent chat. Unit-test stubs are available only through MODEL_FACTORY_UNIT_STUBS=1.")
    model = model_config.model_for_role("input_agent")
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": prompts.load_prompt("review_agent_chat"),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "phase": phase,
                        "context": context,
                        "messages": messages[-12:],
                    },
                    indent=2,
                ),
            },
        ],
        "reasoning": {"effort": "low"},
        "store": False,
    }
    version_id, root = _conversation_root(manifest)
    body["metadata"] = {
        "model_id": str(manifest.get("model_id") or ""),
        "version_id": version_id,
        "stage": "review_agent_chat",
    }
    model_trace.append_event(
        root,
        "review_agent_audit_request",
        actor="backend",
        recipient="review_chat_agent",
        stage="review_agent_chat",
        status="sent",
        payload=body,
    )
    raw = model_builder._post_openai(api_key, body)
    model_trace.append_event(
        root,
        "review_agent_audit_raw_response",
        actor="review_chat_agent",
        recipient="backend",
        stage="review_agent_chat",
        status="received",
        payload=raw,
    )
    text = _clean_input_agent_reply(_extract_response_text(raw))
    if not text:
        text = "I can explain the current review state, but model changes need to go through structured actions."
    usage_report = _record_openai_usage(
        build_run_id=f"{version_id}_review_agent_chat_{uuid.uuid4().hex[:8]}",
        model=model,
        status="completed",
        usage=raw.get("usage") or {},
        artifact_dir=root,
    )
    return text, usage_report

def send_input_agent_message_record(model_id: str, message: str) -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    clean_message = message.strip()
    if not clean_message:
        raise RuntimeError("Message is required.")
    conversation = read_input_agent_conversation(model_id)
    messages = list(conversation.get("messages") or [])
    messages.append({"role": "user", "content": clean_message, "created_utc": _utc_now()})
    _, trace_root = _conversation_root(manifest)
    model_trace.append_event(
        trace_root,
        "user_to_input_agent",
        actor="user",
        recipient="input_agent",
        stage="input_agent_chat",
        status="sent",
        payload={"message": clean_message},
    )
    usage_report = None
    if _use_unit_stubs():
        reply = _clean_input_agent_reply(_unit_stub_input_agent_reply(messages))
    else:
        reply, usage_report = _live_input_agent_reply(messages, manifest)
    reply = _strip_chat_summary(reply)
    messages.append({"role": "assistant", "content": reply, "created_utc": _utc_now()})
    model_trace.append_event(
        trace_root,
        "input_agent_to_user",
        actor="input_agent",
        recipient="user",
        stage="input_agent_chat",
        status="sent",
        payload={"message": reply},
        usage=usage_report,
    )
    conversation = _with_scope_summary(
        {
            **conversation,
            "messages": messages,
            "ready_to_draft": _conversation_ready_to_draft(messages),
            "ready_to_spec": _conversation_ready_to_draft(messages),
            "last_usage_report": usage_report,
        },
        manifest=manifest,
        use_live_summary=not _use_unit_stubs(),
    )
    _write_input_agent_conversation(manifest, conversation)
    return {"model_manifest": model_registry.read_model(model_id), "workspace": build_workspace_payload(model_id), "conversation": conversation}

def send_review_agent_message_record(model_id: str, message: str, phase: str = "review") -> dict[str, Any]:
    manifest = model_registry.read_model(model_id)
    if not manifest:
        raise RuntimeError(f"Model not found: {model_id}")
    clean_message = message.strip()
    if not clean_message:
        raise RuntimeError("Message is required.")
    clean_phase = re.sub(r"[^a-z0-9_]+", "", str(phase or "review").lower()) or "review"
    conversation = read_review_agent_conversation(model_id)
    messages = list(conversation.get("messages") or [])
    messages.append({"role": "user", "content": clean_message, "created_utc": _utc_now(), "phase": clean_phase})
    _, trace_root = _conversation_root(manifest)
    model_trace.append_event(
        trace_root,
        "user_to_review_chat_agent",
        actor="user",
        recipient="review_chat_agent",
        stage="review_agent_chat",
        status="sent",
        payload={"message": clean_message, "phase": clean_phase},
    )
    context = _review_agent_context(manifest, clean_phase)
    usage_report = None
    if _use_unit_stubs():
        reply = _unit_stub_review_agent_reply(clean_message, context)
    else:
        reply, usage_report = _live_review_agent_reply(messages, manifest, clean_phase, context)
    messages.append({"role": "assistant", "content": reply, "created_utc": _utc_now(), "phase": clean_phase})
    model_trace.append_event(
        trace_root,
        "review_chat_agent_to_user",
        actor="review_chat_agent",
        recipient="user",
        stage="review_agent_chat",
        status="sent",
        payload={"message": reply, "phase": clean_phase},
        usage=usage_report,
    )
    conversation = {
        **conversation,
        "messages": messages,
        "last_usage_report": usage_report,
        "last_phase": clean_phase,
        "review_only": True,
    }
    _write_review_agent_conversation(manifest, conversation)
    return {
        "model_manifest": model_registry.read_model(model_id),
        "workspace": build_workspace_payload(model_id),
        "conversation": conversation,
        "assistant_message": reply,
        "phase": clean_phase,
        "review_only": True,
        "suggested_actions": _suggested_review_actions(clean_phase, context),
    }


