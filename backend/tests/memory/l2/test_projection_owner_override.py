from __future__ import annotations

from _shared.memory_stores import build_l1_store

import time
from pathlib import Path

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _make_memory_event(*, event_id: str, content: str = "visited page"):
    timestamp = time.time()
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": None,
                "session_id": None,
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            source="chrome_history",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            timestamp=timestamp,
        event_id=event_id),
        )


@pytest.mark.asyncio
async def test_projection_rows_prefer_effective_batch_owner_over_metadata_json(tmp_path: Path):
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    memory_db = str(tmp_path / "memory.db")
    l1_db = str(tmp_path / "l1.db")
    cognition_store = L2CognitionStore(db_path=memory_db)
    await cognition_store.initialize()
    entity_catalog = L2EntityCatalog(db_path=memory_db)
    await entity_catalog.initialize()
    l1_store = build_l1_store(db_path=l1_db, vector_enabled=False)
    await l1_store.initialize()

    event = _make_memory_event(event_id="evt-chrome-1")
    event.metadata_json = {
        "l2_batch_owner": "chrome_history:Default:github.com",
        "l2_batch_max_events": 20,
    }
    await l1_store.store(event)

    pipeline = L2Pipeline(
        cognition_store,
        l1_store=l1_store,
        entity_catalog=entity_catalog,
        llm_service=L2LLMService(None),
    )
    jobs, missing_event_ids = await pipeline._build_extract_jobs_from_projection_rows(
        [
            {
                "event_id": "evt-chrome-1",
                "lease_token": "lease-owner-override",
                "attempt_count": 1,
                "batch_owner": "chrome_history:Default:github.com",
                "effective_batch_owner": "chrome_history:Default:catchup:2",
            }
        ]
    )

    assert missing_event_ids == []
    assert len(jobs) == 1
    assert jobs[0].bucket_key == "owner:chrome_history:Default:catchup:2"
    assert jobs[0].event_ids == ["evt-chrome-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_content_retry_stays_individual_across_restart_and_owner_grouping(
    tmp_path, l2_store_with_schema, monkeypatch, force,
):
    from magi.core.sqlite import sqlite_connection_async
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.projection.queue import ProjectionJobQueue

    store = l2_store_with_schema
    l1 = build_l1_store(db_path=str(tmp_path / "originals.db"), vector_enabled=False)
    await l1.initialize()
    catalog = L2EntityCatalog(db_path=store.db_path)
    await catalog.initialize()
    error = "L2 LLM call failed for extraction (kind=content_filter, status=400)"
    for event_id in ["a-normal", "b-rejected", "c-peer", "d-normal", "ignored"]:
        event = _make_memory_event(event_id=event_id)
        event.metadata_json = {"l2_batch_owner": "shared-owner", "l2_batch_max_events": 20}
        await l1.store(event)
        await store.enqueue_projection_job(
            event_id=event_id, source="chrome_history", event_type="UserMessage",
            batch_owner="shared-owner", catch_up_owner="shared-tail", max_events=20, min_ready_events=20,
        )
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """UPDATE l2_projection_jobs SET status='failed', last_error=?, updated_at=20
                WHERE event_id IN ('b-rejected', 'c-peer', 'ignored')""", (error,),
        )
        await db.commit()
    await store.set_projection_failure_disposition(action="ignore", selections=[{
        "event_id": "ignored", "expected_updated_at": 20.0,
    }])
    assert await store.retry_failed_projection_jobs() == {"queued_count": 2, "remaining_count": 0}

    # Recreate the queue and pipeline from durable state, including catch-up claims.
    store._projection_queue = ProjectionJobQueue(db_path=store.db_path)
    monkeypatch.setattr("magi.memory.l2.projection.queue.DEFAULT_L2_CATCH_UP_PENDING_THRESHOLD", 1)
    pipeline = L2Pipeline(store, l1_store=l1, entity_catalog=catalog, llm_service=L2LLMService(None))
    assert await pipeline._claim_pending_projection_jobs(force=force) == 3
    jobs = [pipeline._extract_queue.get_nowait() for _ in range(3)]
    assert sorted(sorted(job.event_ids) for job in jobs) == [["a-normal", "d-normal"], ["b-rejected"], ["c-peer"]]
    for job in jobs:
        assert await store.mark_projection_jobs_running(
            job.projection_leases, consumer_name=pipeline._projection_consumer_name,
        ) == len(job.event_ids)
        if job.event_ids == ["b-rejected"]:
            assert await store.fail_projection_jobs(job.projection_leases, error_text=error, requeue=False) == 1
        else:
            await store.stage_event_entity_link_projections(
                desired_links_by_event={event_id: [] for event_id in job.event_ids},
                projection_leases=job.projection_leases,
            )
            assert await store.complete_projection_jobs(job.projection_leases) == len(job.event_ids)
        pipeline._extract_queue.task_done()
    failures = await store.list_projection_failure_records()
    assert [item["event_id"] for item in failures["items"]] == ["b-rejected"]
    assert (await store.list_projection_failure_records(status="ignored"))["total"] == 1
    assert (await store.get_projection_backlog_stats())["pending"] == 0
