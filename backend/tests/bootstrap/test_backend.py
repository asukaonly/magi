from __future__ import annotations

import pytest
from dependency_injector import providers

from magi.bootstrap import backend as backend_module
from magi.core.container import get_container
from magi.llm.lifecycle import RuntimeInitializationDeferred
from magi.skills.service_access import SkillsRuntimeBindings


class _DeferredOrchestrator:
    async def startup(self) -> None:
        raise RuntimeInitializationDeferred(pending_selection=True)


@pytest.mark.asyncio
async def test_initialize_agent_runtime_binds_skills_when_runtime_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = get_container()
    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_runner.reset_override()

    fake_config = type("Config", (), {"features": type("Features", (), {"enable_skills": True})()})()
    bindings = SkillsRuntimeBindings(
        skill_indexer=object(),
        skill_loader=object(),
        skill_runner=object(),
    )

    monkeypatch.setattr(backend_module, "_is_runtime_initialized", lambda: False)
    monkeypatch.setattr(backend_module, "get_config", lambda: fake_config)
    monkeypatch.setattr(backend_module, "build_runtime_modules", lambda context, role=None: [])
    monkeypatch.setattr(backend_module, "ModuleLifecycleOrchestrator", lambda modules: _DeferredOrchestrator())
    monkeypatch.setattr(
        "magi.skills.service_access.build_skills_runtime",
        lambda llm_adapter=None, *, tool_registry, orchestrator_factory=None, engine_run_input_factory=None: bindings,
    )

    await backend_module.initialize_agent_runtime()

    assert container.skill_indexer() is bindings.skill_indexer
    assert container.skill_loader() is bindings.skill_loader
    assert container.skill_runner() is bindings.skill_runner
    assert container.skill_indexer.overridden
    assert container.skill_loader.overridden
    assert container.skill_runner.overridden

    container.skill_indexer.reset_override()
    container.skill_loader.reset_override()
    container.skill_runner.reset_override()


class _DeferredOrchestratorWithContext:
    """Orchestrator that defers but lets context fields be populated first."""

    def __init__(self, context):
        self._context = context

    async def startup(self) -> None:
        # Simulate modules 1-6 running before LLM defers
        self._context.chat.store = object()
        self._context.message_bus.message_bus = object()
        self._context.runtime_commands.runtime_command_queue = object()
        raise RuntimeInitializationDeferred(pending_selection=True)


@pytest.mark.asyncio
async def test_initialize_agent_runtime_exports_infra_bindings_when_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Infrastructure bindings (chat_store, message_bus, etc.) should be
    exported to the DI container even when full runtime init is deferred."""
    container = get_container()
    container.chat_store.reset_override()
    container.message_bus.reset_override()
    container.runtime_command_queue.reset_override()

    fake_config = type("Config", (), {"features": type("Features", (), {"enable_skills": False})()})()

    captured_context = {}

    def fake_orchestrator_factory(modules):
        ctx = captured_context.get("ctx")
        return _DeferredOrchestratorWithContext(ctx)

    def fake_build(context, role=None):
        captured_context["ctx"] = context
        return []

    monkeypatch.setattr(backend_module, "_is_runtime_initialized", lambda: False)
    monkeypatch.setattr(backend_module, "get_config", lambda: fake_config)
    monkeypatch.setattr(backend_module, "build_runtime_modules", fake_build)
    monkeypatch.setattr(backend_module, "ModuleLifecycleOrchestrator", fake_orchestrator_factory)

    await backend_module.initialize_agent_runtime()

    assert container.chat_store.overridden
    assert container.message_bus.overridden
    assert container.runtime_command_queue.overridden
    assert not container.agent_runtime.overridden

    container.chat_store.reset_override()
    container.message_bus.reset_override()
    container.runtime_command_queue.reset_override()


@pytest.mark.asyncio
async def test_initialize_agent_runtime_restarts_previously_deferred_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _SuccessfulOrchestrator:
        async def startup(self) -> None:
            calls.append("startup")

    async def _fake_shutdown() -> None:
        calls.append("shutdown")

    def _fake_resolve(attr: str):
        if attr == "runtime_orchestrator":
            return object()
        return None

    monkeypatch.setattr(backend_module, "_resolve_from_container", _fake_resolve)
    monkeypatch.setattr(backend_module, "build_runtime_modules", lambda context, role=None: [])
    monkeypatch.setattr(backend_module, "ModuleLifecycleOrchestrator", lambda modules: _SuccessfulOrchestrator())
    monkeypatch.setattr(backend_module, "shutdown_agent_runtime", _fake_shutdown)

    await backend_module.initialize_agent_runtime()

    assert calls == ["shutdown", "startup"]


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
