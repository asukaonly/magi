from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.memory.portrait_routes import (
    build_router,
    override_service_for_test,
)
from magi.memory.portrait.contracts import PortraitObservation, PortraitPayload


def _app():
    app = FastAPI()
    app.include_router(build_router(), prefix="/api/memory")
    return app


def test_returns_payload_shape():
    service = AsyncMock()
    service.get_portrait = AsyncMock(return_value=PortraitPayload(
        session_id="s1",
        persona_id="p1",
        topic="罗永浩",
        generated_at=1700000000,
        observations=[
            PortraitObservation(kind="reflection", text="你又在想老罗", basis_count=1,
                                basis_summary="1 条", basis_refs=["m1"]),
        ],
    ))
    with override_service_for_test(service):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait", params={"session_id": "s1", "user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"
    assert body["topic"] == "罗永浩"
    assert body["observations"][0]["text"] == "你又在想老罗"
    assert body["is_cold_start"] is False


def test_force_param_is_forwarded():
    service = AsyncMock()
    service.get_portrait = AsyncMock(return_value=PortraitPayload(
        session_id="s1", persona_id="p1", topic="", generated_at=0,
        is_cold_start=True, cold_start_line="hi",
    ))
    with override_service_for_test(service):
        client = TestClient(_app())
        client.get("/api/memory/portrait", params={"session_id": "s1", "user_id": "u1", "force": "true"})
    assert service.get_portrait.await_args.kwargs["force"] is True


def test_missing_session_id_returns_422():
    service = AsyncMock()
    with override_service_for_test(service):
        client = TestClient(_app())
        resp = client.get("/api/memory/portrait", params={"user_id": "u1"})
    assert resp.status_code == 422
