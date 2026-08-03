"""Concurrency contracts for durable L2 projection leases."""

from __future__ import annotations

import time

import aiosqlite
import pytest

from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.store import L2CognitionStore


def _lease(row: dict[str, object]) -> L2ProjectionLease:
    return L2ProjectionLease(
        event_id=str(row["event_id"]),
        lease_token=str(row["lease_token"]),
        attempt_count=int(row["attempt_count"]),
    )


async def _enqueue(store: L2CognitionStore, event_id: str) -> None:
    assert await store.enqueue_projection_job(
        event_id=event_id,
        source="chat",
        event_type="UserMessage",
    )


@pytest.mark.asyncio
async def test_claim_assigns_a_new_fencing_token_for_each_attempt(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-1")

    first_row = (await store.claim_projection_jobs(consumer_name="worker-1", limit=1))[0]
    first = _lease(first_row)
    assert first.attempt_count == 1
    assert first.lease_token
    assert await store.mark_projection_jobs_running([first], consumer_name="worker-1") == 1

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET lease_heartbeat_at = ?, updated_at = ?
            WHERE event_id = 'event-1'
            """,
            (time.time() - 60, time.time() - 60),
        )
        await db.commit()
    assert (
        await store.requeue_stale_projection_jobs(
            queued_timeout_seconds=30,
            running_timeout_seconds=30,
        )
        == 1
    )
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET next_retry_at = 0 WHERE event_id = 'event-1'"
        )
        await db.commit()

    second_row = (await store.claim_projection_jobs(consumer_name="worker-2", limit=1))[0]
    second = _lease(second_row)
    assert second.attempt_count == 2
    assert second.lease_token != first.lease_token

    assert await store.touch_running_projection_jobs([first]) == 0
    assert await store.complete_projection_jobs([first]) == 0
    assert await store.fail_projection_jobs([first], requeue=False) == 0
    assert await store.mark_projection_jobs_running([second], consumer_name="worker-2") == 1
    assert await store.complete_projection_jobs([second]) == 1


@pytest.mark.asyncio
async def test_failed_attempt_respects_backoff_and_terminal_budget(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-retry")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 2 WHERE event_id = 'event-retry'"
        )
        await db.commit()

    first = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    assert await store.mark_projection_jobs_running([first], consumer_name="worker") == 1
    assert await store.fail_projection_jobs([first], error_text="temporary", requeue=True) == 1
    assert await store.claim_projection_jobs(consumer_name="worker", limit=1) == []

    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET next_retry_at = 0 WHERE event_id = 'event-retry'"
        )
        await db.commit()
    second = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    assert second.attempt_count == 2
    assert await store.mark_projection_jobs_running([second], consumer_name="worker") == 1
    assert await store.fail_projection_jobs([second], error_text="still broken", requeue=True) == 1

    async with aiosqlite.connect(store.db_path) as db:
        row = await (
            await db.execute(
                """
                SELECT status, next_retry_at, terminal_at, last_error
                FROM l2_projection_jobs WHERE event_id = 'event-retry'
                """
            )
        ).fetchone()
    assert row[0] == "failed"
    assert row[1] is None
    assert row[2] is not None
    assert row[3] == "still broken"
    assert await store.claim_projection_jobs(consumer_name="worker", limit=1) == []


@pytest.mark.asyncio
async def test_completion_requires_running_but_queued_failure_is_fenced(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-queued")
    lease = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])

    assert await store.complete_projection_jobs([lease]) == 0
    assert (
        await store.fail_projection_jobs(
            [lease],
            error_text="l1_event_not_found",
            requeue=False,
        )
        == 1
    )


def test_batch_attempt_key_is_order_independent_and_lease_sensitive() -> None:
    first = L2ProjectionLease(event_id="event-a", lease_token="token-a", attempt_count=1)
    second = L2ProjectionLease(event_id="event-b", lease_token="token-b", attempt_count=2)
    events = [
        {"event_id": "event-a", "content": "a", "timestamp": 1.0},
        {"event_id": "event-b", "content": "b", "timestamp": 2.0},
    ]
    job_a = L2BatchJob(
        job_id="job-a",
        bucket_key="bucket",
        events=events,
        flush_reason="projection_ready",
        estimated_tokens=2,
        projection_leases=[first, second],
    )
    job_b = L2BatchJob(
        job_id="job-b",
        bucket_key="bucket",
        events=list(reversed(events)),
        flush_reason="projection_ready",
        estimated_tokens=2,
        projection_leases=[second, first],
    )
    assert job_a.attempt_key == job_b.attempt_key

    retried = L2BatchJob(
        job_id="job-c",
        bucket_key="bucket",
        events=events,
        flush_reason="projection_ready",
        estimated_tokens=2,
        projection_leases=[
            L2ProjectionLease(event_id="event-a", lease_token="token-new", attempt_count=2),
            second,
        ],
    )
    assert retried.attempt_key != job_a.attempt_key


def test_batch_rejects_partial_projection_lease_coverage() -> None:
    with pytest.raises(ValueError, match="complete event batch"):
        L2BatchJob(
            job_id="job-partial",
            bucket_key="bucket",
            events=[
                {"event_id": "event-a", "content": "a", "timestamp": 1.0},
                {"event_id": "event-b", "content": "b", "timestamp": 2.0},
            ],
            flush_reason="projection_ready",
            estimated_tokens=2,
            projection_leases=[
                L2ProjectionLease(event_id="event-a", lease_token="token-a", attempt_count=1)
            ],
        )
