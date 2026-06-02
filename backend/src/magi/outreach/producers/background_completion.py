"""Map terminal BackgroundTask -> OutreachIntent and submit to OutreachService.

Registered as a BackgroundTaskManager listener (replaces the desktop-only
completion handshake). Exceptions are swallowed (listener isolation)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ...agent.background import BackgroundTask, BackgroundTaskStatus, BackgroundTaskTriggerSource
from ...agent.trace import now_wall_ms
from ...core.logger import get_logger
from ..contracts import OutreachIntent, OutreachKind, Urgency

logger = get_logger(__name__)

_HIGH_URGENCY_TRIGGERS = {BackgroundTaskTriggerSource.USER, BackgroundTaskTriggerSource.MANUAL}

_STATUS_TO_KIND = {
    BackgroundTaskStatus.SUCCEEDED: OutreachKind.TASK_COMPLETED,
    BackgroundTaskStatus.FAILED: OutreachKind.TASK_FAILED,
    BackgroundTaskStatus.CANCELLED: OutreachKind.TASK_CANCELLED,
}


def task_to_intent(task: BackgroundTask) -> OutreachIntent | None:
    spec = task.spec
    session_id = str(spec.session_id or "").strip()
    user_id = str(spec.user_id or "").strip()
    if not session_id or not user_id:
        return None
    kind = _STATUS_TO_KIND.get(task.status)
    if kind is None:
        return None

    if task.status is BackgroundTaskStatus.SUCCEEDED:
        facts = (task.summary or "").strip()
    elif task.status is BackgroundTaskStatus.FAILED:
        facts = (task.error or "").strip() or "unknown error"
    else:
        facts = (getattr(task, "cancel_reason", "") or "").strip() or "cancelled"

    finished = task.finished_at if task.finished_at is not None else task.updated_at
    completed_at_ms = int(finished * 1000) if finished else now_wall_ms()
    title = (spec.title or "").strip() or "Background task"

    payload = {
        "background_task_id": task.task_id,
        "background_task_status": task.status.value,
        "background_task_title": title,
        "background_task_attempt": int(getattr(task, "attempt_index", 0)),
        "trigger_source": spec.trigger_source.value,
    }
    urgency = Urgency.HIGH if spec.trigger_source in _HIGH_URGENCY_TRIGGERS else Urgency.NORMAL

    return OutreachIntent(
        kind=kind, user_id=user_id, origin_session_id=session_id, title=title,
        facts=facts, correlation_id=task.task_id, completed_at_ms=completed_at_ms,
        pending_message_id=(spec.pending_message_id or "").strip() or None,
        urgency=urgency, payload=payload,
    )


def build_background_completion_producer(service: Any) -> Callable[[BackgroundTask], Awaitable[None]]:
    async def _on_complete(task: BackgroundTask) -> None:
        try:
            intent = task_to_intent(task)
            if intent is None:
                return
            await service.submit(intent)
        except Exception:
            logger.warning("outreach: background completion producer failed", exc_info=True)

    return _on_complete
