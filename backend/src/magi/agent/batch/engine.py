"""Batch driver core — deterministic control flow, task-agnostic.

``drive_job`` leases a batch, hands it to ``run_batch`` (THE SEAM: production
enqueues a bounded background run whose agent writes outcomes back via the
``batch_item_update`` tool; tests inject a fake that writes outcomes directly),
repeats until no pending remain, requeues retryable failures, then reconciles
and self-heals up to ``reconcile_rounds_max``.

No bootstrap / agent-run / outreach coupling lives here — that wiring (a
``BackgroundManager.add_listener`` self-enqueue + the real background run + the
job-level outreach notification) is verified in a real runtime. This module
isolates the control flow so it can be unit-tested.
"""
from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from .contracts import BatchItem, BatchItemStatus, BatchJob, BatchJobStatus, ReconcileReport
from .store import BatchStore, _now_ms

RunBatch = Callable[[list[BatchItem]], Awaitable[None]]

_LEASE_TTL_MS = 30 * 60 * 1000  # 30 min, matches the background-run timeout


async def drive_job(
    store: BatchStore,
    job: BatchJob,
    *,
    run_batch: RunBatch,
    now_fn: Callable[[], int] = _now_ms,
) -> ReconcileReport:
    """Drive ``job`` to completion; return the final ReconcileReport.

    Marks the job DONE iff the report is complete (no pending/running/
    needs_review) and has no dedup conflicts.
    """
    await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)

    rounds = 0
    while True:
        await _drain_pending(store, job, run_batch=run_batch, now_fn=now_fn)
        await store.requeue_retryable(job.job_id, job.max_attempts, now_ms=now_fn())
        still_pending = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
        if not still_pending:
            break
        rounds += 1
        if rounds > job.reconcile_rounds_max:
            break

    await store.set_job_status(job.job_id, BatchJobStatus.RECONCILING)
    report = await store.reconcile_scan(job.job_id, now_ms=now_fn())
    if report.complete and not report.conflicts:
        await store.set_job_status(job.job_id, BatchJobStatus.DONE)
    return report


async def _drain_pending(
    store: BatchStore,
    job: BatchJob,
    *,
    run_batch: RunBatch,
    now_fn: Callable[[], int],
) -> None:
    """Lease and run batches until no pending items remain."""
    while True:
        leased = await store.lease_next_batch(
            job.job_id,
            limit=job.batch_size,
            lease_owner=uuid.uuid4().hex,
            lease_ttl_ms=_LEASE_TTL_MS,
            now_ms=now_fn(),
        )
        if not leased:
            break
        await run_batch(leased)
