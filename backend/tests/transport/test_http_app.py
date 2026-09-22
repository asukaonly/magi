from __future__ import annotations

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
            "service_ready": True,
            "storage_ready": True,
            "capabilities": {},
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
        "service_ready": True,
        "storage_ready": True,
        "capabilities": {},
        "status": "degraded",
        "runtime_ready": False,
        "worker_ready": True,
        "infrastructure_ready": True,
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
            "service_ready": True,
            "storage_ready": True,
            "capabilities": {},
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
        "version": app.version,
        "api_ready": True,
        "service_ready": True,
        "storage_ready": True,
        "capabilities": {},
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


def test_python_openapi_stays_internal_and_uses_distribution_version(monkeypatch) -> None:
    from magi.transport.http_app import create_transport_app

    monkeypatch.setattr("magi.transport.http_app.version", lambda _: "2.3.4")
    schema = create_transport_app().openapi()
    assert schema["info"]["version"] == "2.3.4"
    assert "JWT" not in schema["info"]["description"]
    assert "disabled in development" not in schema["info"]["description"]
    assert "/api/auth/pair" not in schema["paths"]
    assert "/api/metrics/runtime/overview" not in schema["paths"]
    assert "/api/config/" in schema["paths"]

    for path, method in [("/api/plugins/requests/{operation_id}", "get"), ("/api/plugins/requests/{operation_id}/resolve", "post")]:
        parameters = schema["paths"][path][method]["parameters"]
        assert any(parameter["name"] == "X-Magi-Data-Epoch" and parameter["required"] for parameter in parameters)
