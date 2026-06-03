"""Batch driver wiring core — event-driven self-enqueue (the production driver).

``engine.drive_job`` is the inline, fully-testable driver (one async loop). In
production each batch must be an INDEPENDENT bounded background agent run, strung
together by a terminal listener, to dodge the 30-iteration cap (1000 items =
~67 short runs rather than one 1000-step run). This module holds that
event-driven logic with the background enqueue as an INJECTED SEAM:

    enqueue_run(job, items)  — real binding: build a BackgroundTaskSpec whose
                               goal carries the handler prompt + items, and hand
                               it to the runtime's launch service (wiring, needs
                               a real runtime). tests inject a fake.

Everything here is task-agnostic — it only reads ``job.handler_ref`` and the
opaque item inputs; the handler skill's prompt is supplied by the caller.
"""
from __future__ import annotations

import json
import uuid
from typing import Awaitable, Callable

from .contracts import BatchItem, BatchItemStatus, BatchJob, BatchJobStatus
from .store import BatchStore, _now_ms

# Seam: enqueue ONE bounded background agent run for this batch of items.
EnqueueRun = Callable[[BatchJob, "list[BatchItem]"], Awaitable[None]]

_LEASE_TTL_MS = 30 * 60 * 1000  # matches the background-run timeout
_GOAL_JOB_MARKER = "BATCH_JOB_ID"


def build_batch_goal(handler_prompt: str, job: BatchJob, items: "list[BatchItem]") -> str:
    """Compose the goal (user message) for one batch run. task-agnostic:
    handler prompt + the items + the write-back instruction. The job_id marker
    lets the terminal listener attribute the run back to its job."""
    payload = [{"item_id": i.item_id, "input": i.input} for i in items]
    return (
        f"{handler_prompt}\n\n"
        f"{_GOAL_JOB_MARKER}: {job.job_id}\n"
        f"Process each of the following {len(items)} items, then report every "
        f'outcome by calling batch_item_update(job_id="{job.job_id}", updates=[...]). '
        f"Each update is {{item_id, status, result?, review_reason?, error?}}.\n"
        f"`status` MUST be exactly one of:\n"
        f"  done         — you completed it confidently (put your output in result).\n"
        f"  needs_review — you are NOT confident (ambiguous, can't find it, doesn't "
        f"look like a valid target). IMPORTANT: needs_review is a STATUS you REPORT — "
        f"do NOT rename/relabel/alter the item itself and do NOT guess; leave the "
        f"underlying item untouched and explain in review_reason. A human decides later.\n"
        f"  failed       — you tried but it errored (put the error in error).\n"
        f"  skipped      — intentionally skipped / not applicable.\n"
        f"Choose done vs needs_review honestly: prefer needs_review over guessing.\n"
        f"Items:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def parse_job_id_from_goal(goal: str) -> str | None:
    """Recover the job_id a batch run was launched for (used by the listener)."""
    for line in goal.splitlines():
        line = line.strip()
        if line.startswith(_GOAL_JOB_MARKER):
            return line.split(":", 1)[1].strip() or None
    return None


async def kickoff_next_batch(
    store: BatchStore,
    job: BatchJob,
    *,
    enqueue_run: EnqueueRun,
    now_fn: Callable[[], int] | None = None,
) -> int:
    """Lease the next batch and enqueue a background run for it. Returns the
    number of items leased (0 means nothing pending)."""
    now = now_fn() if now_fn is not None else _now_ms()
    leased = await store.lease_next_batch(
        job.job_id,
        limit=job.batch_size,
        lease_owner=uuid.uuid4().hex,
        lease_ttl_ms=_LEASE_TTL_MS,
        now_ms=now,
    )
    if leased:
        await enqueue_run(job, leased)
    return len(leased)


async def on_batch_run_done(
    store: BatchStore,
    job_id: str,
    *,
    enqueue_run: EnqueueRun,
    now_fn: Callable[[], int] | None = None,
) -> str:
    """Terminal-listener logic for a finished batch run. Either continues
    (kick off the next batch) or finalizes (requeue retryable + reconcile).
    Returns a short status string for observability/tests."""
    now = now_fn() if now_fn is not None else _now_ms()
    job = await store.get_job(job_id)
    if job is None:
        return "unknown_job"

    pending = await store.list_by_status(job_id, BatchItemStatus.PENDING)
    if pending:
        await kickoff_next_batch(store, job, enqueue_run=enqueue_run, now_fn=now_fn)
        return "continued"

    # No pending left: requeue retryable failures, maybe one more lap.
    await store.requeue_retryable(job_id, job.max_attempts, now_ms=now)
    if await store.list_by_status(job_id, BatchItemStatus.PENDING):
        await kickoff_next_batch(store, job, enqueue_run=enqueue_run, now_fn=now_fn)
        return "retrying"

    report = await store.reconcile_scan(job_id, now_ms=now)
    if report.complete and not report.conflicts:
        await store.set_job_status(job_id, BatchJobStatus.DONE)
        return "done"
    await store.set_job_status(job_id, BatchJobStatus.RECONCILING)
    if report.conflicts:
        return "conflicts"
    return "needs_review" if report.counts.get("needs_review") else "blocked"
