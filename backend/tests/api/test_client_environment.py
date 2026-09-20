"""Exercise client environment validation through the public message router."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from magi.api.routers import messages_dispatch
from magi.api.routers.messages import user_messages_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.events.user_message_dispatch import MessageDispatchOutcome


@pytest.fixture
def message_api(monkeypatch):
    dispatch = AsyncMock(
        return_value=MessageDispatchOutcome(
            success=True, user_id="alice", session_id="s1", turn_id="t1"
        )
    )
    monkeypatch.setattr(
        messages_dispatch, "_ensure_runtime_ready_for_user_message", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(messages_dispatch, "dispatch_user_message", dispatch)
    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )
    monkeypatch.setattr(messages_dispatch, "get_current_personality", lambda: "test")
    app = FastAPI()
    app.include_router(
        _build_public_router(user_messages_router, _PUBLIC_ROUTE_METHODS["messages"]),
        prefix="/api/messages",
    )
    with TestClient(app) as client:
        yield client, dispatch


def test_public_send_accepts_typed_environment_without_metadata_promotion(message_api):
    client, dispatch = message_api
    response = client.post(
        "/api/messages/send",
        json={
            "user_id": "alice",
            "session_id": "s1",
            "message": "Hello",
            "client_environment": {"timezone": "Asia/Shanghai", "os": "windows"},
            "metadata": {"client_environment": {"timezone": "Europe/London"}},
        },
    )
    assert response.status_code == 200, response.text
    kwargs = dispatch.await_args.kwargs
    assert kwargs["client_environment"].timezone == "Asia/Shanghai"
    assert "client_environment" not in kwargs["metadata"]


@pytest.mark.parametrize(
    "environment",
    [
        {"timezone": "invalid/zone"},
        {"timezone": "/etc/passwd"},
        {"os": "<instructions>"},
        {"timezone": "UTC", "device_id": "spoofed"},
    ],
)
def test_public_send_rejects_invalid_environment_before_dispatch(message_api, environment):
    client, dispatch = message_api
    response = client.post(
        "/api/messages/send",
        json={"session_id": "s1", "message": "Hello", "client_environment": environment},
    )
    assert response.status_code == 422
    dispatch.assert_not_awaited()
