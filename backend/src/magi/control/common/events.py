"""Best-effort control-plane event publisher.

Writes control-plane interaction events (``control.permission.requested``,
``control.ask.requested``, ``control.todo.updated``, ``control.plan.updated``)
into the runtime trace store as :class:`RuntimeNotificationRecord`s so the
Rust gateway / websocket bridge can push them to the desktop UI.

Usage is intentionally fire-and-forget: failures are logged and swallowed
so they can never break the control-plane decision path.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ...core.logger import get_logger
from ...runtime_trace.provider import resolve_runtime_trace_store

logger = get_logger(__name__)

__all__ = [
    "publish_control_event",
    "publish_control_plan_state_changed",
    "publish_control_todo_state_changed",
    "publish_control_ask_requested",
    "publish_control_ask_answered",
]


def _ask_snapshot(ask: Any) -> Any:
    """Build the bus-carried snapshot of a control ``AskState``.

    Reads the same attributes the transcript projector reads off the ask
    object, so the chat-side subscriber can rebuild an equivalent view
    without importing control code. Imported lazily because
    ``magi.events`` is a lower layer reached only from this publisher.
    """
    from ...events.domain_payloads import AskSnapshot

    return AskSnapshot(
        request_id=str(getattr(ask, "request_id", "") or ""),
        question=str(getattr(ask, "question", "") or ""),
        options=tuple(str(item) for item in getattr(ask, "options", ())),
        allow_free_text=bool(getattr(ask, "allow_free_text", True)),
        asked_at=getattr(ask, "asked_at", None),
        timeout_seconds=getattr(ask, "timeout_seconds", None),
        expires_at=getattr(ask, "expires_at", None),
        answered_at=getattr(ask, "answered_at", None),
        answer=getattr(ask, "answer", None),
        resolution=getattr(ask, "resolution", None),
        status=str(getattr(ask, "status", "pending") or "pending"),
    )


async def _publish_control_state_event(event_type: str, payload: Any) -> None:
    """Publish a control state-change event on the L3 message bus.

    Fire-and-forget like :func:`publish_control_event`: a missing or
    not-yet-wired bus (e.g. tests, smoke harnesses) logs at DEBUG and
    returns. Transcript projection is owned by the chat-side subscriber that
    consumes these events; the control plane never depends on the bus for
    correctness of its own decision path.
    """
    try:
        from ...events.events import Event
        from ...core.container import get_container

        bus = get_container().message_bus()
        if bus is None or not hasattr(bus, "publish"):
            logger.debug("control_state_event.no_bus", event_type=event_type)
            return
        await bus.publish(
            Event(type=event_type, data=payload, source="control")
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("control_state_event.publish_failed", event_type=event_type, exc_info=True)


async def publish_control_plan_state_changed(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    state: dict[str, Any],
) -> None:
    """Emit ``CONTROL_PLAN_STATE_CHANGED`` for the chat transcript subscriber."""
    from ...events.domain_payloads import ControlPlanStateChanged
    from ...events.events import EventTypes

    await _publish_control_state_event(
        EventTypes.CONTROL_PLAN_STATE_CHANGED,
        ControlPlanStateChanged(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            state=dict(state),
        ),
    )


async def publish_control_todo_state_changed(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    plan: dict[str, Any],
) -> None:
    """Emit ``CONTROL_TODO_STATE_CHANGED`` for the chat transcript subscriber."""
    from ...events.domain_payloads import ControlTodoStateChanged
    from ...events.events import EventTypes

    await _publish_control_state_event(
        EventTypes.CONTROL_TODO_STATE_CHANGED,
        ControlTodoStateChanged(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            plan=dict(plan),
        ),
    )


async def publish_control_ask_requested(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    background: bool = False,
) -> None:
    """Emit ``CONTROL_ASK_REQUESTED`` for the chat transcript subscriber."""
    from ...events.domain_payloads import ControlAskRequested
    from ...events.events import EventTypes

    await _publish_control_state_event(
        EventTypes.CONTROL_ASK_REQUESTED,
        ControlAskRequested(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            ask=_ask_snapshot(ask),
            background=background,
        ),
    )


async def publish_control_ask_answered(
    *,
    session_id: str,
    user_id: str | None,
    turn_id: str | None,
    ask: Any,
    answer: str,
    background: bool = False,
) -> None:
    """Emit ``CONTROL_ASK_ANSWERED`` for the chat transcript subscriber."""
    from ...events.domain_payloads import ControlAskAnswered
    from ...events.events import EventTypes

    await _publish_control_state_event(
        EventTypes.CONTROL_ASK_ANSWERED,
        ControlAskAnswered(
            session_id=session_id,
            user_id=user_id,
            turn_id=turn_id,
            ask=_ask_snapshot(ask),
            answer=answer,
            background=background,
        ),
    )


async def publish_control_event(
    channel: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    turn_id: str | None = None,
) -> None:
    """Emit a control-plane notification into the runtime trace store.

    Every argument is treated defensively: missing trace store, missing
    session/user, or serialisation errors log at INFO/WARNING and return
    without raising. The caller must never depend on this helper for
    correctness — it is purely observability / UI push.
    """
    try:
        store = resolve_runtime_trace_store()
    except RuntimeError:
        # Control plane is up but the trace store is not — fine outside
        # of the full runtime (tests, smoke harnesses).
        logger.debug("control_event.no_trace_store", channel=channel)
        return

    try:
        payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception as exc:  # pragma: no cover - payload serialisation failure
        logger.warning(
            "control_event.serialise_failed",
            channel=channel,
            error=str(exc),
        )
        return

    from ...runtime_trace.contracts import RuntimeNotificationRecord

    record = RuntimeNotificationRecord(
        notification_id=0,  # assigned by the store
        channel=channel,
        user_id=str(user_id or ""),
        session_id=str(session_id or ""),
        turn_id=turn_id,
        payload_json=payload_json,
        created_at_ms=int(time.time() * 1000),
    )

    try:
        await store.append_notification(record)
    except Exception as exc:
        logger.warning(
            "control_event.append_failed",
            channel=channel,
            session_id=session_id,
            error=str(exc),
        )
