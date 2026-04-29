"""Persist control-plane state as durable chat status messages."""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable

from ...chat import ChatMessageRecord
from ...chat.provider import get_chat_store
from ...core.logger import get_logger
from ...runtime_defaults import DEFAULT_USER_ID
from ...transport.chat_events import (
    broadcast_chat_message_hidden,
    broadcast_chat_message_upsert,
)

logger = get_logger(__name__)


def _resolve_user_id(user_id: str | None) -> str:
    normalized = str(user_id or "").strip()
    return normalized or DEFAULT_USER_ID


def _coerce_created_at_ms(value: Any) -> int | None:
    try:
                if value is None or value == "":
                        return None
                numeric = float(value)
    except (TypeError, ValueError):
                return None
    if numeric <= 0:
        return None
    if numeric < 10_000_000_000:
        numeric *= 1000
    return int(numeric)


async def persist_plan_state_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    state: dict[str, Any],
) -> str | None:
    normalized_plan_text = str(state.get("plan_text") or "").strip() or None
    entered_at_ms = _coerce_created_at_ms(state.get("entered_at_ms"))
    if entered_at_ms is None:
        entered_at_ms = _coerce_created_at_ms(state.get("entered_at"))
    created_at_ms = entered_at_ms
    if created_at_ms is None:
        created_at_ms = _coerce_created_at_ms(state.get("exited_at_ms"))

    payload = {
        "active": bool(state.get("active")),
        "plan_text": normalized_plan_text,
        "entered_at_ms": entered_at_ms,
        "exited_at_ms": None if bool(state.get("active")) else (created_at_ms or entered_at_ms),
    }
    return await _persist_status_message(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        message_kind="plan_state",
        payload=payload,
        content_text=normalized_plan_text,
        created_at_ms=created_at_ms,
    )


async def persist_todo_state_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    items: Iterable[dict[str, Any]],
    orchestration_id: str | None = None,
) -> str | None:
    normalized_items = [dict(item) for item in items if isinstance(item, dict)]
    if not normalized_items:
        await _hide_latest_status_message(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            message_kind="todo_state",
        )
        return None

    latest_updated_ms = max(
        (
            _coerce_created_at_ms(item.get("updated_at_ms"))
            or _coerce_created_at_ms(item.get("created_at_ms"))
            or 0
        )
        for item in normalized_items
    )
    payload = {
        "items": normalized_items,
        "orchestration_id": str(orchestration_id or "").strip() or None,
    }
    content_text = "\n".join(
        str(item.get("content") or item.get("title") or "").strip()
        for item in normalized_items
        if str(item.get("content") or item.get("title") or "").strip()
    ) or None
    return await _persist_status_message(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        message_kind="todo_state",
        payload=payload,
        content_text=content_text,
        created_at_ms=latest_updated_ms or None,
    )


async def _persist_status_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    message_kind: str,
    payload: dict[str, Any],
    content_text: str | None,
    created_at_ms: int | None,
) -> str | None:
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip() or None
    if not normalized_session_id:
        return None

    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return None

    previous_message = None
    if normalized_turn_id:
        previous_message = await chat_store.get_latest_message_for_turn(
            normalized_turn_id,
            message_kind=message_kind,
        )
    if previous_message is not None and previous_message.is_visible:
        if _payload_json_matches(previous_message.payload_json, payload) and _normalize_optional_text(previous_message.content_text) == _normalize_optional_text(content_text):
            return previous_message.message_id

    next_message = ChatMessageRecord(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id=normalized_session_id,
        turn_id=normalized_turn_id,
        user_id=_resolve_user_id(user_id),
        role="assistant",
        message_kind=message_kind,
        content_text=content_text,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=int(created_at_ms or 0) or _now_ms(),
        sequence_no=await chat_store.next_sequence_no(session_id=normalized_session_id),
        replaces_message_id=previous_message.message_id if previous_message is not None else None,
        replaced_by_message_id=None,
        reply_to_message_id=None,
    )
    await chat_store.append_message(next_message)
    await chat_store.bump_history_version(normalized_session_id)

    if previous_message is not None:
        await chat_store.mark_message_replaced(
            message_id=previous_message.message_id,
            replaced_by_message_id=next_message.message_id,
        )

    try:
        if previous_message is not None:
            await broadcast_chat_message_hidden(
                user_id=next_message.user_id,
                session_id=normalized_session_id,
                message_id=previous_message.message_id,
            )
        await broadcast_chat_message_upsert(
            user_id=next_message.user_id,
            session_id=normalized_session_id,
            message_id=next_message.message_id,
        )
    except Exception:
        logger.debug("control_status_message.broadcast_failed", exc_info=True)
    return next_message.message_id


async def _hide_latest_status_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    message_kind: str,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip() or None
    if not normalized_session_id or not normalized_turn_id:
        return

    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return

    previous_message = await chat_store.get_latest_message_for_turn(
        normalized_turn_id,
        message_kind=message_kind,
    )
    if previous_message is None or not previous_message.is_visible:
        return

    hidden = await chat_store.hide_message(
        session_id=normalized_session_id,
        message_id=previous_message.message_id,
    )
    if hidden is None:
        return
    try:
        await broadcast_chat_message_hidden(
            user_id=_resolve_user_id(user_id),
            session_id=normalized_session_id,
            message_id=previous_message.message_id,
        )
    except Exception:
        logger.debug("control_status_message.hide_broadcast_failed", exc_info=True)


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _payload_json_matches(existing_payload_json: str | None, payload: dict[str, Any]) -> bool:
    raw = str(existing_payload_json or "").strip()
    if not raw:
        return False
    try:
        existing_payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return existing_payload == payload


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


__all__ = [
    "persist_plan_state_message",
    "persist_todo_state_message",
]