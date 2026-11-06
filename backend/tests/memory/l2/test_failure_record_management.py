"""Ignoring terminal extraction failures is durable, reversible, and source-safe."""

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.projection.queue import ProjectionJobQueue


async def add_job(store, event_id, *, reason="content_filter", source="chat", status="failed"):
    await store.enqueue_projection_job(event_id=event_id, source=source, event_type="UserMessage")
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """UPDATE l2_projection_jobs SET status=?, attempt_count=5, last_error=?,
                terminal_at=10, updated_at=20 WHERE event_id=?""",
            (status, f"L2 LLM call failed for extraction (kind={reason}, status=400)", event_id),
        )
        await db.commit()


@pytest.mark.asyncio
async def test_ignored_records_survive_reopen_and_never_requeue_implicitly(l2_store_with_schema):
    store = l2_store_with_schema
    await add_job(store, "blocked")
    selection = [{"event_id": "blocked", "expected_updated_at": 20.0}]
    assert await store.set_projection_failure_disposition(action="ignore", selections=selection) == {"changed_count": 1, "unchanged_count": 0}
    assert (await store.get_projection_backlog_stats())["failed"] == 0
    assert (await store.get_projection_failure_summary())["total"] == 0
    reopened = ProjectionJobQueue(db_path=store.db_path)
    assert await reopened.request_replay(event_id="blocked") is False
    assert await reopened.enqueue(event_id="blocked", source="chat", event_type="UserMessage") is False
    assert (await reopened.retry_failed())["queued_count"] == 0
    ignored = await reopened.list_failure_records(status="ignored")
    record = ignored["items"][0]
    assert record["last_failed_at"] == 10
    assert record["attempt_count"] == 5
    assert record["reason"] == "content_filter"
    assert record["retry_allowed"] is True
    result = await reopened.set_failure_disposition(action="restore", selections=[{
        "event_id": record["event_id"], "expected_updated_at": record["updated_at"],
    }])
    assert result["changed_count"] == 1
    assert (await reopened.get_backlog_stats())["failed"] == 1
    assert (await reopened.get_backlog_stats())["pending"] == 0
    assert (await reopened.list_failure_records())["items"][0]["error"] == record["error"]
    assert await reopened.retry_failed() == {"queued_count": 1, "remaining_count": 0}
    pending = await reopened.claim(consumer_name="restored", limit=1)
    assert pending[0]["max_events"] == 1


@pytest.mark.asyncio
async def test_manual_retry_isolates_content_rejections_and_excludes_missing_sources(l2_store_with_schema):
    store = l2_store_with_schema
    await add_job(store, "a-filtered", reason="content_filter")
    await add_job(store, "b-inspected", reason="content_inspection_failed")
    await add_job(store, "c-timeout", reason="timeout")
    await add_job(store, "0-missing")
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET last_error='l1_event_not_found' WHERE event_id='0-missing'")
        await db.commit()
    summary = await store.get_projection_failure_summary()
    assert summary["total"] == 4
    assert summary["retryable_count"] == 3
    assert await store.request_projection_replay("0-missing") is False
    assert await store.request_projection_replay("a-filtered") is True
    assert await store.retry_failed_projection_jobs(limit=1) == {"queued_count": 1, "remaining_count": 2}
    assert (await store.retry_failed_projection_jobs(event_ids=["a-filtered", "b-inspected"]))["queued_count"] == 0
    assert await store.retry_failed_projection_jobs() == {"queued_count": 1, "remaining_count": 1}
    async with sqlite_connection_async(store.db_path) as db:
        rows = await (await db.execute("SELECT event_id, max_events, min_ready_events FROM l2_projection_jobs WHERE status='pending' ORDER BY event_id")).fetchall()
    assert [tuple(row) for row in rows] == [("a-filtered", 1, 1), ("b-inspected", 1, 1), ("c-timeout", None, None)]


@pytest.mark.asyncio
async def test_disposition_fences_stale_active_and_forgotten_records(l2_store_with_schema):
    store = l2_store_with_schema
    for event_id, status in [("current", "failed"), ("stale", "failed"), ("running", "running"), ("forgotten", "failed")]:
        await add_job(store, event_id, status=status)
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET updated_at=21 WHERE event_id='stale'")
        await db.execute("INSERT INTO memory_source_event_tombstones VALUES ('forgotten', 'forgotten', 1)")
        await db.commit()
    selections = [{"event_id": key, "expected_updated_at": 20.0} for key in ["current", "stale", "running", "forgotten"]]
    assert await store.set_projection_failure_disposition(action="ignore", selections=selections) == {"changed_count": 1, "unchanged_count": 3}
    assert (await store.list_projection_failure_records(status="ignored"))["total"] == 1
    assert (await store.list_projection_failure_records())["total"] == 1


@pytest.mark.asyncio
async def test_reason_and_source_filters_apply_before_pagination(l2_store_with_schema):
    store = l2_store_with_schema
    for index in range(7):
        await add_job(store, f"record-{index}", source="notes" if index < 5 else "chat", reason="content_filter" if index % 2 else "timeout")
    page = await store.list_projection_failure_records(source="notes", reason="content_filter", limit=1, offset=1)
    assert page["total"] == 2
    assert [record["event_id"] for record in page["items"]] == ["record-3"]
