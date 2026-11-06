"""Failure summaries preserve counts and governance without exposing source text."""

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.projection.diagnostics import projection_failure_reason


@pytest.mark.asyncio
async def test_groups_causes_across_requests_and_excludes_forgotten_jobs(l2_store_with_schema):
    store = l2_store_with_schema
    for index in range(5):
        await store.enqueue_projection_job(event_id=f"event-{index}", source="chrome-history", event_type="visit")
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            "UPDATE l2_projection_jobs SET status='failed', last_error=?, updated_at=? WHERE event_id=?",
            [(f"L2 LLM call failed for extraction (kind=auth, status=401, request_id={index})", index + 1, f"event-{index}") for index in range(4)],
        )
        await db.execute("INSERT INTO memory_source_event_tombstones VALUES ('event-3', 'forgotten', 1)")
        await db.commit()
    summary = await store.get_projection_failure_summary()
    assert summary["total"] == 3
    assert (await store.get_projection_backlog_stats())["failed"] == 3
    assert summary["other_count"] == 0
    assert summary["groups"] == [{
        "source": "chrome-history", "reason": "auth", "count": 3,
        "last_failed_at": 3.0,
        "error": "L2 LLM call failed for extraction (kind=auth, status=401, request_id=2)",
    }]
    await store.retry_failed_projection_jobs()
    assert await store.get_projection_failure_summary() == {"total": 0, "groups": [], "other_count": 0}


@pytest.mark.asyncio
async def test_summary_caps_visible_groups_without_losing_total(l2_store_with_schema):
    store = l2_store_with_schema
    for index in range(15):
        await store.enqueue_projection_job(event_id=f"event-{index}", source=f"source-{index}", event_type="visit")
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET status='failed', last_error=NULL")
        await db.commit()
    summary = await store.get_projection_failure_summary()
    assert summary["total"] == 15
    assert len(summary["groups"]) == 12
    assert summary["other_count"] == 3
    assert all(group["reason"] == "unknown" and group["error"] is None for group in summary["groups"])


@pytest.mark.parametrize(("error", "reason"), [
    (None, "unknown"),
    ("A record mentions timeout and auth", "unknown"),
    ("No L2 LLM adapter is available for extraction", "model_unavailable"),
    ("L2 LLM response is not valid JSON", "invalid_response"),
    ("projection_attempt_stale", "interrupted"),
    ("l1_event_not_found", "missing_source"),
])
def test_only_known_diagnostics_are_interpreted(error, reason):
    assert projection_failure_reason(error) == reason
