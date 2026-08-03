"""Pipeline contracts for queue-issued projection batch descriptors."""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite
import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.llm_service import L2LLMService
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.store import L2CognitionStore


def _event(event_id: str):  # type: ignore[no-untyped-def]
    timestamp = time.time()
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "content": event_id,
                "author_type": "user",
                "content_type": "text",
            },
            source="history",
            level=EventLevel.INFO,
            correlation_id=f"corr:{event_id}",
            timestamp=timestamp,
            event_id=event_id,
        )
    )


@pytest.mark.asyncio
async def test_pipeline_binds_each_final_owner_batch_before_running(tmp_path: Path) -> None:
    memory_db = str(tmp_path / "memory.db")
    l1_db = str(tmp_path / "l1.db")
    cognition_store = L2CognitionStore(db_path=memory_db)
    await cognition_store.initialize()
    l1_store = L1EventStore(db_path=l1_db, vector_enabled=False)
    await l1_store.initialize()
    entity_catalog = L2EntityCatalog(db_path=memory_db)
    await entity_catalog.initialize()
    pipeline = L2Pipeline(
        cognition_store,
        l1_store=l1_store,
        entity_catalog=entity_catalog,
        llm_service=L2LLMService(None),
    )

    event_owners = {
        "event-a1": "owner:a",
        "event-a2": "owner:a",
        "event-b1": "owner:b",
        "event-direct": None,
    }
    for event_id, owner in event_owners.items():
        await l1_store.store(_event(event_id))
        assert await cognition_store.enqueue_projection_job(
            event_id=event_id,
            source="history",
            event_type="UserMessage",
            batch_owner=owner,
        )

    assert await pipeline._claim_pending_projection_jobs(limit=4, force=True) == 3
    jobs = [
        await pipeline._extract_queue.get(),
        await pipeline._extract_queue.get(),
        await pipeline._extract_queue.get(),
    ]
    jobs_by_events = {tuple(job.event_ids): job for job in jobs}
    assert set(jobs_by_events) == {
        ("event-a1", "event-a2"),
        ("event-b1",),
        ("event-direct",),
    }

    async with aiosqlite.connect(memory_db) as db:
        db.row_factory = aiosqlite.Row
        rows = await (
            await db.execute(
                """
                SELECT event_id, status, batch_attempt_key,
                       batch_descriptor_json, batch_bound_at
                FROM l2_projection_jobs
                ORDER BY event_id
                """
            )
        ).fetchall()
    by_event = {str(row["event_id"]): dict(row) for row in rows}
    for event_ids, job in jobs_by_events.items():
        descriptors = {by_event[event_id]["batch_descriptor_json"] for event_id in event_ids}
        assert len(descriptors) == 1
        descriptor = json.loads(descriptors.pop())
        assert {item["event_id"] for item in descriptor["leases"]} == set(event_ids)
        assert {
            by_event[event_id]["batch_attempt_key"] for event_id in event_ids
        } == {job.attempt_key}
        assert all(by_event[event_id]["batch_bound_at"] is not None for event_id in event_ids)
        assert all(by_event[event_id]["status"] == "queued" for event_id in event_ids)

    assert by_event["event-a1"]["batch_attempt_key"] != by_event["event-b1"][
        "batch_attempt_key"
    ]
    owner_a_job = jobs_by_events[("event-a1", "event-a2")]
    assert await pipeline._start_extract_job(owner_a_job) is True
    async with aiosqlite.connect(memory_db) as db:
        statuses = await (
            await db.execute(
                """
                SELECT status FROM l2_projection_jobs
                WHERE event_id IN ('event-a1', 'event-a2')
                ORDER BY event_id
                """
            )
        ).fetchall()
    assert statuses == [("running",), ("running",)]


@pytest.mark.asyncio
async def test_pipeline_binds_missing_l1_event_before_terminal_failure(
    tmp_path: Path,
) -> None:
    memory_db = str(tmp_path / "memory.db")
    cognition_store = L2CognitionStore(db_path=memory_db)
    await cognition_store.initialize()
    l1_store = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    await l1_store.initialize()
    entity_catalog = L2EntityCatalog(db_path=memory_db)
    await entity_catalog.initialize()
    pipeline = L2Pipeline(
        cognition_store,
        l1_store=l1_store,
        entity_catalog=entity_catalog,
        llm_service=L2LLMService(None),
    )
    assert await cognition_store.enqueue_projection_job(
        event_id="event-missing-l1",
        source="history",
        event_type="UserMessage",
    )

    assert await pipeline._claim_pending_projection_jobs(limit=1, force=True) == 0
    async with aiosqlite.connect(memory_db) as db:
        row = await (
            await db.execute(
                """
                SELECT status, last_error, lease_token, batch_attempt_key,
                       batch_descriptor_json, batch_bound_at
                FROM l2_projection_jobs
                WHERE event_id = 'event-missing-l1'
                """
            )
        ).fetchone()
    assert row == ("failed", "l1_event_not_found", None, None, None, None)
