from __future__ import annotations

from types import SimpleNamespace

from magi.api.services import runtime_status_service as service
from magi.runtime_trace import RuntimeHeartbeatRecord


class _FakeRuntimeTraceStore:
    def __init__(self, heartbeat: RuntimeHeartbeatRecord | None) -> None:
        self._heartbeat = heartbeat

    async def get_runtime_heartbeat(self, *, role: str) -> RuntimeHeartbeatRecord | None:
        assert role == "ipc_worker"
        return self._heartbeat


class _FakeRuntimeCommandQueue:
    def __init__(self, pending_count: int = 0) -> None:
        self.pending_count = pending_count

    async def get_stats(self) -> dict[str, int]:
        return {"pending_count": self.pending_count}


def _snapshot(*, startup_state: str, reason: str | None = None, detail: str | None = None):
    return SimpleNamespace(startup_state=startup_state, reason=reason, detail=detail)


async def test_get_runtime_system_status_reports_deferred_when_runtime_heartbeat_missing(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    monkeypatch.setattr(service, "resolve_runtime_trace_store", lambda: _FakeRuntimeTraceStore(None))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(2))
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: _snapshot(startup_state="deferred", reason="llm_selection_pending"))
    monkeypatch.setattr(service, "_resolve_binding", lambda _name: None)

    status = await service.get_runtime_system_status(app)

    assert status["api_ready"] is True
    assert status["worker_ready"] is False
    assert status["llm_ready"] is False
    assert status["agent_runtime_ready"] is False
    assert status["runtime_ready"] is False
    assert status["status"] == "degraded"
    assert status["runtime_status"] == "offline"
    assert status["startup_state"] == "deferred"
    assert status["deferred_reason"] == "llm_selection_pending"


async def test_get_runtime_system_status_reports_ready_when_runtime_and_bindings_exist(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))
    heartbeat = RuntimeHeartbeatRecord(
        role="ipc_worker",
        instance_id="runtime-1",
        pid=4321,
        started_at_ms=1_711_260_000_000,
        last_seen_at_ms=int(service.time.time() * 1000),
        status="ready",
        queue_backlog=0,
        active_turns=0,
        active_workers=0,
        last_error=None,
    )

    monkeypatch.setattr(service, "resolve_runtime_trace_store", lambda: _FakeRuntimeTraceStore(heartbeat))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(0))
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: _snapshot(startup_state="ready"))
    monkeypatch.setattr(service, "_resolve_binding", lambda _name: object())

    status = await service.get_runtime_system_status(app)

    assert status["api_ready"] is True
    assert status["worker_ready"] is True
    assert status["infrastructure_ready"] is True
    assert status["llm_ready"] is True
    assert status["agent_runtime_ready"] is True
    assert status["runtime_ready"] is True
    assert status["status"] == "ready"
    assert status["runtime_status"] == "ready"
    assert status["startup_state"] == "ready"
    assert status["deferred_reason"] is None


async def test_get_runtime_system_status_uses_deferred_heartbeat_reason_when_snapshot_has_none(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))
    heartbeat = RuntimeHeartbeatRecord(
        role="ipc_worker",
        instance_id="runtime-1",
        pid=4321,
        started_at_ms=1_711_260_000_000,
        last_seen_at_ms=int(service.time.time() * 1000),
        status="deferred",
        queue_backlog=0,
        active_turns=0,
        active_workers=0,
        last_error="llm_configuration_invalid",
    )

    def _resolve_binding(name: str):
        if name in {"runtime_command_queue", "chat_store", "message_bus", "runtime_trace_store"}:
            return object()
        return None

    monkeypatch.setattr(service, "resolve_runtime_trace_store", lambda: _FakeRuntimeTraceStore(heartbeat))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(0))
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: _snapshot(startup_state="offline"))
    monkeypatch.setattr(service, "_resolve_binding", _resolve_binding)

    status = await service.get_runtime_system_status(app)

    assert status["worker_ready"] is True
    assert status["runtime_ready"] is False
    assert status["runtime_status"] == "deferred"
    assert status["startup_state"] == "deferred"
    assert status["deferred_reason"] == "llm_configuration_invalid"


async def test_get_runtime_system_status_can_trust_local_worker_without_heartbeat_store(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    def fail_if_heartbeat_store_is_read():
        raise AssertionError("local worker readiness must not read the persisted heartbeat")

    monkeypatch.setattr(service, "resolve_runtime_trace_store", fail_if_heartbeat_store_is_read)
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(0))
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: _snapshot(startup_state="ready"))
    monkeypatch.setattr(service, "_resolve_binding", lambda _name: object())

    status = await service.get_runtime_system_status(app, trust_local_worker=True)

    assert status["worker_ready"] is True
    assert status["runtime_ready"] is True
    assert status["runtime_status"] == "ready"
    assert status["runtime_heartbeat_age_ms"] is None
