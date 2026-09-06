"""Real-store diagnostics through the product router, without model calls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.api.routers.memory import quality_routes
from magi.api.routers.memory.router import memory_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router


@pytest.mark.asyncio
async def test_quality_surface_separates_raw_records_from_profile(
    l2_store_with_schema, monkeypatch
):
    unified = SimpleNamespace(
        l1=SimpleNamespace(count_events=AsyncMock(return_value=23)),
        l2=l2_store_with_schema,
        memory_operation_guard=AsyncOperationBarrier().operation,
        get_l2_pipeline_stats=lambda: {"events_evaluated": 10, "events_eligible": 0},
    )
    monkeypatch.setattr(quality_routes, "_resolve_unified_memory", lambda: unified)
    app = FastAPI()
    app.include_router(
        _build_public_router(memory_router, _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/memory/quality", params={"user_id": "local_user"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"]["scope"] == "process_attempts"
    assert payload["stored"]["l1_events"] == 23
    assert payload["user"]["profile_visible_items"] == 0
    assert payload["user"]["grounded_claims"] == 0
