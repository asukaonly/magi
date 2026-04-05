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
            "api_ready": bool(getattr(app.state, "backend_ready", False)),
            "runtime_ready": False,
            "queue_backlog_healthy": True,
            "status": "degraded" if getattr(app.state, "backend_ready", False) else "starting",
            "runtime_status": "offline",
            "process_role": getattr(app.state, "process_role", "ipc_worker"),
        }

    monkeypatch.setattr("magi.transport.http_app.get_runtime_system_status", _fake_runtime_status)

    app = create_transport_app()
    app.state.process_role = "ipc_worker"
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "ready": False,
        "status": "starting",
        "api_ready": False,
        "runtime_ready": False,
        "runtime_status": "offline",
        "process_role": "ipc_worker",
    }

    app.state.backend_ready = True

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "ready": False,
        "status": "degraded",
        "api_ready": True,
        "runtime_ready": False,
        "runtime_status": "offline",
        "process_role": "ipc_worker",
    }


def test_transport_app_exposes_runtime_health_details(monkeypatch) -> None:
    from magi.transport.http_app import create_transport_app

    async def _fake_runtime_status(app):
        return {
            "api_ready": True,
            "runtime_ready": True,
            "queue_backlog_healthy": True,
            "status": "ready",
            "runtime_status": "ready",
            "process_role": getattr(app.state, "process_role", "ipc_worker"),
            "runtime_heartbeat_age_ms": 1200,
            "pending_commands": 4,
        }

    monkeypatch.setattr("magi.transport.http_app.get_runtime_system_status", _fake_runtime_status)

    app = create_transport_app()
    app.state.backend_ready = True
    app.state.process_role = "ipc_worker"
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ready",
        "version": "1.0.0",
        "api_ready": True,
        "runtime_ready": True,
        "runtime_status": "ready",
        "queue_backlog_healthy": True,
        "runtime_heartbeat_age_ms": 1200,
        "pending_commands": 4,
        "process_role": "ipc_worker",
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
