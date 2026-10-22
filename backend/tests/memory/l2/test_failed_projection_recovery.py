"""Public failure recovery preserves active attempts and deletion barriers."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
from fastapi import FastAPI

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.core.sqlite import sqlite_connection_async
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.memory import memory_router
from magi.api.routers.memory.l2.status import build_background_pending_response
from magi.api.routers.memory.helpers import build_l2_pending_breakdown, build_embedding_pending
from magi.memory.store_l2_operations import UnifiedMemoryL2OperationsMixin


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
    memory.retry_failed_l2_extractions.assert_awaited_once_with(limit=2, event_ids=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "2"},
    {"event_ids": []}, {"event_ids": None}, {"event_ids": "failed-1"},
    {"event_ids": [""]}, {"event_ids": [" "]}, {"event_ids": [" failed-1"]},
    {"event_ids": [1]}, {"event_ids": ["x" * 513]},
    {"event_ids": ["failed-1"] * 101}, {"event_id": "failed-1"},
])
async def test_public_retry_rejects_invalid_selection_without_work(monkeypatch, body):
    memory = SimpleNamespace(l2=object(), l2_pipeline=object(),
        retry_failed_l2_extractions=AsyncMock())
    monkeypatch.setattr('magi.api.routers.memory.l2.operations_routes._resolve_unified_memory', lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS['memory']), prefix='/api/memory')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/memory/l2/retry-failed', json=body)
    assert response.status_code == 422
    memory.retry_failed_l2_extractions.assert_not_awaited()


@pytest.mark.asyncio
async def test_selected_retry_traverses_public_router_and_real_queue(l2_store_with_schema, monkeypatch):
    store = l2_store_with_schema
    states = {
        'selected': 'failed', 'provider-failure': 'failed',
        'forgotten': 'failed', 'time-blocked': 'failed',
        'pending': 'pending', 'queued': 'queued', 'running': 'running',
        'completed': 'completed',
    }
    for event_id in states:
        await store.enqueue_projection_job(event_id=event_id, source='chat', event_type='UserMessage')
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            """UPDATE l2_projection_jobs SET status=?, attempt_count=5,
                last_error='original error', updated_at=1 WHERE event_id=?""",
            [(state, event_id) for event_id, state in states.items()],
        )
        await db.execute("INSERT INTO memory_source_event_tombstones VALUES ('forgotten', 'forgotten', 1)")
        await db.execute("""INSERT INTO memory_forget_operations(
            operation_id, selector_kind, selector_hash, selector_json,
            reason, created_at, updated_at
        ) VALUES ('time-forget', 'time_range', 'time-selection', '{}', 'test', 1, 1)""")
        await db.execute("""INSERT INTO memory_projection_blocks
            VALUES ('episode_formation', 'time:selection', 'time-blocked', 'time-forget', 1)""")
        await db.commit()
        before = dict((row[0], tuple(row)) for row in await (await db.execute(
            'SELECT * FROM l2_projection_jobs'
        )).fetchall())

    class Host(UnifiedMemoryL2OperationsMixin):
        def __init__(self):
            self.l2 = store
            self.l2_pipeline = SimpleNamespace(flush_pending_projection_jobs=AsyncMock())
            self.barrier = AsyncOperationBarrier()

        def memory_operation_guard(self):
            return self.barrier.operation()

    memory = Host()
    monkeypatch.setattr('magi.api.routers.memory.l2.operations_routes._resolve_unified_memory', lambda: memory)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS['memory']), prefix='/api/memory')
    selected_ids = ['selected', 'selected', 'forgotten', 'time-blocked', 'pending', 'queued', 'running', 'completed', 'missing']
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/api/memory/l2/retry-failed', json={'event_ids': selected_ids})
        assert response.status_code == 200
        assert response.json() == {'queued_count': 1, 'remaining_count': 1}
        repeated = await client.post('/api/memory/l2/retry-failed', json={'event_ids': selected_ids})
        assert repeated.json() == {'queued_count': 0, 'remaining_count': 1}
        assert (await client.post('/api/memory/l2/extract/selected')).status_code == 404
        assert (await client.post('/api/memory/post-turn/retry-failed', json={'event_ids': ['selected']})).status_code == 422
    memory.l2_pipeline.flush_pending_projection_jobs.assert_awaited_once()
    async with sqlite_connection_async(store.db_path) as db:
        after = dict((row[0], tuple(row)) for row in await (await db.execute(
            'SELECT * FROM l2_projection_jobs'
        )).fetchall())
        selected = await (await db.execute(
            "SELECT status, attempt_count, last_error FROM l2_projection_jobs WHERE event_id='selected'"
        )).fetchone()
    assert tuple(selected) == ('pending', 0, None)
    assert {key: row for key, row in before.items() if key != 'selected'} == {
        key: row for key, row in after.items() if key != 'selected'
    }


@pytest.mark.asyncio
async def test_selected_retry_applies_limit_and_keeps_global_remaining_count(l2_store_with_schema):
    store = l2_store_with_schema
    for event_id in ['selected-1', 'selected-2', 'unselected']:
        await store.enqueue_projection_job(event_id=event_id, source='chat', event_type='UserMessage')
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET status='failed', updated_at=1, attempt_count=5")
        await db.commit()
    selection = ['selected-1', 'selected-1', 'selected-2']
    assert await store.retry_failed_projection_jobs(limit=1, event_ids=selection) == {'queued_count': 1, 'remaining_count': 2}
    assert await store.retry_failed_projection_jobs(limit=1, event_ids=selection) == {'queued_count': 1, 'remaining_count': 1}
    assert await store.retry_failed_projection_jobs(limit=1, event_ids=selection) == {'queued_count': 0, 'remaining_count': 1}


@pytest.mark.asyncio
@pytest.mark.parametrize('selection', [[], [' '], [1], ['x' * 513], ['selected'] * 101, 'selected'])
async def test_queue_rejects_invalid_selection_before_reset(l2_store_with_schema, selection):
    store = l2_store_with_schema
    await store.enqueue_projection_job(event_id='selected', source='chat', event_type='UserMessage')
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute("UPDATE l2_projection_jobs SET status='failed', attempt_count=5")
        await db.commit()
    with pytest.raises(ValueError):
        await store.retry_failed_projection_jobs(event_ids=selection)
    async with sqlite_connection_async(store.db_path) as db:
        row = await (await db.execute('SELECT status, attempt_count FROM l2_projection_jobs')).fetchone()
    assert tuple(row) == ('failed', 5)


def test_terminal_failures_are_not_reported_as_idle():
    result = build_background_pending_response(
        l2_pending=build_l2_pending_breakdown({}, {'failed': 3}),
        l2_edge_pending={}, l1_pending=build_embedding_pending(None),
        l3_pending=build_embedding_pending(None), l4_pending=build_embedding_pending(None))
    assert result['all_idle'] is False
    assert result['l2']['projection_failed'] == 3
