from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.api.services import runtime_status_service as service


def _ready_binding(name):
    if name == "runtime_orchestrator":
        return SimpleNamespace(snapshot=lambda: {
            key: {"state": "ready"} for key in (
                "runtime_llm", "runtime_memory", "runtime_exports", "runtime_command_processor",
            )
        })
    if name == "runtime_bootstrap_context":
        return SimpleNamespace(
            runtime_commands=SimpleNamespace(full_clear_recovery_pending=False),
            llm=SimpleNamespace(llm_adapter=object()),
        )
    return object()


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
    monkeypatch.setattr(service, "_resolve_binding", _ready_binding)

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
    monkeypatch.setattr(service, "_resolve_binding", _ready_binding)

    status = await service.get_runtime_system_status(app)

    assert status["worker_ready"] is True
    assert status["runtime_ready"] is True
    assert status["runtime_status"] == "ready"


@pytest.mark.parametrize("unavailable", ["adapter", "runtime_command_processor", "runtime_optional"])
async def test_readiness_distinguishes_execution_failure_from_optional_failure(monkeypatch, unavailable):
    def resolve(name):
        value = _ready_binding(name)
        if name == "runtime_bootstrap_context" and unavailable == "adapter":
            value.llm.llm_adapter = None
        if name == "runtime_orchestrator" and unavailable != "adapter":
            states = value.snapshot()
            states[unavailable] = {"state": "failed"}
            value.snapshot = lambda: states
        return value

    monkeypatch.setattr(service, "_resolve_binding", resolve)
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: _snapshot(startup_state="failed"))
    monkeypatch.setattr(service, "require_runtime_command_queue", lambda: _FakeRuntimeCommandQueue())
    status = await service.get_runtime_system_status(SimpleNamespace(state=SimpleNamespace(backend_ready=True)))
    assert status["service_ready"] and status["storage_ready"]
    assert status["runtime_ready"] is (unavailable == "runtime_optional")
    assert status["status"] == "degraded"
