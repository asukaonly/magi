from __future__ import annotations

from types import SimpleNamespace

from magi.api.services import runtime_status_service as service


class _FakeRuntimeCommandQueue:
    def __init__(self, pending_count: int = 0) -> None:
        self.pending_count = pending_count

    async def get_stats(self) -> dict[str, int]:
        return {"pending_count": self.pending_count}


def _snapshot(*, startup_state: str, reason: str | None = None, detail: str | None = None):
    return SimpleNamespace(startup_state=startup_state, reason=reason, detail=detail)


async def test_get_runtime_system_status_reports_deferred_from_startup_snapshot(
    monkeypatch,
) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    monkeypatch.setattr(
        service,
        "require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(2),
    )
    monkeypatch.setattr(
        service,
        "get_runtime_startup_snapshot",
        lambda: _snapshot(
            startup_state="deferred",
            reason="llm_selection_pending",
        ),
    )
    monkeypatch.setattr(service, "_resolve_binding", lambda _name: None)

    status = await service.get_runtime_system_status(app)

    assert status["api_ready"] is True
    assert status["worker_ready"] is True
    assert status["llm_ready"] is False
    assert status["agent_runtime_ready"] is False
    assert status["runtime_ready"] is False
    assert status["status"] == "degraded"
    assert status["runtime_status"] == "deferred"
    assert status["startup_state"] == "deferred"
    assert status["deferred_reason"] == "llm_selection_pending"


async def test_get_runtime_system_status_reports_ready_when_runtime_and_bindings_exist(
    monkeypatch,
) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    monkeypatch.setattr(
        service,
        "require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(0),
    )
    monkeypatch.setattr(
        service,
        "get_runtime_startup_snapshot",
        lambda: _snapshot(startup_state="ready"),
    )
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


async def test_get_runtime_system_status_uses_snapshot_deferred_reason(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    def _resolve_binding(name: str):
        if name in {"runtime_command_queue", "chat_store", "message_bus", "runtime_trace_store"}:
            return object()
        return None

    monkeypatch.setattr(
        service,
        "require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(0),
    )
    monkeypatch.setattr(
        service,
        "get_runtime_startup_snapshot",
        lambda: _snapshot(
            startup_state="deferred",
            reason="llm_configuration_invalid",
        ),
    )
    monkeypatch.setattr(service, "_resolve_binding", _resolve_binding)

    status = await service.get_runtime_system_status(app)

    assert status["worker_ready"] is True
    assert status["runtime_ready"] is False
    assert status["runtime_status"] == "deferred"
    assert status["startup_state"] == "deferred"
    assert status["deferred_reason"] == "llm_configuration_invalid"


async def test_get_runtime_system_status_never_reads_runtime_heartbeat_store(monkeypatch) -> None:
    app = SimpleNamespace(state=SimpleNamespace(backend_ready=True, process_role="ipc_worker"))

    def fail_if_heartbeat_store_is_read():
        raise AssertionError("runtime readiness must not read the persisted heartbeat")

    monkeypatch.setattr(
        service,
        "resolve_runtime_trace_store",
        fail_if_heartbeat_store_is_read,
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "require_runtime_command_queue",
        lambda: _FakeRuntimeCommandQueue(0),
    )
    monkeypatch.setattr(
        service,
        "get_runtime_startup_snapshot",
        lambda: _snapshot(startup_state="ready"),
    )
    monkeypatch.setattr(service, "_resolve_binding", lambda _name: object())

    status = await service.get_runtime_system_status(app)

    assert status["worker_ready"] is True
    assert status["runtime_ready"] is True
    assert status["runtime_status"] == "ready"
