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


async def test_get_runtime_system_status_reports_degraded_when_runtime_heartbeat_missing(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    monkeypatch.setattr(service, "require_runtime_trace_store", lambda: _FakeRuntimeTraceStore(None))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(2))

    status = await service.get_runtime_system_status(app)

    assert status["api_ready"] is True
    assert status["runtime_ready"] is False
    assert status["status"] == "degraded"
    assert status["runtime_status"] == "offline"


async def test_get_runtime_system_status_reports_ready_for_api_role(monkeypatch) -> None:
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

    monkeypatch.setattr(service, "require_runtime_trace_store", lambda: _FakeRuntimeTraceStore(heartbeat))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue(0))

    status = await service.get_runtime_system_status(app)

    assert status["api_ready"] is True
    assert status["runtime_ready"] is True
    assert status["status"] == "ready"
    assert status["runtime_status"] == "ready"
