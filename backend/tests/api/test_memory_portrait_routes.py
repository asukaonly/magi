from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_routes import (
    build_router,
    get_service,
    override_service_for_test,
)
from magi.chat.portrait.contracts import ChatPortraitObservation, ChatPortraitPayload
from magi.core.container import get_container


def _app():
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router

    app = FastAPI()
    app.include_router(
        _build_public_router(build_router(), _PUBLIC_ROUTE_METHODS["memory"]), prefix="/api/memory"
    )
    return app


@pytest.mark.parametrize("force,cold", [(None, False), ("false", False), ("true", True)])
def test_public_portrait_serializes_nested_payload_and_forwards_context(force, cold):
    observations = (
        []
        if cold
        else [
            ChatPortraitObservation(
                kind="reflection",
                text="你最近老聊落寞英雄",
                basis_count=5,
                basis_summary="5 条反思",
                basis_refs=["mem-a", "mem-b"],
            )
        ]
    )
    payload = ChatPortraitPayload(
        session_id="s1",
        persona_id="p1",
        topic="" if cold else "罗永浩",
        generated_at=1700000000,
        observations=observations,
        is_cold_start=cold,
        cold_start_line="七号还在认识你" if cold else None,
        cold_start_reason="insufficient_evidence" if cold else None,
        is_stale=not cold,
    )
    service = AsyncMock()
    service.get_portrait.return_value = payload
    params = {"session_id": "s1", "user_id": "u1"}
    if force is not None:
        params["force"] = force
    with override_service_for_test(service), TestClient(_app()) as client:
        response = client.get("/api/memory/portrait", params=params)
    assert response.status_code == 200
    service.get_portrait.assert_awaited_once_with(
        user_id="u1", session_id="s1", force=force == "true"
    )
    assert response.json() == {
        "session_id": "s1",
        "persona_id": "p1",
        "topic": "" if cold else "罗永浩",
        "generated_at": 1700000000,
        "observations": (
            []
            if cold
            else [
                {
                    "kind": "reflection",
                    "text": "你最近老聊落寞英雄",
                    "basis_count": 5,
                    "basis_summary": "5 条反思",
                    "basis_refs": ["mem-a", "mem-b"],
                }
            ]
        ),
        "is_cold_start": cold,
        "cold_start_line": "七号还在认识你" if cold else None,
        "cold_start_reason": "insufficient_evidence" if cold else None,
        "is_stale": not cold,
    }


@pytest.mark.parametrize(
    "params", [{"user_id": "u1"}, {"session_id": "", "user_id": "u1"}, {"session_id": "s1"}]
)
def test_portrait_rejects_missing_context_before_service(params):
    service = AsyncMock()
    with override_service_for_test(service), TestClient(_app()) as client:
        response = client.get("/api/memory/portrait", params=params)
    assert response.status_code == 422
    service.get_portrait.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_is_resolved_from_runtime_binding():
    service = object()
    container = get_container()
    container.chat_portrait_service.override(providers.Object(service))

    try:
        assert await get_service() is service
    finally:
        container.chat_portrait_service.reset_override()
