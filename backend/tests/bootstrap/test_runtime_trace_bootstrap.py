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
    context.chat.store = object()
    context.chat.projector = object()
    context.agent_runtime.agent_runtime = object()
    context.memory.memory_integration = object()
    context.memory.unified_memory = object()
    context.memory.hybrid_retrieval_service = object()
    context.plugins.plugin_manager = object()
    context.plugins.plugin_projection_service = object()
    context.plugins.source_registry = object()
    context.runtime_trace.store = object()

    container = get_container()
    container.runtime_trace_store.reset_override()
    container.hybrid_retrieval_service.reset_override()
    from magi.bootstrap.tool_capabilities import (
        build_tool_capabilities as build_host_tool_capabilities,
        reset_tool_capabilities,
    )
    from magi.tools.capabilities import (
        build_tool_capabilities,
        reset_tool_capabilities_provider,
    )

    reset_tool_capabilities()
    reset_tool_capabilities_provider()

    module = RuntimeExportsModule(context)
    await module.init()

    try:
        assert container.runtime_trace_store() is context.runtime_trace.store
        assert container.runtime_trace_store.overridden
        assert container.hybrid_retrieval_service() is context.memory.hybrid_retrieval_service
        assert container.hybrid_retrieval_service.overridden
        assert build_tool_capabilities() is build_host_tool_capabilities()
    finally:
        # init() overrides MANY container bindings (unified_memory, chat
        # store, plugin manager, ...) — resetting only two of them leaked
        # overrides into later test files. shutdown() resets them all.
        await module.shutdown()
        reset_tool_capabilities_provider()
        reset_tool_capabilities()
