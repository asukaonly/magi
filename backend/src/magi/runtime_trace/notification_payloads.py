"""Shared builders for runtime notification payload records."""

from __future__ import annotations

import json
import time
from typing import Any

from .contracts import RuntimeNotificationRecord


CHAT_MESSAGE_UPSERTED = "chat_message_upserted"
CHAT_MESSAGE_HIDDEN = "chat_message_hidden"
TURN_UX_PLAN = "turn_ux_plan"
TRACE_UPDATE = "trace_update"
EXECUTION_CONTROL = "execution_control"
CONTEXT_USAGE = "context_usage"
AGENT_RESPONSE = "agent_response"
AGENT_RESPONSE_CHUNK = "agent_response_chunk"


def build_notification_record(
    *,
    channel: str,
    user_id: str,
    session_id: str,
    payload: dict[str, Any],
    turn_id: str | None = None,
    created_at_ms: int = 0,
) -> RuntimeNotificationRecord:
    return RuntimeNotificationRecord(
        notification_id=0,
        channel=channel,
        user_id=str(user_id or ""),
        session_id=str(session_id or ""),
        turn_id=turn_id,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        created_at_ms=created_at_ms,
    )


def chat_message_upsert_payload(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
    message: Any,
    session_summary: Any | None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "message_id": message_id,
        "message": message.to_dict(),
        "session_summary": (
            session_summary.to_dict() if session_summary is not None else None
        ),
    }


def chat_message_hidden_payload(
    *,
    user_id: str,
    session_id: str,
    message_id: str,
    session_summary: Any | None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "message_id": message_id,
        "session_summary": (
            session_summary.to_dict() if session_summary is not None else None
        ),
    }


def turn_ux_plan_payload(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    ux_plan: dict[str, Any],
    message_id: str | None,
    message_kind: str | None,
    timestamp_ms: int | None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "message_id": message_id,
        "message_kind": message_kind,
        "ux_plan": ux_plan,
        "timestamp": (timestamp_ms / 1000.0) if timestamp_ms is not None else time.time(),
    }


def trace_update_payload(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    trace_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "refresh_trace": True,
    }
    if trace_summary is not None:
        payload["trace_summary"] = trace_summary
    return payload


def execution_control_payload(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    run_id: str | None,
    orchestration_id: str | None,
    state: str,
    can_cancel: bool,
    label: str | None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "run_id": run_id,
        "orchestration_id": orchestration_id,
        "state": state,
        "can_cancel": can_cancel,
        "label": label,
        "timestamp": time.time(),
    }


def context_usage_payload(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    context_usage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "used_tokens": context_usage.get("used_tokens", 0),
        "window_size": context_usage.get(
            "context_window",
            context_usage.get("window_size", 0),
        ),
        "input_capacity": context_usage.get("input_capacity", 0),
        "threshold": context_usage.get(
            "compaction_threshold",
            context_usage.get("threshold", 0),
        ),
        "measurement": context_usage.get("measurement"),
        "model_provider": context_usage.get("model_provider"),
        "model_id": context_usage.get("model_id"),
        "updated_at_ms": context_usage.get("updated_at_ms"),
        "timestamp": time.time(),
    }


def agent_response_payload(
    *,
    user_id: str,
    session_id: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    extra_fields: dict[str, Any] | None = None,
    include_none_extra_fields: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "content": content,
        "is_final": True,
        "timestamp": time.time(),
    }
    if attachments:
        payload["attachments"] = [dict(item) for item in attachments]
    for key, value in (extra_fields or {}).items():
        if value is not None or include_none_extra_fields:
            payload[key] = value
    return payload


def agent_response_chunk_payload(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    event: dict[str, Any],
    is_final: bool,
    seq: int,
    persona_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "event": event,
        "is_final": bool(is_final),
        "seq": int(seq),
        "timestamp": time.time(),
    }
    if persona_id is not None:
        payload["persona_id"] = persona_id
    return payload


__all__ = [
    "AGENT_RESPONSE",
    "AGENT_RESPONSE_CHUNK",
    "CHAT_MESSAGE_HIDDEN",
    "CHAT_MESSAGE_UPSERTED",
    "CONTEXT_USAGE",
    "EXECUTION_CONTROL",
    "TRACE_UPDATE",
    "TURN_UX_PLAN",
    "agent_response_chunk_payload",
    "agent_response_payload",
    "build_notification_record",
    "chat_message_hidden_payload",
    "chat_message_upsert_payload",
    "context_usage_payload",
    "execution_control_payload",
    "trace_update_payload",
    "turn_ux_plan_payload",
]
