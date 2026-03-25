"""Bootstrap builder for API-safe runtime modules."""

from __future__ import annotations

from dependency_injector import providers

from .context import RuntimeBootstrapContext, require_initialized
from .exports import RuntimeExportsModule
from .lifecycle import LifecycleModule

from ..chat.lifecycle import ChatProjectorModule, ChatStoreModule
from ..config.lifecycle import ConfigurationModule
from ..core.container import get_container
from ..core.lifecycle import CoreDependenciesModule
from ..events.lifecycle import MessageBusModule, RuntimeCommandQueueModule
from ..llm.lifecycle import LLMRuntimeModule
from ..memory.lifecycle import MemoryStoreModule
from ..plugins.lifecycle import PluginSystemModule
from ..runtime_trace import RuntimeTraceStore
from ..skills.lifecycle import SkillsModule


def _build_runtime_trace_module(context: RuntimeBootstrapContext) -> LifecycleModule:
    async def _init_runtime_trace() -> None:
        runtime_paths = context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        store = RuntimeTraceStore(db_path=str(runtime_paths.runtime_trace_db_path))
        await store.initialize()
        context.runtime_trace.store = store

    async def _shutdown_runtime_trace() -> None:
        if context.runtime_trace.store is not None:
            await context.runtime_trace.store.shutdown()
            context.runtime_trace.store = None

    return LifecycleModule(
        name="runtime_trace",
        dependencies=("runtime_core_dependencies",),
        init=_init_runtime_trace,
        shutdown=_shutdown_runtime_trace,
    )


class APIRuntimeExportsModule(RuntimeExportsModule):
    """Expose API-safe runtime objects without background runtime bindings."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(context)
        self.name = "runtime_api_exports"
        self.dependencies = (
            "runtime_command_queue",
            "runtime_chat_store",
            "runtime_chat_projector",
            "runtime_memory",
            "runtime_plugin_system",
            "runtime_llm",
            "runtime_skills",
            "runtime_trace",
        )

    async def init(self) -> None:
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        chat_store = require_initialized(self._context.chat.store, "chat store")
        chat_projector = require_initialized(self._context.chat.projector, "chat projector")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        hybrid_retrieval_service = require_initialized(
            self._context.memory.hybrid_retrieval_service,
            "hybrid retrieval service",
        )
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        sensor_registry = require_initialized(self._context.plugins.sensor_registry, "sensor registry")
        runtime_trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        container = get_container()
        container.runtime_command_queue.override(providers.Object(runtime_command_queue))
        container.chat_store.override(providers.Object(chat_store))
        container.chat_projector.override(providers.Object(chat_projector))
        container.unified_memory.override(providers.Object(unified_memory))
        container.hybrid_retrieval_service.override(providers.Object(hybrid_retrieval_service))
        container.plugin_manager.override(providers.Object(plugin_manager))
        container.sensor_registry.override(providers.Object(sensor_registry))
        container.runtime_trace_store.override(providers.Object(runtime_trace_store))

        if self._context.llm.scenario_llm_pool is not None:
            container.scenario_llm_pool.override(providers.Object(self._context.llm.scenario_llm_pool))

        skill_indexer = self._context.skills.skill_indexer
        if skill_indexer is not None:
            container.skill_indexer.override(providers.Object(skill_indexer))

    async def shutdown(self) -> None:
        container = get_container()
        container.runtime_command_queue.reset_override()
        container.chat_store.reset_override()
        container.chat_projector.reset_override()
        container.unified_memory.reset_override()
        container.hybrid_retrieval_service.reset_override()
        container.plugin_manager.reset_override()
        container.sensor_registry.reset_override()
        container.runtime_trace_store.reset_override()
        container.scenario_llm_pool.reset_override()
        container.skill_indexer.reset_override()


def build_api_runtime_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build lifecycle modules required by the API/read-side process."""
    return [
        CoreDependenciesModule(context),
        ConfigurationModule(context),
        RuntimeCommandQueueModule(context),
        MessageBusModule(context),
        ChatStoreModule(context),
        PluginSystemModule(context),
        LLMRuntimeModule(context),
        MemoryStoreModule(context, start_memory_integration=False),
        ChatProjectorModule(context),
        _build_runtime_trace_module(context),
        SkillsModule(context),
        APIRuntimeExportsModule(context),
    ]


__all__ = [
    "APIRuntimeExportsModule",
    "build_api_runtime_modules",
]
