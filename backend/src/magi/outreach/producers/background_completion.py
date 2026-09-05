"""Map terminal BackgroundTask -> durable OutreachIntent delivery.

The producer is registered as a BackgroundTaskManager listener and also drains
completion intents left pending by a crash or by the startup interval before
the listener is attached.

Batch-orchestrator runs get special handling (W3 dedup): a batch job is many
self-enqueued background runs, so notifying per run would spam the user. We stay
QUIET while the job still has pending/running items, and emit ONE job-level
report when the final batch leaves nothing pending/running. This is decided here
(not in the driver) so it doesn't depend on listener ordering — the producer
just reads the manifest.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from uuid import uuid4

from ...agent.background import BackgroundTask, BackgroundTaskStatus, BackgroundTaskTriggerSource
from ...agent.batch.contracts import BatchRunIdentity
from ...agent.batch.store import default_batch_store
from ...agent.trace import now_wall_ms
from ...core.logger import get_logger
from ..contracts import OutreachIntent, OutreachKind, Urgency
from ..identity import canonical_intent_json

logger = get_logger(__name__)

_HIGH_URGENCY_TRIGGERS = {BackgroundTaskTriggerSource.USER, BackgroundTaskTriggerSource.MANUAL}
_MAX_COMPLETION_DRAIN_ITEMS = 500

_STATUS_TO_KIND = {
    BackgroundTaskStatus.SUCCEEDED: OutreachKind.TASK_COMPLETED,
    BackgroundTaskStatus.FAILED: OutreachKind.TASK_FAILED,
    BackgroundTaskStatus.CANCELLED: OutreachKind.TASK_CANCELLED,
}


def _code_agent_delegations(task: BackgroundTask) -> list[dict[str, str]]:
    result_payload = task.result_payload
    if not isinstance(result_payload, dict):
        return []
    message_payload = result_payload.get("message_payload")
    if not isinstance(message_payload, dict):
        return []
    raw_references = message_payload.get("code_agent_delegations")
    if not isinstance(raw_references, list):
        return []

    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_reference in raw_references:
        if not isinstance(raw_reference, dict):
            continue
        delegation_id = str(raw_reference.get("delegation_id") or "").strip()
        turn_id = str(raw_reference.get("turn_id") or "").strip()
        workspace_path = str(raw_reference.get("workspace_path") or "").strip()
        if (
            not delegation_id
            or not turn_id
            or not workspace_path
            or delegation_id in seen
        ):
            continue
        seen.add(delegation_id)
        references.append(
            {
                "delegation_id": delegation_id,
                "turn_id": turn_id,
                "workspace_path": workspace_path,
            }
        )
    return references


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
    code_agent_delegations = _code_agent_delegations(task)
    if code_agent_delegations:
        payload["code_agent_delegations"] = code_agent_delegations
    urgency = Urgency.HIGH if spec.trigger_source in _HIGH_URGENCY_TRIGGERS else Urgency.NORMAL
    attempt_index = int(getattr(task, "attempt_index", 0))
    pending_message_id = None
    if attempt_index == 0:
        pending_message_id = (spec.pending_message_id or "").strip() or None

    return OutreachIntent(
        kind=kind, user_id=user_id, origin_session_id=session_id, title=title,
        facts=facts,
        correlation_id=f"{task.task_id}:attempt:{attempt_index}",
        completed_at_ms=completed_at_ms,
        origin_turn_id=(
            str(getattr(spec, "origin_turn_id", "") or "").strip() or None
        ),
        pending_message_id=pending_message_id,
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
    terminal_state_json = json.dumps(
        counts,
        sort_keys=True,
        separators=(",", ":"),
    )
    terminal_state_id = hashlib.sha256(
        terminal_state_json.encode("utf-8")
    ).hexdigest()[:16]
    return OutreachIntent(
        kind=kind,
        user_id=(str(spec.user_id or "").strip() or job.owner),
        origin_session_id=((str(spec.session_id or "").strip() or job.origin_session_id) or None),
        title=job.title,
        facts=facts,
        correlation_id=f"{job_id}:terminal:{terminal_state_id}",
        completed_at_ms=int(job.updated_at_ms),
        origin_turn_id=(
            str(getattr(spec, "origin_turn_id", "") or "").strip() or None
        ),
        pending_message_id=None,
        urgency=Urgency.NORMAL,
        payload={"batch_job_id": job_id, "counts": counts},
    )


class BackgroundCompletionProducer:
    """Submit one durable task-attempt completion and acknowledge it."""

    def __init__(self, service: Any, *, completion_store: Any | None = None) -> None:
        self._service = service
        self._completion_store = completion_store
        self._lock = asyncio.Lock()

    async def __call__(self, task: BackgroundTask) -> None:
        async with self._lock:
            await self._submit_and_acknowledge(task)

    async def _submit_and_acknowledge(self, task: BackgroundTask) -> None:
        prepared_intent_json: str | None = None
        prepared_body: str | None = None
        claim_token: str | None = None
        if self._completion_store is not None:
            claim_token = uuid4().hex
            completion = await self._completion_store.claim_completion(
                task_id=task.task_id,
                attempt_index=task.attempt_index,
                claim_token=claim_token,
            )
            if completion is None:
                return
            task = completion.task
            prepared_intent_json = completion.intent_json
            prepared_body = completion.composed_body

        try:
            intent: OutreachIntent | None
            if prepared_intent_json is not None:
                intent = OutreachIntent.from_dict(json.loads(prepared_intent_json))
            else:
                identity = BatchRunIdentity.from_trigger(task.spec.trigger)
                intent = (
                    await batch_job_intent(task, identity.job_id)
                    if identity is not None
                    else task_to_intent(task)
                )
                if intent is not None and self._completion_store is not None:
                    assert claim_token is not None
                    prepared_intent_json = canonical_intent_json(intent)
                    await self._completion_store.save_completion_intent(
                        task_id=task.task_id,
                        attempt_index=task.attempt_index,
                        claim_token=claim_token,
                        intent_json=prepared_intent_json,
                    )

            if intent is not None:
                if self._completion_store is None:
                    await self._service.submit(intent)
                else:
                    assert claim_token is not None
                    assert prepared_intent_json is not None

                    async def persist_composed_body(body: str) -> None:
                        await self._completion_store.save_completion_body(
                            task_id=task.task_id,
                            attempt_index=task.attempt_index,
                            claim_token=claim_token,
                            intent_json=prepared_intent_json,
                            composed_body=body,
                        )

                    await self._service.submit(
                        intent,
                        prepared_body=prepared_body,
                        persist_composed_body=persist_composed_body,
                    )
            if self._completion_store is not None:
                assert claim_token is not None
                handled = await self._completion_store.mark_completion_handled(
                    task_id=task.task_id,
                    attempt_index=task.attempt_index,
                    claim_token=claim_token,
                )
                if not handled:
                    raise RuntimeError(
                        "Background completion claim disappeared before acknowledgement"
                    )
        except BaseException:  # keep interrupted delivery retryable
            if self._completion_store is not None and claim_token is not None:
                try:
                    await asyncio.shield(
                        self._completion_store.release_completion_claim(
                            task_id=task.task_id,
                            attempt_index=task.attempt_index,
                            claim_token=claim_token,
                        )
                    )
                except Exception:
                    logger.exception(
                        "outreach: failed to release background completion claim",
                        task_id=task.task_id,
                        attempt_index=task.attempt_index,
                    )
            raise

    async def drain_pending(
        self,
        *,
        max_items: int = _MAX_COMPLETION_DRAIN_ITEMS,
    ) -> int:
        """Retry one bounded snapshot of unacknowledged completions."""

        if self._completion_store is None:
            return 0
        bounded_limit = max(1, min(int(max_items), _MAX_COMPLETION_DRAIN_ITEMS))
        completions = await self._completion_store.list_pending_completions(
            limit=bounded_limit
        )
        handled = 0
        for completion in completions:
            task = completion.task
            try:
                await self(task)
            except Exception:
                logger.warning(
                    "outreach: pending background completion remains retryable",
                    task_id=task.task_id,
                    attempt_index=task.attempt_index,
                    exc_info=True,
                )
            else:
                handled += 1
        return handled


def build_background_completion_producer(
    service: Any,
    *,
    completion_store: Any | None = None,
) -> BackgroundCompletionProducer:
    """Build the live listener and startup recovery drain."""

    return BackgroundCompletionProducer(
        service,
        completion_store=completion_store,
    )
