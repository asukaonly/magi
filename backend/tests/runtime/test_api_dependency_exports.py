"""Product API dependencies follow their lifecycle owners across recovery."""
from types import SimpleNamespace

import pytest
from dependency_injector import providers

from magi.api.runtime_dependencies import get_api_runtime_dependencies
from magi.bootstrap.api_dependencies import build_api_runtime_dependencies
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.core.container import Container


def test_dependencies_follow_live_owners_and_retire_after_shutdown(monkeypatch):
    container = Container()
    monkeypatch.setattr("magi.core.container.get_container", lambda: container)
    try:
        assert get_api_runtime_dependencies().channels_module is None
        context = RuntimeBootstrapContext()
        container.api_runtime_dependencies.override(providers.Factory(build_api_runtime_dependencies, context))
        first = get_api_runtime_dependencies()
        assert first.channels_module is None
        owner = SimpleNamespace(session_mapper=object())
        context.channels.module = owner
        context.llm.llm_adapter = object()
        context.runtime_commands.full_clear_recovery_pending = True
        second = get_api_runtime_dependencies()
        assert second.channels_module is owner
        assert second.llm_adapter_ready and second.full_clear_recovery_pending
        context.channels.module = None
        assert get_api_runtime_dependencies().channels_module is None
        container.api_runtime_dependencies.reset_override()
        assert get_api_runtime_dependencies().llm_adapter_ready is False
    finally:
        container.unwire()


@pytest.mark.asyncio
async def test_readiness_stays_blocked_during_clear_recovery(monkeypatch):
    from magi.api.runtime_dependencies import ApiRuntimeDependencies
    from magi.api.services import runtime_status_service as service

    states = {name: {"state": "ready"} for name in (
        "runtime_llm", "runtime_memory", "runtime_exports", "runtime_command_processor",
    )}
    monkeypatch.setattr(service, "_resolve_binding", lambda name: SimpleNamespace(snapshot=lambda: states) if name == "runtime_orchestrator" else object())
    monkeypatch.setattr(service, "get_api_runtime_dependencies", lambda: ApiRuntimeDependencies(llm_adapter_ready=True, full_clear_recovery_pending=True))
    monkeypatch.setattr(service, "get_runtime_startup_snapshot", lambda: SimpleNamespace(startup_state="ready", reason=None, detail=None))
    result = await service.get_runtime_system_status(SimpleNamespace())
    assert result["infrastructure_ready"]
    assert not result["llm_ready"]
    assert not result["runtime_ready"]
