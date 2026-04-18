from __future__ import annotations

import pytest

from magi.bootstrap.builder import build_runtime_modules
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.exports import RuntimeExportsModule
from magi.core.container import get_container


def test_build_runtime_modules_includes_runtime_trace_module() -> None:
    context = RuntimeBootstrapContext()

    modules = build_runtime_modules(context)
    module_names = [module.name for module in modules]

    assert "runtime_trace" in module_names
    assert module_names.index("runtime_trace") < module_names.index("runtime_exports")


@pytest.mark.asyncio
async def test_runtime_exports_register_runtime_trace_store() -> None:
    context = RuntimeBootstrapContext()
    context.runtime_commands.runtime_command_queue = object()
    context.message_bus.message_bus = object()
    context.agent_runtime.agent_runtime = object()
    context.memory.memory_integration = object()
    context.memory.unified_memory = object()
    context.memory.hybrid_retrieval_service = object()
    context.plugins.plugin_manager = object()
    context.plugins.sensor_registry = object()
    context.plugins.action_registry = object()
    context.runtime_trace.store = object()

    container = get_container()
    container.runtime_trace_store.reset_override()
    container.hybrid_retrieval_service.reset_override()

    module = RuntimeExportsModule(context)
    await module.init()

    try:
        assert container.runtime_trace_store() is context.runtime_trace.store
        assert container.runtime_trace_store.overridden
        assert container.hybrid_retrieval_service() is context.memory.hybrid_retrieval_service
        assert container.hybrid_retrieval_service.overridden
    finally:
        container.runtime_trace_store.reset_override()
        container.hybrid_retrieval_service.reset_override()
