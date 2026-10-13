"""Public recovery and content-free status for accepted conversation processing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routers.memory import memory_router
from magi.api.routers.memory.post_turn_status import with_post_turn_processing
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


@pytest.mark.asyncio
async def test_post_turn_backlog_is_included_without_analysis(monkeypatch):
    service = SimpleNamespace(get_status=AsyncMock(return_value={
        "pending": 2, "claimed": 1, "failed": 1, "error_kinds": ["TimeoutError"],
        "analysis_json": "private analysis",
    }))
    monkeypatch.setattr('magi.api.routers.memory.post_turn_status.resolve_post_turn_service', lambda: service)
    result = await with_post_turn_processing({"total_pending": 4, "all_idle": True})
    assert result['total_pending'] == 7
    assert result['all_idle'] is False
    assert 'analysis_json' not in result['post_turn']


@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable', [True, False])
async def test_unavailable_status_does_not_fabricate_zero_backlog(monkeypatch, unavailable):
    service = None if unavailable else SimpleNamespace(get_status=AsyncMock(side_effect=RuntimeError('storage offline')))
    monkeypatch.setattr('magi.api.routers.memory.post_turn_status.resolve_post_turn_service', lambda: service)
    result = await with_post_turn_processing({"total_pending": 4, "all_idle": True})
    assert result == {"total_pending": 4, "all_idle": False, "post_turn": None}


def test_retry_is_bounded_and_publicly_reachable(monkeypatch):
    service = SimpleNamespace(retry_failed=AsyncMock(return_value=2), get_status=AsyncMock(return_value={
        'pending': 2, 'claimed': 0, 'failed': 3, 'error_kinds': ['TimeoutError'],
    }))
    monkeypatch.setattr('magi.api.routers.memory.l2.operations_routes.resolve_post_turn_service', lambda: service)
    app = FastAPI()
    app.include_router(_build_public_router(memory_router, _PUBLIC_ROUTE_METHODS['memory']), prefix='/api/memory')
    client = TestClient(app)
    response = client.post('/api/memory/post-turn/retry-failed', json={'limit': 2})
    assert response.status_code == 200
    assert response.json() == {'queued_count': 2, 'remaining_count': 3}
    service.retry_failed.assert_awaited_once_with(limit=2)
    assert client.post('/api/memory/post-turn/retry-failed', json={'limit': 101}).status_code == 422
    monkeypatch.setattr('magi.api.routers.memory.l2.operations_routes.resolve_post_turn_service', lambda: None)
    assert client.post('/api/memory/post-turn/retry-failed', json={'limit': 2}).status_code == 503
