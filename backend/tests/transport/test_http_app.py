from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


def test_transport_app_registers_health_endpoint() -> None:
    from magi.transport.http_app import create_transport_app

    app = create_transport_app()
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200


def test_transport_app_exposes_ready_state(monkeypatch) -> None:
    from magi.transport.http_app import create_transport_app

    async def _fake_runtime_status(app):
        return {
            "api_ready": True,
            "runtime_ready": False,
            "worker_ready": True,
            "infrastructure_ready": True,
            "llm_ready": False,
            "agent_runtime_ready": False,
            "queue_backlog_healthy": True,
            "status": "degraded",
            "runtime_status": "deferred",
            "startup_state": "deferred",
            "deferred_reason": "llm_selection_pending",
            "startup_detail": None,
        }

    monkeypatch.setattr("magi.transport.http_app.get_runtime_system_status", _fake_runtime_status)

    app = create_transport_app()
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "ready": False,
        "status": "degraded",
        "runtime_ready": False,
        "worker_ready": True,
        "llm_ready": False,
        "agent_runtime_ready": False,
        "runtime_status": "deferred",
        "startup_state": "deferred",
        "deferred_reason": "llm_selection_pending",
    }


def test_transport_app_exposes_runtime_health_details(monkeypatch) -> None:
    from magi.transport.http_app import create_transport_app

    async def _fake_runtime_status(app):
        return {
            "api_ready": True,
            "runtime_ready": True,
            "worker_ready": True,
            "infrastructure_ready": True,
            "llm_ready": True,
            "agent_runtime_ready": True,
            "queue_backlog_healthy": True,
            "status": "ready",
            "runtime_status": "ready",
            "startup_state": "ready",
            "deferred_reason": None,
            "startup_detail": None,
            "pending_commands": 4,
        }

    monkeypatch.setattr("magi.transport.http_app.get_runtime_system_status", _fake_runtime_status)

    app = create_transport_app()
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ready",
        "version": "1.0.0",
        "api_ready": True,
        "runtime_ready": True,
        "worker_ready": True,
        "infrastructure_ready": True,
        "llm_ready": True,
        "agent_runtime_ready": True,
        "runtime_status": "ready",
        "startup_state": "ready",
        "deferred_reason": None,
        "startup_detail": None,
        "queue_backlog_healthy": True,
        "pending_commands": 4,
    }


def test_transport_app_registers_runtime_shutdown_endpoint(monkeypatch) -> None:
    from magi.transport.http_app import create_transport_app

    scheduled: list[bool] = []

    monkeypatch.setattr(
        "magi.transport.http_app._schedule_process_shutdown",
        lambda delay_seconds=0.1: scheduled.append(True),
    )

    app = create_transport_app()
    client = TestClient(app)

    response = client.post("/api/runtime/shutdown")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert scheduled == [True]
