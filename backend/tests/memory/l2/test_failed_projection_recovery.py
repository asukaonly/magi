"""Public failure recovery preserves active attempts and deletion barriers."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import FastAPI

from magi.core.sqlite import sqlite_connection_async
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.api.routers.memory.l2.status import build_background_pending_response
from magi.api.routers.memory.helpers import build_l2_pending_breakdown, build_embedding_pending


@pytest.mark.asyncio
async def test_bounded_retry_only_resets_failed_ungoverned_jobs(l2_store_with_schema):
    store = l2_store_with_schema
    for index in range(4):
        await store.enqueue_projection_job(event_id=f'failed-{index}', source='chat', event_type='UserMessage')
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET status = 'failed', attempt_count = 5")
        await db.execute("INSERT INTO memory_source_event_tombstones (event_id, reason, created_at) VALUES ('failed-3', 'forgotten', 1)")
        await db.commit()
    assert await store.retry_failed_projection_jobs(limit=2) == {'queued_count': 2, 'remaining_count': 1}
    assert await store.retry_failed_projection_jobs(limit=2) == {'queued_count': 1, 'remaining_count': 0}
    assert await store.retry_failed_projection_jobs(limit=2) == {'queued_count': 0, 'remaining_count': 0}
    async with sqlite_connection_async(store.db_path) as db:
        rows = await (await db.execute("SELECT event_id, status, attempt_count FROM l2_projection_jobs ORDER BY event_id")).fetchall()
    assert [tuple(row) for row in rows] == [('failed-0', 'pending', 0), ('failed-1', 'pending', 0), ('failed-2', 'pending', 0), ('failed-3', 'failed', 5)]


@pytest.mark.asyncio
async def test_retry_is_reachable_through_public_router(monkeypatch):
    memory = SimpleNamespace(l2=object(), l2_pipeline=object(),
        retry_failed_l2_extractions=AsyncMock(return_value={'queued_count': 2, 'remaining_count': 3}))
    monkeypatch.setattr('magi.api.routers.memory.l2.operations_routes._resolve_unified_memory', lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS['memory']), prefix='/api/memory')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/memory/l2/retry-failed', json={'limit': 2})
        assert response.status_code == 200
        assert response.json() == {'queued_count': 2, 'remaining_count': 3}
        assert (await client.post('/api/memory/l2/retry-failed', json={'limit': 101})).status_code == 422
    memory.retry_failed_l2_extractions.assert_awaited_once_with(limit=2)


def test_terminal_failures_are_not_reported_as_idle():
    result = build_background_pending_response(
        l2_pending=build_l2_pending_breakdown({}, {'failed': 3}),
        l2_edge_pending={}, l1_pending=build_embedding_pending(None),
        l3_pending=build_embedding_pending(None), l4_pending=build_embedding_pending(None))
    assert result['all_idle'] is False
    assert result['l2']['projection_failed'] == 3
