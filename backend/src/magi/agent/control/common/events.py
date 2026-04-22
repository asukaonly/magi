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

from ....core.logger import get_logger
from ....core.runtime_bindings import require_runtime_trace_store

logger = get_logger(__name__)

__all__ = [
    "publish_control_event",
]


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
        store = require_runtime_trace_store()
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

    from ....runtime_trace.contracts import RuntimeNotificationRecord

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
