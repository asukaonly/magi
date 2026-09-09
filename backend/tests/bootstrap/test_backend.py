from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from dependency_injector import providers

from magi.bootstrap import backend as backend_module
from magi.bootstrap.lifecycle import LifecycleModule
from magi.core.container import get_container
from magi.llm.lifecycle import RuntimeInitializationDeferred


@pytest.mark.asyncio
async def test_base_runtime_is_available_before_optional_start_and_survives_retry(monkeypatch):
    container = get_container()
    for name in ("runtime_orchestrator", "runtime_bootstrap_context", "agent_runtime"):
        getattr(container, name).reset_override()
    configured = False
    calls = []
    config = SimpleNamespace()
    monkeypatch.setattr(backend_module, "get_config", lambda: config)
    monkeypatch.setattr("magi.bootstrap.maintenance_worker.is_restore_worker", lambda: True)

    def build(context):
        async def base():
            calls.append("base")
            context.chat.store = object()
        async def llm():
            calls.append("llm")
            if not configured:
                raise RuntimeInitializationDeferred(pending_selection=True)
        async def agent():
            calls.append("agent")
            container.agent_runtime.override(providers.Object(object()))
        async def stop_agent():
            container.agent_runtime.reset_override()
        return [
            LifecycleModule("runtime_base_exports", init=base),
            LifecycleModule("runtime_llm", dependencies=("runtime_base_exports",), init=llm),
            LifecycleModule("runtime_agent_core", dependencies=("runtime_llm",), init=agent, shutdown=stop_agent),
        ]
    monkeypatch.setattr(backend_module, "build_runtime_modules", build)
    try:
        await backend_module.initialize_base_runtime()
        owner = container.runtime_orchestrator()
        store = container.runtime_bootstrap_context().chat.store
        assert calls == ["base"]
        await backend_module.initialize_agent_runtime()
        assert calls == ["base", "llm"]
        configured = True
        await backend_module.initialize_agent_runtime()
        assert calls == ["base", "llm", "llm", "agent"]
        assert container.runtime_orchestrator() is owner
        assert container.runtime_bootstrap_context().chat.store is store
    finally:
        await backend_module.shutdown_agent_runtime()


@pytest.mark.asyncio
async def test_shutdown_agent_runtime_strict_mode_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingOrchestrator:
        async def shutdown(self, *, strict: bool = False) -> None:
            assert strict is True
            raise OSError("close failed")

    container = get_container()
    container.runtime_orchestrator.override(providers.Object(_FailingOrchestrator()))
    container.runtime_bootstrap_context.override(providers.Object(object()))

    try:
        with pytest.raises(RuntimeError, match="could not be stopped safely"):
            await backend_module.shutdown_agent_runtime(strict=True)

        assert container.runtime_orchestrator.overridden
        assert container.runtime_bootstrap_context.overridden
    finally:
        container.runtime_orchestrator.reset_override()
        container.runtime_bootstrap_context.reset_override()


@pytest.mark.asyncio
async def test_shutdown_agent_runtime_default_mode_keeps_best_effort_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingOrchestrator:
        async def shutdown(self, *, strict: bool = False) -> None:
            assert strict is False
            raise OSError("close failed")

    monkeypatch.setattr(
        backend_module,
        "_resolve_from_container",
        lambda name: _FailingOrchestrator() if name == "runtime_orchestrator" else None,
    )

    await backend_module.shutdown_agent_runtime()
@pytest.mark.asyncio
async def test_lifecycle_serializes_background_initialization_and_shutdown(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []
    ready = False

    async def initialize():
        nonlocal ready
        if ready:
            return
        calls.append("start")
        entered.set()
        await release.wait()
        ready = True

    async def shutdown(*, strict=False):
        calls.append("stop")

    monkeypatch.setattr(backend_module, "_runtime_lifecycle_lock", asyncio.Lock())
    monkeypatch.setattr(backend_module, "_initialize_agent_runtime", initialize)
    monkeypatch.setattr(backend_module, "_shutdown_agent_runtime", shutdown)
    first = asyncio.create_task(backend_module.initialize_agent_runtime())
    await entered.wait()
    second = asyncio.create_task(backend_module.initialize_agent_runtime())
    stop = asyncio.create_task(backend_module.shutdown_agent_runtime())
    await asyncio.sleep(0)
    assert calls == ["start"]
    assert not second.done()
    assert not stop.done()
    release.set()
    await asyncio.gather(first, second, stop)
    assert calls == ["start", "stop"]


@pytest.mark.asyncio
async def test_shutdown_fences_queued_initialization(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []
    async def initialize():
        calls.append("start")
        entered.set()
        await release.wait()
    async def stop(*, strict=False):
        calls.append("stop")
    monkeypatch.setattr(backend_module, "_runtime_lifecycle_lock", asyncio.Lock())
    monkeypatch.setattr(backend_module, "_initialize_agent_runtime", initialize)
    monkeypatch.setattr(backend_module, "_shutdown_agent_runtime", stop)
    first = asyncio.create_task(backend_module.initialize_agent_runtime())
    await entered.wait()
    second = asyncio.create_task(backend_module.initialize_agent_runtime())
    await asyncio.sleep(0)
    stopping = asyncio.create_task(backend_module.shutdown_agent_runtime())
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second, stopping)
    assert calls == ["start", "stop"]
