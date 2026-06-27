"""Runtime notifications for background task state changes."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ...core.logger import get_logger
from ...runtime_trace import RuntimeNotificationRecord
from ...runtime_trace.provider import resolve_runtime_trace_store

if TYPE_CHECKING:
    from .contracts import BackgroundTask

logger = get_logger(__name__)


async def broadcast_background_task_state_changed(task: "BackgroundTask | Any") -> None:
    """Write a background-task state change notification for the UI bridge."""
    try:
        payload = task.to_dict()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed to serialize background task", error=str(exc))
        return
    user_id = str(getattr(task.spec, "user_id", "") or "")
    session_id = str(getattr(task.spec, "session_id", "") or "")
    try:
        store = resolve_runtime_trace_store()
        await store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="background_task_state_changed",
                user_id=user_id,
                session_id=session_id,
                payload_json=json.dumps(payload, default=str),
            )
        )
    except Exception as exc:
        logger.debug(
            "Failed to write background_task_state_changed notification",
            error=str(exc),
        )


__all__ = ["broadcast_background_task_state_changed"]
