"""Map terminal BackgroundTask -> OutreachIntent and submit to OutreachService.

Registered as a BackgroundTaskManager listener (replaces the desktop-only
completion handshake). Exceptions are swallowed (listener isolation).

Batch-orchestrator runs get special handling (W3 dedup): a batch job is many
self-enqueued background runs, so notifying per run would spam the user. We stay
QUIET while the job still has pending/running items, and emit ONE job-level
report when the final batch leaves nothing pending/running. This is decided here
(not in the driver) so it doesn't depend on listener ordering — the producer
just reads the manifest.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from ...agent.background import BackgroundTask, BackgroundTaskStatus, BackgroundTaskTriggerSource
from ...agent.batch.runner import parse_job_id_from_goal
from ...agent.batch.store import default_batch_store
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


async def batch_job_intent(task: BackgroundTask, job_id: str) -> OutreachIntent | None:
    """Job-level notification for a batch run. Returns None for intermediate
    batches (job still has pending/running items) so only ONE report fires when
    the job is fully drained."""
    store = default_batch_store()
    counts = await store.status_counts(job_id)
    if counts.get("pending", 0) + counts.get("running", 0) > 0:
        return None  # mid-job — more batches coming; stay quiet
    job = await store.get_job(job_id)
    if job is None:
        return None

    done = counts.get("done", 0)
    review = counts.get("needs_review", 0)
    failed = counts.get("failed", 0)
    skipped = counts.get("skipped", 0)
    total = done + review + failed + skipped
    facts = f"{done}/{total} done"
    if review:
        facts += f", {review} need review"
    if failed:
        facts += f", {failed} failed"
    if skipped:
        facts += f", {skipped} skipped"

    kind = OutreachKind.TASK_COMPLETED if failed == 0 else OutreachKind.TASK_FAILED
    spec = task.spec
    return OutreachIntent(
        kind=kind,
        user_id=(str(spec.user_id or "").strip() or job.owner),
        origin_session_id=((str(spec.session_id or "").strip() or job.origin_session_id) or None),
        title=job.title,
        facts=facts,
        correlation_id=job_id,
        completed_at_ms=now_wall_ms(),
        pending_message_id=None,
        urgency=Urgency.NORMAL,
        payload={"batch_job_id": job_id, "counts": counts},
    )


def build_background_completion_producer(service: Any) -> Callable[[BackgroundTask], Awaitable[None]]:
    async def _on_complete(task: BackgroundTask) -> None:
        try:
            job_id = parse_job_id_from_goal(getattr(task.spec, "goal", "") or "")
            intent = await batch_job_intent(task, job_id) if job_id else task_to_intent(task)
            if intent is None:
                return
            await service.submit(intent)
        except Exception:
            logger.warning("outreach: background completion producer failed", exc_info=True)

    return _on_complete
