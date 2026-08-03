"""Race, failure, and crash-recovery tests for L2-owned L1 entity links."""

from __future__ import annotations

import json
import math
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l2.models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.pipeline import extraction as extraction_module
from magi.memory.l2.projection.entity_links import (
    begin_event_entity_link_projection_clear,
)
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore


async def _running_leases(  # type: ignore[no-untyped-def]
    store,
    event_ids: list[str],
    consumer: str,
) -> list[L2ProjectionLease]:
    for event_id in event_ids:
        assert await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="user_message",
        )
    claimed = await store.claim_projection_jobs(
        consumer_name=consumer,
        limit=len(event_ids),
    )
    assert len(claimed) == len(event_ids)
    leases = [L2ProjectionLease.from_dict(row) for row in claimed]
    assert await store.mark_projection_jobs_running(leases, consumer_name=consumer) == len(leases)
    return sorted(leases, key=lambda lease: lease.event_id)


async def _running_lease(  # type: ignore[no-untyped-def]
    store,
    event_id: str,
    consumer: str,
) -> L2ProjectionLease:
    return (await _running_leases(store, [event_id], consumer))[0]


def _pipeline(store, l1: L1EventStore) -> L2Pipeline:  # type: ignore[no-untyped-def]
    return L2Pipeline(
        store,
        l1_store=l1,
        entity_catalog=SimpleNamespace(),
        llm_service=SimpleNamespace(),
    )


def _unified_memory(tmp_path) -> UnifiedMemoryStore:  # type: ignore[no-untyped-def]
    return UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        enable_l0=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            async_embeddings=False,
        ),
    )


async def _publish(  # type: ignore[no-untyped-def]
    store,
    pipeline: L2Pipeline,
    lease: L2ProjectionLease,
    links: list[tuple[str, str | None, float | None]],
) -> None:
    await store.stage_event_entity_link_projections(
        desired_links_by_event={lease.event_id: links},
        projection_leases=[lease],
    )
    assert await store.complete_projection_jobs([lease]) == 1
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1


async def _published_projection_and_replay(  # type: ignore[no-untyped-def]
    store,
    pipeline: L2Pipeline,
    event_id: str,
) -> L2ProjectionLease:
    first = await _running_lease(store, event_id, "worker-1")
    await _publish(
        store,
        pipeline,
        first,
        [("entity:old", "topic", 0.8)],
    )
    assert await store.request_projection_replay(event_id)
    claimed = await store.claim_projection_jobs(consumer_name="worker-2", limit=1)
    replay = L2ProjectionLease.from_dict(claimed[0])
    assert await store.mark_projection_jobs_running([replay], consumer_name="worker-2") == 1
    return replay


def _job(lease: L2ProjectionLease) -> L2BatchJob:
    return L2BatchJob(
        job_id=f"job:{lease.event_id}",
        bucket_key=f"bucket:{lease.event_id}",
        events=[{"event_id": lease.event_id, "timestamp": 1.0}],
        flush_reason="test",
        estimated_tokens=1,
        projection_leases=[lease],
    )


def _outbox_states(db_path: str) -> list[tuple[str, int, str]]:
    with sqlite3.connect(db_path) as db:
        return [(str(row[0]), int(row[1]), str(row[2])) for row in db.execute("""
                SELECT event_id, revision, state
                FROM l2_event_entity_link_outbox
                ORDER BY event_id, revision
                """).fetchall()]


def _outbox_rows(db_path: str) -> list[tuple[str, int, str, str, list[dict[str, object]]]]:
    with sqlite3.connect(db_path) as db:
        return [
            (
                str(row[0]),
                int(row[1]),
                str(row[2]),
                str(row[3]),
                json.loads(str(row[4])),
            )
            for row in db.execute("""
                SELECT event_id, revision, state, batch_key, desired_links_json
                FROM l2_event_entity_link_outbox
                ORDER BY event_id, revision
                """).fetchall()
        ]


@pytest.mark.asyncio
async def test_stage_is_invisible_until_queue_completion_publishes_batch(
    l2_store_with_schema,
    tmp_path,
) -> None:
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    lease = await _running_lease(l2_store_with_schema, "evt-a", "worker-1")

    batch = await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={"evt-a": [("entity:new", "topic", 0.9)]},
        projection_leases=[lease],
    )
    assert batch.items[0].revision == 1
    assert await l2_store_with_schema.prepare_event_entity_link_outbox() == []
    assert await pipeline._drain_event_entity_link_outbox() == 0
    assert (await l1.get_event_entity_ids(["evt-a"]))["evt-a"] == []

    assert await l2_store_with_schema.complete_projection_jobs([lease]) == 1
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1
    assert (await l1.get_event_entity_ids(["evt-a"]))["evt-a"] == ["entity:new"]
    assert _outbox_states(l2_store_with_schema.db_path) == [("evt-a", 1, "applied")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [[], [("entity:failed", "topic", 0.95)]],
)
async def test_failed_replay_discards_candidate_without_replacing_last_good(
    candidate,
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-failed-replay"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    replay = await _published_projection_and_replay(
        l2_store_with_schema,
        pipeline,
        event_id,
    )

    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: candidate},
        projection_leases=[replay],
    )
    assert await l2_store_with_schema.fail_projection_jobs([replay], requeue=True) == 1
    assert await pipeline._drain_event_entity_link_outbox() == 0

    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:old"]
    assert _outbox_states(l2_store_with_schema.db_path)[-1][2] == "discarded"


@pytest.mark.asyncio
async def test_successful_empty_replay_clears_only_projected_links(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-empty-replay"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    await l1.write_event_entities([(event_id, "entity:manual", "topic", 0.7)])
    pipeline = _pipeline(l2_store_with_schema, l1)
    replay = await _published_projection_and_replay(
        l2_store_with_schema,
        pipeline,
        event_id,
    )

    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: []},
        projection_leases=[replay],
    )
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == [
        "entity:manual",
        "entity:old",
    ]
    assert await l2_store_with_schema.complete_projection_jobs([replay]) == 1
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:manual"]


@pytest.mark.asyncio
async def test_startup_discards_unfinished_pending_replay_and_keeps_last_good(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-startup-pending"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    replay = await _published_projection_and_replay(
        l2_store_with_schema,
        pipeline,
        event_id,
    )
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: [("entity:unfinished", "topic", 0.9)]},
        projection_leases=[replay],
    )

    restarted = _pipeline(l2_store_with_schema, l1)
    restarted._extract_worker_count = 0
    await restarted.start()
    try:
        assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:old"]
        assert _outbox_states(l2_store_with_schema.db_path)[-1][2] == "discarded"
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_completed_ready_batch_survives_crash_and_startup_drains_it(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-completion-crash"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    lease = await _running_lease(l2_store_with_schema, event_id, "dead-worker")
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: [("entity:durable", "topic", 0.9)]},
        projection_leases=[lease],
    )
    assert await l2_store_with_schema.complete_projection_jobs([lease]) == 1
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == []

    restarted = _pipeline(l2_store_with_schema, l1)
    restarted._extract_worker_count = 0
    await restarted.start()
    try:
        assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:durable"]
        assert _outbox_states(l2_store_with_schema.db_path) == [(event_id, 1, "applied")]
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_multi_event_completion_missing_one_stage_rolls_back_queue_transition(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(
        l2_store_with_schema,
        ["evt-a", "evt-b"],
        "worker-1",
    )
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={
            "evt-a": [("entity:a", "topic", 0.8)],
            "evt-b": [("entity:b", "topic", 0.8)],
        },
        projection_leases=leases,
    )
    with sqlite3.connect(l2_store_with_schema.db_path) as db:
        db.execute("DELETE FROM l2_event_entity_link_outbox WHERE event_id = 'evt-b'")
        db.commit()

    with pytest.raises(RuntimeError, match="missing staged"):
        await l2_store_with_schema.complete_projection_jobs(leases)

    with sqlite3.connect(l2_store_with_schema.db_path) as db:
        statuses = db.execute(
            "SELECT event_id, status FROM l2_projection_jobs ORDER BY event_id"
        ).fetchall()
        state = db.execute(
            "SELECT state FROM l2_event_entity_link_outbox WHERE event_id = 'evt-a'"
        ).fetchone()
    assert statuses == [("evt-a", "running"), ("evt-b", "running")]
    assert state == ("pending",)


@pytest.mark.asyncio
async def test_partial_supersession_applies_remaining_batch_and_acks_whole_batch(
    l2_store_with_schema,
    tmp_path,
) -> None:
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    leases = await _running_leases(
        l2_store_with_schema,
        ["evt-a", "evt-b"],
        "worker-1",
    )
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={
            "evt-a": [("entity:a-stale", "topic", 0.6)],
            "evt-b": [("entity:b", "topic", 0.8)],
        },
        projection_leases=leases,
    )
    assert await l2_store_with_schema.complete_projection_jobs(leases) == 2
    assert await l1.replace_projected_event_entities(
        event_id="evt-a",
        revision=2,
        lease_token="governance-a2",
        attempt_count=1,
        clear_generation=0,
        mappings=[("entity:a-newer", "topic", 1.0)],
    )

    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 2
    links = await l1.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == ["entity:a-newer"]
    assert links["evt-b"] == ["entity:b"]
    assert {state for _, _, state in _outbox_states(l2_store_with_schema.db_path)} == {"applied"}


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence", [math.nan, math.inf, -math.inf, -0.01, 1.01])
async def test_outbox_rejects_non_canonical_confidence(
    confidence,
    l2_store_with_schema,
) -> None:
    lease = await _running_lease(l2_store_with_schema, "evt-invalid", "worker-1")

    with pytest.raises(ValueError, match="confidence"):
        await l2_store_with_schema.stage_event_entity_link_projections(
            desired_links_by_event={"evt-invalid": [("entity:a", "topic", confidence)]},
            projection_leases=[lease],
        )

    assert _outbox_states(l2_store_with_schema.db_path) == []


@pytest.mark.asyncio
async def test_schema_rejects_invalid_json_and_does_not_cascade_with_job_delete(
    l2_store_with_schema,
) -> None:
    lease = await _running_lease(l2_store_with_schema, "evt-a", "worker-1")
    batch = await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={"evt-a": [("entity:a", "topic", 0.8)]},
        projection_leases=[lease],
    )
    with sqlite3.connect(l2_store_with_schema.db_path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("""
                UPDATE l2_event_entity_link_outbox
                SET desired_links_json = 'not-json'
                WHERE event_id = 'evt-a'
                """)
        foreign_keys = db.execute("PRAGMA foreign_key_list(l2_event_entity_link_outbox)").fetchall()
        db.execute("DELETE FROM l2_projection_jobs WHERE event_id = 'evt-a'")
        db.commit()
        remaining = db.execute(
            "SELECT batch_key FROM l2_event_entity_link_outbox WHERE event_id = 'evt-a'"
        ).fetchone()
    assert foreign_keys == []
    assert remaining == (batch.batch_key,)


@pytest.mark.asyncio
async def test_source_forget_discards_running_replay_and_clears_projected_only(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-forget"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    await l1.write_event_entities([(event_id, "entity:manual", "topic", 0.7)])
    pipeline = _pipeline(l2_store_with_schema, l1)
    replay = await _published_projection_and_replay(
        l2_store_with_schema,
        pipeline,
        event_id,
    )
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: [("entity:replay", "topic", 0.9)]},
        projection_leases=[replay],
    )

    result = await l2_store_with_schema.forget_source_events(
        [event_id],
        reason="test_forget",
    )
    assert result["event_entity_links"] == 1
    rows_before_drain = _outbox_rows(l2_store_with_schema.db_path)
    assert [row[2] for row in rows_before_drain] == [
        "applied",
        "discarded",
        "ready",
    ]
    assert all(row[4] == [] for row in rows_before_drain)
    assert await l2_store_with_schema.complete_projection_jobs([replay]) == 0
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1

    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:manual"]
    assert [state for _, _, state in _outbox_states(l2_store_with_schema.db_path)] == [
        "applied",
        "discarded",
        "applied",
    ]


@pytest.mark.asyncio
async def test_source_forget_replaces_ready_batch_and_restart_preserves_other_event(
    l2_store_with_schema,
    tmp_path,
) -> None:
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    leases = await _running_leases(
        l2_store_with_schema,
        ["evt-forgotten", "evt-retained"],
        "worker-1",
    )
    original = await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={
            "evt-forgotten": [("entity:private", "topic", 0.9)],
            "evt-retained": [("entity:keep", "topic", 0.8)],
        },
        projection_leases=leases,
    )
    assert await l2_store_with_schema.complete_projection_jobs(leases) == 2
    assert len(await l2_store_with_schema.prepare_event_entity_link_outbox()) == 1

    result = await l2_store_with_schema.forget_source_events(
        ["evt-forgotten"],
        reason="user_delete_event",
    )
    assert result["event_entity_links"] == 2
    rows = _outbox_rows(l2_store_with_schema.db_path)
    original_rows = [row for row in rows if row[3] == original.batch_key]
    assert {row[2] for row in original_rows} == {"discarded"}
    assert all(row[4] == [] for row in rows if row[0] == "evt-forgotten")
    assert "entity:private" not in json.dumps(rows)
    assert sum(row[2] == "ready" for row in rows) == 2

    restarted = _pipeline(l2_store_with_schema, l1)
    restarted._extract_worker_count = 0
    await restarted.start()
    try:
        links = await l1.get_event_entity_ids(["evt-forgotten", "evt-retained"])
        assert links["evt-forgotten"] == []
        assert links["evt-retained"] == ["entity:keep"]
        row_count = len(_outbox_rows(l2_store_with_schema.db_path))
        repeated = await l2_store_with_schema.forget_source_events(
            ["evt-forgotten"],
            reason="user_delete_event",
        )
        assert repeated["event_entity_links"] == 0
        assert len(_outbox_rows(l2_store_with_schema.db_path)) == row_count
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_entity_forget_removes_target_projected_link_and_preserves_others(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-entity-forget"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    await l1.write_event_entities(
        [
            (event_id, "entity:target", "manual", 0.9),
            (event_id, "entity:manual", "manual", 0.8),
        ]
    )
    pipeline = _pipeline(l2_store_with_schema, l1)
    lease = await _running_lease(l2_store_with_schema, event_id, "worker-1")
    await _publish(
        l2_store_with_schema,
        pipeline,
        lease,
        [
            ("entity:target", "projected", 0.9),
            ("entity:keep", "projected", 0.8),
        ],
    )

    result = await l2_store_with_schema.forget_entity(
        entity_id="entity:target",
        operation_key="forget-op-1",
    )
    assert result["event_entity_links"] == 1
    rows_before_drain = _outbox_rows(l2_store_with_schema.db_path)
    assert {row[2] for row in rows_before_drain} == {"applied", "ready"}
    assert "entity:target" not in json.dumps(rows_before_drain)
    assert "entity:keep" in json.dumps(rows_before_drain)
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1

    with sqlite3.connect(l1.db_path) as db:
        projected = db.execute(
            """
            SELECT entity_id FROM l1_projected_event_entities
            WHERE event_id = ? ORDER BY entity_id
            """,
            (event_id,),
        ).fetchall()
        manual = db.execute(
            """
            SELECT entity_id FROM l1_event_entities
            WHERE event_id = ? ORDER BY entity_id
            """,
            (event_id,),
        ).fetchall()
    assert projected == [("entity:keep",)]
    assert manual == [("entity:manual",), ("entity:target",)]
    row_count = len(_outbox_rows(l2_store_with_schema.db_path))
    repeated = await l2_store_with_schema.forget_entity(
        entity_id="entity:target",
        operation_key="forget-op-1",
    )
    assert repeated["event_entity_links"] == 0
    assert len(_outbox_rows(l2_store_with_schema.db_path)) == row_count


@pytest.mark.asyncio
async def test_entity_forget_replaces_ready_batch_without_losing_unrelated_links(
    l2_store_with_schema,
    tmp_path,
) -> None:
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    leases = await _running_leases(
        l2_store_with_schema,
        ["evt-a", "evt-b"],
        "worker-1",
    )
    original = await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={
            "evt-a": [
                ("entity:target", "topic", 0.9),
                ("entity:a-keep", "topic", 0.8),
            ],
            "evt-b": [("entity:b-keep", "topic", 0.7)],
        },
        projection_leases=leases,
    )
    assert await l2_store_with_schema.complete_projection_jobs(leases) == 2

    result = await l2_store_with_schema.forget_entity(
        entity_id="entity:target",
        operation_key="forget-ready-batch",
    )
    assert result["event_entity_links"] == 2
    rows = _outbox_rows(l2_store_with_schema.db_path)
    assert {row[2] for row in rows if row[3] == original.batch_key} == {"discarded"}
    assert "entity:target" not in json.dumps(rows)
    assert sum(row[2] == "ready" for row in rows) == 2

    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 2
    links = await l1.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == ["entity:a-keep"]
    assert links["evt-b"] == ["entity:b-keep"]


@pytest.mark.asyncio
async def test_entity_forget_discards_entire_running_replay_batch(
    l2_store_with_schema,
    tmp_path,
) -> None:
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    first_a = await _running_lease(l2_store_with_schema, "evt-a", "seed-a")
    await _publish(
        l2_store_with_schema,
        pipeline,
        first_a,
        [
            ("entity:target", "topic", 0.9),
            ("entity:a-keep", "topic", 0.8),
        ],
    )
    first_b = await _running_lease(l2_store_with_schema, "evt-b", "seed-b")
    await _publish(
        l2_store_with_schema,
        pipeline,
        first_b,
        [("entity:b-old", "topic", 0.8)],
    )
    assert await l2_store_with_schema.request_projection_replay("evt-a")
    assert await l2_store_with_schema.request_projection_replay("evt-b")
    replay_rows = await l2_store_with_schema.claim_projection_jobs(
        consumer_name="replay-worker",
        limit=2,
    )
    replays = sorted(
        (L2ProjectionLease.from_dict(row) for row in replay_rows),
        key=lambda lease: lease.event_id,
    )
    assert (
        await l2_store_with_schema.mark_projection_jobs_running(
            replays,
            consumer_name="replay-worker",
        )
        == 2
    )
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={
            "evt-a": [("entity:target", "topic", 1.0)],
            "evt-b": [("entity:b-unpublished", "topic", 1.0)],
        },
        projection_leases=replays,
    )

    result = await l2_store_with_schema.forget_entity(
        entity_id="entity:target",
        operation_key="forget-running-replay",
    )
    assert result["event_entity_links"] == 1
    with pytest.raises(RuntimeError, match="not pending"):
        await l2_store_with_schema.complete_projection_jobs(replays)
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1

    links = await l1.get_event_entity_ids(["evt-a", "evt-b"])
    assert links["evt-a"] == ["entity:a-keep"]
    assert links["evt-b"] == ["entity:b-old"]
    with sqlite3.connect(l2_store_with_schema.db_path) as db:
        replay_states = db.execute(
            """
            SELECT DISTINCT state FROM l2_event_entity_link_outbox
            WHERE lease_token IN (?, ?)
            """,
            tuple(lease.lease_token for lease in replays),
        ).fetchall()
        job_states = db.execute(
            "SELECT status FROM l2_projection_jobs ORDER BY event_id"
        ).fetchall()
    assert replay_states == [("discarded",)]
    assert job_states == [("running",), ("running",)]
    outbox_rows = _outbox_rows(l2_store_with_schema.db_path)
    assert "entity:target" not in json.dumps(outbox_rows)
    assert "entity:b-unpublished" in json.dumps(outbox_rows)


@pytest.mark.asyncio
async def test_clear_generation_fences_old_outbox_and_direct_l2_clear_is_blocked(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-clear"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    lease = await _running_lease(l2_store_with_schema, event_id, "worker-1")
    await _publish(
        l2_store_with_schema,
        pipeline,
        lease,
        [("entity:old", "topic", 0.8)],
    )

    with pytest.raises(RuntimeError, match="requires unified memory clear"):
        await l2_store_with_schema.clear()
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:old"]
    assert _outbox_states(l2_store_with_schema.db_path) == [(event_id, 1, "applied")]

    clear_generation = await begin_event_entity_link_projection_clear(l2_store_with_schema.db_path)
    # Simulate the first unified-clear attempt failing before it can wipe L1.
    assert await pipeline._drain_event_entity_link_outbox() == 0
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:old"]

    await l1.clear(
        restart_workers=False,
        entity_link_clear_generation=clear_generation,
    )
    await l2_store_with_schema.clear(
        entity_link_clear_generation=clear_generation,
    )
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == []
    assert _outbox_states(l2_store_with_schema.db_path) == []


@pytest.mark.asyncio
async def test_old_prepared_applier_cannot_restore_links_after_l1_clear_fence(
    l2_store_with_schema,
    tmp_path,
) -> None:
    event_id = "evt-clear-race"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    lease = await _running_lease(l2_store_with_schema, event_id, "worker-1")
    await l2_store_with_schema.stage_event_entity_link_projections(
        desired_links_by_event={event_id: [("entity:stale", "topic", 0.9)]},
        projection_leases=[lease],
    )
    assert await l2_store_with_schema.complete_projection_jobs([lease]) == 1
    prepared = await l2_store_with_schema.prepare_event_entity_link_outbox()
    assert len(prepared) == 1
    stale_batch = prepared[0]

    clear_generation = await begin_event_entity_link_projection_clear(l2_store_with_schema.db_path)
    await l1.align_entity_link_projection_clear_generation(clear_generation)

    accepted = await l1.replace_projected_event_entities_batch(
        projections=[
            (
                item.event_id,
                item.revision,
                item.lease_token,
                item.attempt_count,
                item.clear_generation,
                list(item.desired_links),
            )
            for item in stale_batch.items
        ]
    )
    assert not accepted
    assert not await l2_store_with_schema.acknowledge_event_entity_link_projection_batch(
        stale_batch
    )
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == []


@pytest.mark.asyncio
async def test_unified_clear_l1_failure_restart_and_retry_converges(
    tmp_path,
    monkeypatch,
) -> None:
    await apply_memory_shared_schema(str(tmp_path / "memory.db"))
    memory = _unified_memory(tmp_path)
    await memory.initialize(start_workers=False)
    assert memory.l1 is not None and memory.l2 is not None
    assert memory.l2_pipeline is not None
    lease = await _running_lease(memory.l2, "evt-clear-retry", "worker-1")
    await _publish(
        memory.l2,
        memory.l2_pipeline,
        lease,
        [("entity:old", "topic", 0.8)],
    )

    async def fail_l1_clear(**_kwargs) -> int:  # type: ignore[no-untyped-def]
        raise RuntimeError("injected L1 clear failure")

    monkeypatch.setattr(memory.l1, "clear", fail_l1_clear)
    with pytest.raises(RuntimeError, match="injected L1 clear failure"):
        await memory.clear_all_memory()
    assert (await memory.l1.get_event_entity_ids(["evt-clear-retry"]))["evt-clear-retry"] == [
        "entity:old"
    ]
    await memory.shutdown()

    restarted = _unified_memory(tmp_path)
    await restarted.initialize(start_workers=False)
    try:
        assert restarted.l1 is not None
        assert (await restarted.l1.get_event_entity_ids(["evt-clear-retry"]))[
            "evt-clear-retry"
        ] == []
        await restarted.clear_all_memory()
        assert _outbox_states(restarted.memory_db_path) == []
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["policy_skip", "structured_only"])
async def test_successful_early_return_stages_empty_but_waits_for_completion(
    branch,
    l2_store_with_schema,
    tmp_path,
    monkeypatch,
) -> None:
    event_id = f"evt-{branch}"
    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1.initialize(start_workers=False)
    pipeline = _pipeline(l2_store_with_schema, l1)
    replay = await _published_projection_and_replay(
        l2_store_with_schema,
        pipeline,
        event_id,
    )

    plan = SimpleNamespace(skip_result=None, primary=SimpleNamespace(), decisions=[])
    monkeypatch.setattr(extraction_module, "build_l2_extraction_plan", lambda _events: plan)
    pipeline._load_batch_events = AsyncMock(return_value=[])  # type: ignore[method-assign]
    result = {"skipped": True, "skip_reason": branch}
    if branch == "policy_skip":
        pipeline._policy_skip_result = lambda _decision: result  # type: ignore[method-assign]
    else:
        pipeline._policy_skip_result = lambda _decision: None  # type: ignore[method-assign]
        pipeline._prepare_extraction_batch = AsyncMock(  # type: ignore[method-assign]
            return_value=SimpleNamespace(projection_leases=[replay])
        )
        pipeline._maybe_structured_only = AsyncMock(return_value=result)  # type: ignore[method-assign]

    assert await pipeline._extract_and_persist(_job(replay)) == result
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == ["entity:old"]
    assert await l2_store_with_schema.complete_projection_jobs([replay]) == 1
    assert await pipeline._drain_event_entity_link_outbox(raise_on_error=True) == 1
    assert (await l1.get_event_entity_ids([event_id]))[event_id] == []
