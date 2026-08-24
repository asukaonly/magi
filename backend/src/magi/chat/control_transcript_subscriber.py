"""Project control-plane state-change events into durable chat transcript rows.

Control-Plane Extraction Phase 1. The control-actuator tools (enter/exit plan
mode and ``ask_user_question``) used to call ``persist_*`` helpers
in ``magi.control.chat_state_persister`` directly, which forced the
control package to import chat/transport. That dependency is now inverted: the
tools publish control state-change events on the L3 event bus (a legal downward
edge), and this chat-side subscriber owns the transcript projection.

The remaining projections are user-facing interactions. Runtime plans are
projected from canonical agent-run events and never stored as transcript rows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ..core.operation_barrier import AsyncOperationBarrier
from ..events.domain_payloads import (
    AskSnapshot,
    ControlAskAnswered,
    ControlAskRequested,
    ControlPlanStateChanged,
)
from ..events.events import Event, EventTypes, published_memory_epoch
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


def _get_chat_store_or_none() -> Any | None:
    try:
        return get_chat_store()
    except RuntimeError:
        return None


async def _next_sequence_no(
    chat_store: Any,
    *,
    previous_message: ChatMessageRecord | None,
    session_id: str,
) -> int:
    if previous_message is not None:
        return previous_message.sequence_no
    return await chat_store.next_sequence_no(session_id=session_id)


async def _append_message_and_bump(
    chat_store: Any,
    *,
    message: ChatMessageRecord,
    session_id: str,
) -> None:
    await chat_store.append_message(message)
    await chat_store.bump_history_version(session_id)


async def _broadcast_upsert_safely(
    *,
    message: ChatMessageRecord,
    session_id: str,
    log_key: str,
) -> None:
    try:
        await broadcast_chat_message_upsert(
            user_id=message.user_id,
            session_id=session_id,
            message_id=message.message_id,
        )
    except Exception:
        logger.debug(log_key, exc_info=True)


def _ask_request_inputs(session_id: str, ask: Any) -> tuple[str, str, str] | None:
    normalized_session_id = str(session_id or "").strip()
    request_id = str(getattr(ask, "request_id", "") or "").strip()
    question = str(getattr(ask, "question", "") or "").strip()
    if not normalized_session_id or not request_id or not question:
        return None
    return normalized_session_id, request_id, question


def _ask_response_inputs(
    session_id: str,
    ask: Any,
    answer: str,
) -> tuple[str, str, str] | None:
    normalized_session_id = str(session_id or "").strip()
    request_id = str(getattr(ask, "request_id", "") or "").strip()
    answer_text = str(answer or "").strip()
    if not normalized_session_id or not request_id or not answer_text:
        return None
    return normalized_session_id, request_id, answer_text


def _ask_response_payload(
    *,
    request_id: str,
    session_id: str,
    ask: Any,
    answer_text: str,
) -> dict[str, Any]:
    return {
        "ask_request_id": request_id,
        "session_id": session_id,
        "answer": answer_text,
        "answered_at_ms": _coerce_created_at_ms(getattr(ask, "answered_at", None)),
    }


async def _build_ask_request_message(
    chat_store: Any,
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    request_id: str,
    question: str,
    ask: Any,
    background: bool,
    previous_message: ChatMessageRecord | None,
) -> ChatMessageRecord:
    created_at_ms = _coerce_created_at_ms(getattr(ask, "asked_at", None)) or _now_ms()
    sequence_no = await _next_sequence_no(
        chat_store,
        previous_message=previous_message,
        session_id=session_id,
    )
    payload = _ask_state_payload(session_id=session_id, ask=ask, background=background)
    return ChatMessageRecord(
        message_id=_ask_request_message_id(request_id),
        session_id=session_id,
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


async def _build_ask_response_message(
    chat_store: Any,
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    request_id: str,
    answer_text: str,
    ask: Any,
    ask_message_id: str,
    previous_message: ChatMessageRecord | None,
) -> ChatMessageRecord:
    created_at_ms = _coerce_created_at_ms(getattr(ask, "answered_at", None)) or _now_ms()
    sequence_no = await _next_sequence_no(
        chat_store,
        previous_message=previous_message,
        session_id=session_id,
    )
    payload = _ask_response_payload(
        request_id=request_id,
        session_id=session_id,
        ask=ask,
        answer_text=answer_text,
    )
    return ChatMessageRecord(
        message_id=_ask_response_message_id(request_id),
        session_id=session_id,
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


async def persist_ask_request_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    background: bool = False,
) -> str | None:
    inputs = _ask_request_inputs(session_id, ask)
    if inputs is None:
        return None
    normalized_session_id, request_id, question = inputs

    chat_store = _get_chat_store_or_none()
    if chat_store is None:
        return None

    message_id = _ask_request_message_id(request_id)
    previous_message = await chat_store.get_message(message_id)
    next_message = await _build_ask_request_message(
        chat_store,
        session_id=normalized_session_id,
        user_id=user_id,
        turn_id=turn_id,
        request_id=request_id,
        question=question,
        ask=ask,
        background=background,
        previous_message=previous_message,
    )
    await _append_message_and_bump(
        chat_store,
        message=next_message,
        session_id=normalized_session_id,
    )
    await _broadcast_upsert_safely(
        message=next_message,
        session_id=normalized_session_id,
        log_key="ask_request_message.broadcast_failed",
    )
    return next_message.message_id


async def _ask_reply_target_message_id(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    background: bool,
    request_id: str,
) -> str:
    ask_message_id = await persist_ask_request_message(
        session_id=session_id,
        user_id=user_id,
        turn_id=turn_id,
        ask=ask,
        background=background,
    )
    return ask_message_id or _ask_request_message_id(request_id)


async def persist_ask_response_message(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    answer: str,
    background: bool = False,
) -> str | None:
    inputs = _ask_response_inputs(session_id, ask, answer)
    if inputs is None:
        return None
    normalized_session_id, request_id, answer_text = inputs

    ask_message_id = await _ask_reply_target_message_id(
        session_id=normalized_session_id,
        user_id=user_id,
        turn_id=turn_id,
        ask=ask,
        background=background,
        request_id=request_id,
    )

    chat_store = _get_chat_store_or_none()
    if chat_store is None:
        return None

    previous_message = await chat_store.get_message(_ask_response_message_id(request_id))
    next_message = await _build_ask_response_message(
        chat_store,
        session_id=normalized_session_id,
        user_id=user_id,
        turn_id=turn_id,
        request_id=request_id,
        answer_text=answer_text,
        ask=ask,
        ask_message_id=ask_message_id,
        previous_message=previous_message,
    )
    await _append_message_and_bump(
        chat_store,
        message=next_message,
        session_id=normalized_session_id,
    )
    await _broadcast_upsert_safely(
        message=next_message,
        session_id=normalized_session_id,
        log_key="ask_response_message.broadcast_failed",
    )
    return next_message.message_id


async def _status_message_context(
    *,
    session_id: str,
    turn_id: str | None,
    message_kind: str,
) -> tuple[str, str | None, Any, ChatMessageRecord | None] | None:
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip() or None
    if not normalized_session_id:
        return None
    chat_store = _get_chat_store_or_none()
    if chat_store is None:
        return None
    previous_message = await _latest_status_message(
        chat_store,
        turn_id=normalized_turn_id,
        message_kind=message_kind,
    )
    return normalized_session_id, normalized_turn_id, chat_store, previous_message


async def _latest_status_message(
    chat_store: Any,
    *,
    turn_id: str | None,
    message_kind: str,
) -> ChatMessageRecord | None:
    if not turn_id:
        return None
    return await chat_store.get_latest_message_for_turn(
        turn_id,
        message_kind=message_kind,
    )


def _status_message_is_unchanged(
    previous_message: ChatMessageRecord | None,
    *,
    payload: dict[str, Any],
    content_text: str | None,
) -> bool:
    if previous_message is None or not previous_message.is_visible:
        return False
    return _payload_json_matches(previous_message.payload_json, payload) and _normalize_optional_text(
        previous_message.content_text
    ) == _normalize_optional_text(content_text)


async def _build_status_message(
    chat_store: Any,
    *,
    session_id: str,
    turn_id: str | None,
    user_id: str | None,
    message_kind: str,
    payload: dict[str, Any],
    content_text: str | None,
    created_at_ms: int | None,
    previous_message: ChatMessageRecord | None,
) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=f"msg_{uuid.uuid4().hex[:16]}",
        session_id=session_id,
        turn_id=turn_id,
        user_id=_resolve_user_id(user_id),
        role="assistant",
        message_kind=message_kind,
        content_text=content_text,
        payload_json=json.dumps(payload, ensure_ascii=False),
        is_final=True,
        is_visible=True,
        created_at_ms=int(created_at_ms or 0) or _now_ms(),
        sequence_no=await chat_store.next_sequence_no(session_id=session_id),
        replaces_message_id=previous_message.message_id if previous_message is not None else None,
        replaced_by_message_id=None,
        reply_to_message_id=None,
    )


async def _append_status_message(
    chat_store: Any,
    *,
    session_id: str,
    next_message: ChatMessageRecord,
    previous_message: ChatMessageRecord | None,
) -> None:
    await _append_message_and_bump(
        chat_store,
        message=next_message,
        session_id=session_id,
    )
    if previous_message is not None:
        await chat_store.mark_message_replaced(
            message_id=previous_message.message_id,
            replaced_by_message_id=next_message.message_id,
        )


async def _broadcast_status_message_change(
    *,
    next_message: ChatMessageRecord,
    previous_message: ChatMessageRecord | None,
    session_id: str,
) -> None:
    try:
        if previous_message is not None:
            await broadcast_chat_message_hidden(
                user_id=next_message.user_id,
                session_id=session_id,
                message_id=previous_message.message_id,
            )
        await broadcast_chat_message_upsert(
            user_id=next_message.user_id,
            session_id=session_id,
            message_id=next_message.message_id,
        )
    except Exception:
        logger.debug("control_status_message.broadcast_failed", exc_info=True)


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
    context = await _status_message_context(
        session_id=session_id,
        turn_id=turn_id,
        message_kind=message_kind,
    )
    if context is None:
        return None
    normalized_session_id, normalized_turn_id, chat_store, previous_message = context
    if _status_message_is_unchanged(
        previous_message,
        payload=payload,
        content_text=content_text,
    ):
        return previous_message.message_id if previous_message is not None else None

    next_message = await _build_status_message(
        chat_store,
        session_id=normalized_session_id,
        turn_id=normalized_turn_id,
        user_id=user_id,
        message_kind=message_kind,
        payload=payload,
        content_text=content_text,
        created_at_ms=created_at_ms,
        previous_message=previous_message,
    )
    await _append_status_message(
        chat_store,
        session_id=normalized_session_id,
        next_message=next_message,
        previous_message=previous_message,
    )
    await _broadcast_status_message_change(
        next_message=next_message,
        previous_message=previous_message,
        session_id=normalized_session_id,
    )
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

    def __init__(
        self,
        *,
        event_bus,
        memory_epoch_getter: Callable[[], int] | None = None,
    ) -> None:
        self._bus = event_bus
        self._memory_epoch_getter = memory_epoch_getter
        self._sub_ids: list[str] = []
        self._inflight: set[asyncio.Task] = set()
        self._serialize_lock = asyncio.Lock()
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0
        self._clear_request_count = 0
        self._clear_cutoff_event_timestamp = 0.0

    async def start(self) -> None:
        self._sub_ids.append(
            await self._bus.subscribe(
                EventTypes.CONTROL_PLAN_STATE_CHANGED, self._on_plan_state_changed
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

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Drain admitted projections and reject events crossing a full clear."""
        self._clear_request_count += 1
        self._clear_generation += 1
        try:
            async with self._clear_barrier.exclusive():
                yield
        finally:
            self._clear_cutoff_event_timestamp = max(
                self._clear_cutoff_event_timestamp,
                time.time(),
            )
            self._clear_request_count -= 1

    # -- event handlers -----------------------------------------------------

    async def _on_plan_state_changed(self, event: Event) -> None:
        if not self._admits_event(event):
            return
        try:
            payload = expect_payload(event, ControlPlanStateChanged)
        except PayloadTypeError:
            logger.exception("malformed ControlPlanStateChanged payload")
            return
        self._spawn(lambda: self._project_plan_state(payload))

    async def _on_ask_requested(self, event: Event) -> None:
        if not self._admits_event(event):
            return
        try:
            payload = expect_payload(event, ControlAskRequested)
        except PayloadTypeError:
            logger.exception("malformed ControlAskRequested payload")
            return
        self._spawn(lambda: self._project_ask_requested(payload))

    async def _on_ask_answered(self, event: Event) -> None:
        if not self._admits_event(event):
            return
        try:
            payload = expect_payload(event, ControlAskAnswered)
        except PayloadTypeError:
            logger.exception("malformed ControlAskAnswered payload")
            return
        self._spawn(lambda: self._project_ask_answered(payload))

    # -- projection (serialized + error-isolated) ---------------------------

    def _spawn(self, operation: Callable[[], Awaitable[None]]) -> None:
        generation = self._clear_generation
        task = asyncio.create_task(self._serialized(operation, generation))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _serialized(
        self,
        operation: Callable[[], Awaitable[None]],
        generation: int,
    ) -> None:
        try:
            async with self._serialize_lock:
                async with self._clear_barrier.operation():
                    if generation != self._clear_generation:
                        return
                    await operation()
        except Exception:
            logger.exception("control transcript projection failed")

    def _admits_event(self, event: Event) -> bool:
        if self._clear_request_count > 0:
            return False
        if event.timestamp <= self._clear_cutoff_event_timestamp:
            return False
        if self._memory_epoch_getter is None:
            return True
        event_epoch = published_memory_epoch(event)
        if event_epoch is None:
            return True
        try:
            return event_epoch == int(self._memory_epoch_getter())
        except Exception:
            logger.exception("control transcript memory epoch resolution failed")
            return False

    async def _project_plan_state(self, p: ControlPlanStateChanged) -> None:
        await persist_plan_state_message(
            session_id=p.session_id,
            user_id=p.user_id,
            turn_id=p.turn_id,
            state=dict(p.state),
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
]
