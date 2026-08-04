"""Concurrency contracts for durable L2 projection leases."""

from __future__ import annotations

import asyncio
import time

import aiosqlite
import pytest

from magi.memory.l2.models import (
    L2BatchJob,
    L2ProjectionLease,
    derive_projection_attempt_key,
)
from magi.memory.l2.projection.errors import ProjectionAttemptFencedError
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


async def _bind(
    store: L2CognitionStore,
    leases: list[L2ProjectionLease],
    *,
    consumer_name: str,
) -> None:
    assert await store.bind_projection_job_batch(leases, consumer_name=consumer_name) == len(leases)


@pytest.mark.asyncio
async def test_claim_assigns_a_new_fencing_token_for_each_attempt(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-1")

    first_row = (await store.claim_projection_jobs(consumer_name="worker-1", limit=1))[0]
    first = _lease(first_row)
    assert first.attempt_count == 1
    assert first.lease_token
    await _bind(store, [first], consumer_name="worker-1")
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
    await _bind(store, [second], consumer_name="worker-2")

    assert await store.touch_running_projection_jobs([first]) == 0
    assert await store.complete_projection_jobs([first]) == 0
    assert await store.fail_projection_jobs([first], requeue=False) == 0
    assert await store.mark_projection_jobs_running([second], consumer_name="worker-2") == 1
    await store.stage_event_entity_link_projections(
        desired_links_by_event={second.event_id: []},
        projection_leases=[second],
    )
    assert await store.complete_projection_jobs([second]) == 1


@pytest.mark.asyncio
async def test_stale_requeue_waits_for_the_shared_persistence_guard(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    async with store.memory_correction_job_guard():
        task = asyncio.create_task(
            store.requeue_stale_projection_jobs(
                queued_timeout_seconds=0,
                running_timeout_seconds=0,
            )
        )
        await asyncio.sleep(0)
        assert task.done() is False

    assert await task == 0


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
    await _bind(store, [first], consumer_name="worker")
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
    await _bind(store, [second], consumer_name="worker")
    assert await store.mark_projection_jobs_running([second], consumer_name="worker") == 1
    assert await store.fail_projection_jobs([second], error_text="still broken", requeue=True) == 1

    async with aiosqlite.connect(store.db_path) as db:
        row = await (
            await db.execute("""
                SELECT status, next_retry_at, terminal_at, last_error
                FROM l2_projection_jobs WHERE event_id = 'event-retry'
                """)
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
    await _bind(store, [lease], consumer_name="worker")

    assert await store.complete_projection_jobs([lease]) == 0
    assert (
        await store.fail_projection_jobs(
            [lease],
            error_text="l1_event_not_found",
            requeue=False,
        )
        == 1
    )


@pytest.mark.asyncio
async def test_explicit_replay_resets_a_completed_job_to_a_fresh_attempt(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-replay")
    first = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    await _bind(store, [first], consumer_name="worker")
    assert await store.mark_projection_jobs_running([first], consumer_name="worker") == 1
    await store.stage_event_entity_link_projections(
        desired_links_by_event={first.event_id: []},
        projection_leases=[first],
    )
    assert await store.complete_projection_jobs([first]) == 1

    assert await store.request_projection_replay("event-replay") is True
    replay = _lease((await store.claim_projection_jobs(consumer_name="replay-worker", limit=1))[0])
    assert replay.attempt_count == 1
    assert replay.lease_token != first.lease_token

    await store.tombstone_source_events(["event-replay"], reason="user_request")
    assert await store.request_projection_replay("event-replay") is False


@pytest.mark.asyncio
async def test_replay_requested_during_an_active_attempt_runs_after_it_finishes(
    tmp_path,
) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-active-replay")
    active = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])

    assert await store.request_projection_replay("event-active-replay") is True
    await _bind(store, [active], consumer_name="worker")
    assert await store.mark_projection_jobs_running([active], consumer_name="worker") == 1
    assert await store.request_projection_replay("event-active-replay") is True
    await store.stage_event_entity_link_projections(
        desired_links_by_event={active.event_id: []},
        projection_leases=[active],
    )
    assert await store.complete_projection_jobs([active]) == 1

    async with aiosqlite.connect(store.db_path) as db:
        row = await (
            await db.execute("""
                SELECT status, attempt_count, replay_requested, lease_token,
                       completed_at, next_retry_at
                FROM l2_projection_jobs
                WHERE event_id = 'event-active-replay'
                """)
        ).fetchone()
    assert row == ("pending", 0, 0, None, None, None)

    replay = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    assert replay.attempt_count == 1
    assert replay.lease_token != active.lease_token


@pytest.mark.asyncio
async def test_explicit_replay_clears_pending_backoff_and_resets_attempt_budget(
    tmp_path,
) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-pending-replay")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("""
            UPDATE l2_projection_jobs
            SET max_attempts = 2
            WHERE event_id = 'event-pending-replay'
            """)
        await db.commit()

    first = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    await _bind(store, [first], consumer_name="worker")
    assert await store.mark_projection_jobs_running([first], consumer_name="worker") == 1
    assert (
        await store.fail_projection_jobs(
            [first],
            error_text="temporary",
            requeue=True,
        )
        == 1
    )

    async with aiosqlite.connect(store.db_path) as db:
        pending = await (
            await db.execute("""
                SELECT attempt_count, next_retry_at
                FROM l2_projection_jobs
                WHERE event_id = 'event-pending-replay'
                """)
        ).fetchone()
    assert pending is not None
    assert pending[0] == 1
    assert pending[1] is not None

    assert await store.request_projection_replay("event-pending-replay") is True
    async with aiosqlite.connect(store.db_path) as db:
        replayed = await (
            await db.execute("""
                SELECT status, attempt_count, max_attempts, next_retry_at,
                       terminal_at, lease_token, claimed_by, last_error
                FROM l2_projection_jobs
                WHERE event_id = 'event-pending-replay'
                """)
        ).fetchone()
    assert replayed == ("pending", 0, 2, None, None, None, None, None)

    replay = _lease((await store.claim_projection_jobs(consumer_name="worker", limit=1))[0])
    assert replay.attempt_count == 1
    assert replay.lease_token != first.lease_token


@pytest.mark.asyncio
async def test_startup_recovery_releases_only_foreign_active_attempts(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await _enqueue(store, "event-foreign-queued")
    foreign_queued = _lease(
        (await store.claim_projection_jobs(consumer_name="old-worker", limit=1))[0]
    )
    await _bind(store, [foreign_queued], consumer_name="old-worker")

    await _enqueue(store, "event-foreign-running")
    foreign_running = _lease(
        (await store.claim_projection_jobs(consumer_name="old-worker", limit=1))[0]
    )
    await _bind(store, [foreign_running], consumer_name="old-worker")
    assert (
        await store.mark_projection_jobs_running(
            [foreign_running],
            consumer_name="old-worker",
        )
        == 1
    )

    await _enqueue(store, "event-current-running")
    current_running = _lease(
        (await store.claim_projection_jobs(consumer_name="current-worker", limit=1))[0]
    )
    await _bind(store, [current_running], consumer_name="current-worker")
    assert (
        await store.mark_projection_jobs_running(
            [current_running],
            consumer_name="current-worker",
        )
        == 1
    )

    await _enqueue(store, "event-foreign-exhausted")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("""
            UPDATE l2_projection_jobs
            SET max_attempts = 1
            WHERE event_id = 'event-foreign-exhausted'
            """)
        await db.commit()
    foreign_exhausted = _lease(
        (await store.claim_projection_jobs(consumer_name="old-worker", limit=1))[0]
    )
    await _bind(store, [foreign_exhausted], consumer_name="old-worker")

    assert await store.recover_foreign_projection_jobs(consumer_name="current-worker") == 3
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute("""
                SELECT event_id, status, attempt_count, lease_token,
                       batch_attempt_key, batch_descriptor_json, batch_bound_at,
                       lease_heartbeat_at, next_retry_at, terminal_at,
                       claimed_by, claimed_at, started_at, last_error
                FROM l2_projection_jobs
                ORDER BY event_id
                """)
        ).fetchall()
    by_event = {str(row["event_id"]): dict(row) for row in rows}

    for lease in (foreign_queued, foreign_running):
        row = by_event[lease.event_id]
        assert row["status"] == "pending"
        assert row["attempt_count"] == 1
        assert row["lease_token"] is None
        assert row["batch_attempt_key"] is None
        assert row["batch_descriptor_json"] is None
        assert row["batch_bound_at"] is None
        assert row["lease_heartbeat_at"] is None
        assert row["next_retry_at"] is None
        assert row["terminal_at"] is None
        assert row["claimed_by"] is None
        assert row["claimed_at"] is None
        assert row["started_at"] is None
        assert row["last_error"] == "projection_attempt_recovered_on_startup"

    current_row = by_event[current_running.event_id]
    assert current_row["status"] == "running"
    assert current_row["lease_token"] == current_running.lease_token
    assert current_row["claimed_by"] == "current-worker"

    exhausted_row = by_event[foreign_exhausted.event_id]
    assert exhausted_row["status"] == "failed"
    assert exhausted_row["attempt_count"] == 1
    assert exhausted_row["lease_token"] is None
    assert exhausted_row["batch_attempt_key"] is None
    assert exhausted_row["batch_descriptor_json"] is None
    assert exhausted_row["batch_bound_at"] is None
    assert exhausted_row["next_retry_at"] is None
    assert exhausted_row["terminal_at"] is not None
    assert exhausted_row["last_error"] == "projection_attempt_budget_exhausted_on_startup"

    assert await store.recover_foreign_projection_jobs(consumer_name="current-worker") == 0
    reclaimed = await store.claim_projection_jobs(consumer_name="current-worker", limit=10)
    assert {str(row["event_id"]) for row in reclaimed} == {
        "event-foreign-queued",
        "event-foreign-running",
    }
    assert {int(row["attempt_count"]) for row in reclaimed} == {2}


@pytest.mark.asyncio
async def test_startup_recovery_does_not_consume_an_unbound_claim(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-unbound-startup")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 1 WHERE event_id = ?",
            ("event-unbound-startup",),
        )
        await db.commit()

    claimed = await store.claim_projection_jobs(consumer_name="old-worker", limit=1)
    assert len(claimed) == 1
    assert claimed[0]["batch_attempt_key"] is None

    assert await store.recover_foreign_projection_jobs(consumer_name="new-worker") == 1
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                """
                SELECT status, attempt_count, lease_token, terminal_at
                FROM l2_projection_jobs
                WHERE event_id = ?
                """,
                ("event-unbound-startup",),
            )
        ).fetchone()
    assert state == ("pending", 0, None, None)
    reclaimed = await store.claim_projection_jobs(consumer_name="new-worker", limit=1)
    assert len(reclaimed) == 1
    assert int(reclaimed[0]["attempt_count"]) == 1


@pytest.mark.asyncio
async def test_stale_recovery_does_not_consume_an_unbound_claim(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-unbound-stale")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "UPDATE l2_projection_jobs SET max_attempts = 1 WHERE event_id = ?",
            ("event-unbound-stale",),
        )
        await db.commit()

    claimed = await store.claim_projection_jobs(consumer_name="old-worker", limit=1)
    assert len(claimed) == 1
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET claimed_at = 0, updated_at = 0
            WHERE event_id = ?
            """,
            ("event-unbound-stale",),
        )
        await db.commit()

    assert (
        await store.requeue_stale_projection_jobs(
            queued_timeout_seconds=1,
            running_timeout_seconds=1,
        )
        == 1
    )
    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                """
                SELECT status, attempt_count, lease_token, terminal_at
                FROM l2_projection_jobs
                WHERE event_id = ?
                """,
                ("event-unbound-stale",),
            )
        ).fetchone()
    assert state == ("pending", 0, None, None)
    reclaimed = await store.claim_projection_jobs(consumer_name="new-worker", limit=1)
    assert len(reclaimed) == 1
    assert int(reclaimed[0]["attempt_count"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_path", ["startup", "stale"])
async def test_unbound_replay_resets_attempt_budget(
    tmp_path,
    recovery_path: str,
) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    event_id = f"event-unbound-replay-{recovery_path}"
    await _enqueue(store, event_id)
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET attempt_count = 3, max_attempts = 5
            WHERE event_id = ?
            """,
            (event_id,),
        )
        await db.commit()

    claimed = await store.claim_projection_jobs(consumer_name="old-worker", limit=1)
    assert len(claimed) == 1
    assert int(claimed[0]["attempt_count"]) == 4
    assert await store.request_projection_replay(event_id) is True

    if recovery_path == "startup":
        assert await store.recover_foreign_projection_jobs(consumer_name="new-worker") == 1
    else:
        async with aiosqlite.connect(store.db_path) as db:
            await db.execute(
                "UPDATE l2_projection_jobs SET claimed_at = 0 WHERE event_id = ?",
                (event_id,),
            )
            await db.commit()
        assert (
            await store.requeue_stale_projection_jobs(
                queued_timeout_seconds=1,
                running_timeout_seconds=1,
            )
            == 1
        )

    async with aiosqlite.connect(store.db_path) as db:
        state = await (
            await db.execute(
                """
                SELECT status, attempt_count, replay_requested, last_error
                FROM l2_projection_jobs
                WHERE event_id = ?
                """,
                (event_id,),
            )
        ).fetchone()
    assert state == ("pending", 0, 0, None)


@pytest.mark.asyncio
async def test_non_positive_claim_limits_leave_projection_jobs_pending(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-limit")

    for limit in (0, -1):
        assert (
            await store.claim_projection_jobs(
                consumer_name="worker",
                limit=limit,
            )
            == []
        )
        assert (
            await store.claim_ready_projection_jobs(
                consumer_name="worker",
                limit=limit,
            )
            == []
        )

    claimed = await store.claim_projection_jobs(consumer_name="worker", limit=1)
    assert [row["event_id"] for row in claimed] == ["event-limit"]


@pytest.mark.asyncio
async def test_bound_batch_rejects_singleton_start_write_and_completion(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-a")
    await _enqueue(store, "event-b")
    rows = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    leases = [_lease(row) for row in rows]
    assert {lease.event_id for lease in leases} == {"event-a", "event-b"}

    assert (
        await store.bind_projection_job_batch(
            leases,
            consumer_name="worker",
            attempt_key=f"l2pa_{'0' * 32}",
        )
        == 0
    )
    await _bind(store, leases, consumer_name="worker")
    singleton = [leases[0]]
    assert await store.mark_projection_jobs_running(singleton, consumer_name="worker") == 0
    assert await store.mark_projection_jobs_running(leases, consumer_name="worker") == 2
    assert await store.touch_running_projection_jobs(singleton) == 0
    with pytest.raises(ProjectionAttemptFencedError, match="projection_attempt_fenced"):
        await store.stage_event_entity_link_projections(
            desired_links_by_event={singleton[0].event_id: []},
            projection_leases=singleton,
        )
    assert await store.complete_projection_jobs(singleton) == 0

    await store.stage_event_entity_link_projections(
        desired_links_by_event={lease.event_id: [] for lease in leases},
        projection_leases=leases,
    )
    assert await store.complete_projection_jobs(leases) == 2


@pytest.mark.asyncio
async def test_forget_between_claim_and_bind_releases_unbound_batch_peer(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-a")
    await _enqueue(store, "event-b")
    rows = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    leases = [_lease(row) for row in rows]
    leases_by_event = {lease.event_id: lease for lease in leases}

    await store.tombstone_source_events(["event-a"], reason="user_delete_event")
    assert await store.bind_projection_job_batch(leases, consumer_name="worker") == 0

    async with aiosqlite.connect(store.db_path) as db:
        states = await (
            await db.execute(
                """
                SELECT event_id, status, attempt_count, lease_token, claimed_by,
                       batch_attempt_key, batch_descriptor_json
                FROM l2_projection_jobs
                ORDER BY event_id
                """
            )
        ).fetchall()
    assert states == [
        ("event-a", "completed", 1, None, None, None, None),
        ("event-b", "pending", 0, None, None, None, None),
    ]
    reclaimed = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    assert [row["event_id"] for row in reclaimed] == ["event-b"]
    assert int(reclaimed[0]["attempt_count"]) == 1
    assert reclaimed[0]["lease_token"] != leases_by_event["event-b"].lease_token


@pytest.mark.asyncio
async def test_one_member_replay_resets_the_full_failed_batch(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-a")
    await _enqueue(store, "event-b")
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET max_attempts = CASE event_id WHEN 'event-a' THEN 1 ELSE 5 END
            """
        )
        await db.commit()
    rows = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    leases = [_lease(row) for row in rows]
    await _bind(store, leases, consumer_name="worker")
    assert await store.mark_projection_jobs_running(leases, consumer_name="worker") == 2
    assert await store.request_projection_replay("event-b") is True

    assert await store.fail_projection_jobs(leases, error_text="retry", requeue=True) == 2
    async with aiosqlite.connect(store.db_path) as db:
        states = await (
            await db.execute(
                """
                SELECT event_id, status, attempt_count, terminal_at,
                       batch_attempt_key, batch_descriptor_json
                FROM l2_projection_jobs
                ORDER BY event_id
                """
            )
        ).fetchall()
    assert states == [
        ("event-a", "pending", 0, None, None, None),
        ("event-b", "pending", 0, None, None, None),
    ]
    reclaimed = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    assert {row["event_id"] for row in reclaimed} == {"event-a", "event-b"}
    assert {int(row["attempt_count"]) for row in reclaimed} == {1}
    assert {str(row["lease_token"]) for row in reclaimed}.isdisjoint(
        {lease.lease_token for lease in leases}
    )


@pytest.mark.asyncio
async def test_retry_and_clear_invalidate_old_batch_descriptor(tmp_path) -> None:
    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()
    await _enqueue(store, "event-a")
    await _enqueue(store, "event-b")
    first_rows = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    first = [_lease(row) for row in first_rows]
    await _bind(store, first, consumer_name="worker")
    assert await store.mark_projection_jobs_running(first, consumer_name="worker") == 2
    assert await store.fail_projection_jobs(first, error_text="retry", requeue=True) == 2

    async with aiosqlite.connect(store.db_path) as db:
        cleared = await (
            await db.execute(
                """
                SELECT COUNT(*)
                FROM l2_projection_jobs
                WHERE batch_attempt_key IS NOT NULL
                   OR batch_descriptor_json IS NOT NULL
                   OR batch_bound_at IS NOT NULL
                """
            )
        ).fetchone()
        await db.execute("UPDATE l2_projection_jobs SET next_retry_at = 0")
        await db.commit()
    assert cleared == (0,)

    second_rows = await store.claim_projection_jobs(consumer_name="worker", limit=2)
    second = [_lease(row) for row in second_rows]
    assert {lease.lease_token for lease in second}.isdisjoint(
        {lease.lease_token for lease in first}
    )
    await _bind(store, second, consumer_name="worker")
    assert await store.mark_projection_jobs_running(first, consumer_name="worker") == 0

    await store.clear()
    async with aiosqlite.connect(store.db_path) as db:
        remaining = await (await db.execute("SELECT COUNT(*) FROM l2_projection_jobs")).fetchone()
    assert remaining == (0,)
    assert await store.mark_projection_jobs_running(second, consumer_name="worker") == 0


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


def test_projection_attempt_key_uses_unambiguous_structured_material() -> None:
    first = [
        L2ProjectionLease(
            event_id="event:a",
            lease_token="token\n1",
            attempt_count=2,
        )
    ]
    second = [
        L2ProjectionLease(
            event_id="event",
            lease_token="a:2:token\n1",
            attempt_count=1,
        )
    ]

    assert derive_projection_attempt_key(first) != derive_projection_attempt_key(second)


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
