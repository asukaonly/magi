"""Project control-plane state-change events into durable chat transcript rows.

Control-Plane Extraction Phase 1. The control-actuator tools (enter/exit plan
mode, ``todo_write``, ``ask_user_question``) used to call ``persist_*`` helpers
in ``magi.control.chat_state_persister`` directly, which forced the
control package to import chat/transport. That dependency is now inverted: the
tools publish control state-change events on the L3 event bus (a legal downward
edge), and this chat-side subscriber owns the transcript projection.

The persistence logic below is MOVED VERBATIM from the former
``chat_state_persister`` module — its dedup / replace / hide / threading
semantics are behaviour-bearing and a golden parity test guards byte-identical
output. Do not rewrite it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Iterable

from ..events.domain_payloads import (
    AskSnapshot,
    ControlAskAnswered,
    ControlAskRequested,
    ControlPlanStateChanged,
    ControlTodoStateChanged,
)
from ..events.events import Event, EventTypes
from ..events.payload_helpers import expect_payload, PayloadTypeError
from ..identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
from .contracts import ChatMessageRecord
from .message_notifications import (
    broadcast_chat_message_hidden,
    broadcast_chat_message_upsert,
)
from .provider import get_chat_store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers (moved verbatim from chat_state_persister).
# ---------------------------------------------------------------------------


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


def _ask_request_message_id(request_id: str) -> str:
    return f"ask:{request_id}"


def _ask_response_message_id(request_id: str) -> str:
    return f"ask-response:{request_id}"


class _AskView:
    """Read-only view exposing ``AskSnapshot`` fields via attribute access.

    The transcript projector reads the ask object purely through ``getattr``;
    rebuilding a lightweight namespace from the event snapshot keeps the moved
    persistence logic byte-identical without importing control's ``AskState``.
    """

    __slots__ = (
        "request_id",
        "question",
        "options",
        "allow_free_text",
        "asked_at",
        "timeout_seconds",
        "expires_at",
        "answered_at",
        "answer",
        "resolution",
        "status",
    )

    def __init__(self, snapshot: AskSnapshot) -> None:
        self.request_id = snapshot.request_id
        self.question = snapshot.question
        self.options = tuple(snapshot.options)
        self.allow_free_text = snapshot.allow_free_text
        self.asked_at = snapshot.asked_at
        self.timeout_seconds = snapshot.timeout_seconds
        self.expires_at = snapshot.expires_at
        self.answered_at = snapshot.answered_at
        self.answer = snapshot.answer
        self.resolution = snapshot.resolution
        self.status = snapshot.status


def _ask_state_payload(
    *,
    session_id: str,
    ask: Any,
    background: bool,
) -> dict[str, Any]:
    asked_at_ms = _coerce_created_at_ms(getattr(ask, "asked_at", None))
    answered_at_ms = _coerce_created_at_ms(getattr(ask, "answered_at", None))
    expires_at_ms = _coerce_created_at_ms(getattr(ask, "expires_at", None))
    return {
        "ask_request_id": str(getattr(ask, "request_id", "") or "").strip(),
        "session_id": session_id,
        "status": str(getattr(ask, "status", "pending") or "pending").strip() or "pending",
        "question": str(getattr(ask, "question", "") or "").strip(),
        "options": [str(item).strip() for item in getattr(ask, "options", ()) if str(item).strip()],
        "allow_free_text": bool(getattr(ask, "allow_free_text", True)),
        "timeout_seconds": getattr(ask, "timeout_seconds", None),
        "created_at_ms": asked_at_ms,
        "expires_at_ms": expires_at_ms,
        "answered_at_ms": answered_at_ms,
        "answer": getattr(ask, "answer", None),
        "resolution": getattr(ask, "resolution", None),
        "background": bool(background),
    }


# ---------------------------------------------------------------------------
# Projectors (moved verbatim from chat_state_persister).
# ---------------------------------------------------------------------------


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


async def persist_ask_request_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    background: bool = False,
) -> str | None:
    normalized_session_id = str(session_id or "").strip()
    request_id = str(getattr(ask, "request_id", "") or "").strip()
    question = str(getattr(ask, "question", "") or "").strip()
    if not normalized_session_id or not request_id or not question:
        return None

    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return None

    message_id = _ask_request_message_id(request_id)
    previous_message = await chat_store.get_message(message_id)
    created_at_ms = _coerce_created_at_ms(getattr(ask, "asked_at", None)) or _now_ms()
    sequence_no = (
        previous_message.sequence_no
        if previous_message is not None
        else await chat_store.next_sequence_no(session_id=normalized_session_id)
    )
    payload = _ask_state_payload(session_id=normalized_session_id, ask=ask, background=background)

    next_message = ChatMessageRecord(
        message_id=message_id,
        session_id=normalized_session_id,
        turn_id=str(turn_id or "").strip() or None,
        user_id=_resolve_user_id(user_id),
        role="assistant",
        message_kind="ask_request",
        content_text=question,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=previous_message.created_at_ms if previous_message is not None else created_at_ms,
        sequence_no=sequence_no,
        replaces_message_id=None,
        replaced_by_message_id=None,
        reply_to_message_id=None,
        persona_id=previous_message.persona_id if previous_message is not None else None,
    )
    await chat_store.append_message(next_message)
    await chat_store.bump_history_version(normalized_session_id)
    try:
        await broadcast_chat_message_upsert(
            user_id=next_message.user_id,
            session_id=normalized_session_id,
            message_id=next_message.message_id,
        )
    except Exception:
        logger.debug("ask_request_message.broadcast_failed", exc_info=True)
    return next_message.message_id


async def persist_ask_response_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    answer: str,
    background: bool = False,
) -> str | None:
    normalized_session_id = str(session_id or "").strip()
    request_id = str(getattr(ask, "request_id", "") or "").strip()
    answer_text = str(answer or "").strip()
    if not normalized_session_id or not request_id or not answer_text:
        return None

    ask_message_id = await persist_ask_request_message(
        session_id=normalized_session_id,
        user_id=user_id,
        turn_id=turn_id,
        ask=ask,
        background=background,
    )
    if ask_message_id is None:
        ask_message_id = _ask_request_message_id(request_id)

    try:
        chat_store = get_chat_store()
    except RuntimeError:
        return None

    message_id = _ask_response_message_id(request_id)
    previous_message = await chat_store.get_message(message_id)
    created_at_ms = _coerce_created_at_ms(getattr(ask, "answered_at", None)) or _now_ms()
    sequence_no = (
        previous_message.sequence_no
        if previous_message is not None
        else await chat_store.next_sequence_no(session_id=normalized_session_id)
    )
    payload = {
        "ask_request_id": request_id,
        "session_id": normalized_session_id,
        "answer": answer_text,
        "answered_at_ms": _coerce_created_at_ms(getattr(ask, "answered_at", None)),
    }
    next_message = ChatMessageRecord(
        message_id=message_id,
        session_id=normalized_session_id,
        turn_id=str(turn_id or "").strip() or None,
        user_id=_resolve_user_id(user_id),
        role="user",
        message_kind="ask_response",
        content_text=answer_text,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=previous_message.created_at_ms if previous_message is not None else created_at_ms,
        sequence_no=sequence_no,
        replaces_message_id=None,
        replaced_by_message_id=None,
        reply_to_message_id=ask_message_id,
        persona_id=None,
    )
    await chat_store.append_message(next_message)
    await chat_store.bump_history_version(normalized_session_id)
    try:
        await broadcast_chat_message_upsert(
            user_id=next_message.user_id,
            session_id=normalized_session_id,
            message_id=next_message.message_id,
        )
    except Exception:
        logger.debug("ask_response_message.broadcast_failed", exc_info=True)
    return next_message.message_id


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
        if _payload_json_matches(previous_message.payload_json, payload) and _normalize_optional_text(
            previous_message.content_text
        ) == _normalize_optional_text(content_text):
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


# ---------------------------------------------------------------------------
# Subscriber wiring.
# ---------------------------------------------------------------------------


class ControlTranscriptSubscriber:
    """Subscribe to control state-change events; project them into the transcript.

    Mirrors :class:`magi.runtime_trace.subscribers.RuntimeTraceSubscriber`:
    one ``subscribe`` per event type, handler errors caught and logged, and an
    in-flight set drained on ``stop`` so a clean shutdown completes pending
    transcript writes. Projection per subscriber is serialized so successive
    events for the same turn (e.g. an ask request then its answer) apply in
    publish order.
    """

    def __init__(self, *, event_bus) -> None:
        self._bus = event_bus
        self._sub_ids: list[str] = []
        self._inflight: set[asyncio.Task] = set()
        self._serialize_lock = asyncio.Lock()

    async def start(self) -> None:
        self._sub_ids.append(
            await self._bus.subscribe(
                EventTypes.CONTROL_PLAN_STATE_CHANGED, self._on_plan_state_changed
            )
        )
        self._sub_ids.append(
            await self._bus.subscribe(
                EventTypes.CONTROL_TODO_STATE_CHANGED, self._on_todo_state_changed
            )
        )
        self._sub_ids.append(
            await self._bus.subscribe(
                EventTypes.CONTROL_ASK_REQUESTED, self._on_ask_requested
            )
        )
        self._sub_ids.append(
            await self._bus.subscribe(
                EventTypes.CONTROL_ASK_ANSWERED, self._on_ask_answered
            )
        )

    async def stop(self) -> None:
        for sub_id in self._sub_ids:
            try:
                await self._bus.unsubscribe(sub_id)
            except Exception:
                logger.exception("unsubscribe failed")
        self._sub_ids = []
        await self.drain()

    async def drain(self) -> None:
        if not self._inflight:
            return
        await asyncio.gather(*list(self._inflight), return_exceptions=True)

    # -- event handlers -----------------------------------------------------

    async def _on_plan_state_changed(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlPlanStateChanged)
        except PayloadTypeError:
            logger.exception("malformed ControlPlanStateChanged payload")
            return
        self._spawn(self._project_plan_state(payload))

    async def _on_todo_state_changed(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlTodoStateChanged)
        except PayloadTypeError:
            logger.exception("malformed ControlTodoStateChanged payload")
            return
        self._spawn(self._project_todo_state(payload))

    async def _on_ask_requested(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlAskRequested)
        except PayloadTypeError:
            logger.exception("malformed ControlAskRequested payload")
            return
        self._spawn(self._project_ask_requested(payload))

    async def _on_ask_answered(self, event: Event) -> None:
        try:
            payload = expect_payload(event, ControlAskAnswered)
        except PayloadTypeError:
            logger.exception("malformed ControlAskAnswered payload")
            return
        self._spawn(self._project_ask_answered(payload))

    # -- projection (serialized + error-isolated) ---------------------------

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(self._serialized(coro))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _serialized(self, coro) -> None:
        async with self._serialize_lock:
            try:
                await coro
            except Exception:
                logger.exception("control transcript projection failed")

    async def _project_plan_state(self, p: ControlPlanStateChanged) -> None:
        await persist_plan_state_message(
            session_id=p.session_id,
            user_id=p.user_id,
            turn_id=p.turn_id,
            state=dict(p.state),
        )

    async def _project_todo_state(self, p: ControlTodoStateChanged) -> None:
        await persist_todo_state_message(
            session_id=p.session_id,
            user_id=p.user_id,
            turn_id=p.turn_id,
            items=[dict(item) for item in p.items],
            orchestration_id=p.orchestration_id,
        )

    async def _project_ask_requested(self, p: ControlAskRequested) -> None:
        await persist_ask_request_message(
            session_id=p.session_id,
            user_id=p.user_id,
            turn_id=p.turn_id,
            ask=_AskView(p.ask),
            background=p.background,
        )

    async def _project_ask_answered(self, p: ControlAskAnswered) -> None:
        await persist_ask_response_message(
            session_id=p.session_id,
            user_id=p.user_id,
            turn_id=p.turn_id,
            ask=_AskView(p.ask),
            answer=p.answer,
            background=p.background,
        )


__all__ = [
    "ControlTranscriptSubscriber",
    "persist_ask_request_message",
    "persist_ask_response_message",
    "persist_plan_state_message",
    "persist_todo_state_message",
]
