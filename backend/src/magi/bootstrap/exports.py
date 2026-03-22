"""Bootstrap exports module for exposing runtime objects to DI container."""

from __future__ import annotations

from dependency_injector import providers

from .lifecycle import LifecycleModule
from .context import RuntimeBootstrapContext, require_initialized
from ..core.container import get_container
from ..core.logger import get_logger

logger = get_logger(__name__)


class RuntimeExportsModule(LifecycleModule):
    """Expose initialized runtime objects to DI and API bindings."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_exports",
            dependencies=(
                "runtime_agent_core",
                "runtime_command_queue",
                "runtime_chat_store",
                "runtime_memory",
                "runtime_message_bus",
                "runtime_plugin_system",
                "runtime_scheduler",
                "runtime_llm",
                "runtime_trace",
            ),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        chat_store = require_initialized(self._context.chat.store, "chat store")
        agent_runtime = require_initialized(self._context.agent_runtime.agent_runtime, "agent runtime")
        memory_integration = require_initialized(self._context.memory.memory_integration, "memory integration")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        hybrid_retrieval_service = require_initialized(
            self._context.memory.hybrid_retrieval_service,
            "hybrid retrieval service",
        )
        other_memory = require_initialized(self._context.personality.other_memory, "other memory")
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        sensor_registry = require_initialized(self._context.plugins.sensor_registry, "sensor registry")
        action_registry = require_initialized(self._context.plugins.action_registry, "action registry")
        runtime_trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        container = get_container()
        container.message_bus.override(providers.Object(message_bus))
        container.runtime_command_queue.override(providers.Object(runtime_command_queue))
        container.chat_store.override(providers.Object(chat_store))
        container.agent_runtime.override(providers.Object(agent_runtime))
        container.memory_integration.override(providers.Object(memory_integration))
        container.unified_memory.override(providers.Object(unified_memory))
        container.hybrid_retrieval_service.override(providers.Object(hybrid_retrieval_service))
        container.other_memory.override(providers.Object(other_memory))
        container.plugin_manager.override(providers.Object(plugin_manager))
        container.sensor_registry.override(providers.Object(sensor_registry))
        container.action_registry.override(providers.Object(action_registry))
        container.runtime_trace_store.override(providers.Object(runtime_trace_store))

        if self._context.scheduler.scheduler_service is not None:
            container.scheduler_service.override(providers.Object(self._context.scheduler.scheduler_service))
        if self._context.timeline.timeline_scheduler_contrib is not None:
            container.timeline_scheduler_contrib.override(
                providers.Object(self._context.timeline.timeline_scheduler_contrib)
            )
        if self._context.llm.scenario_llm_pool is not None:
            container.scenario_llm_pool.override(providers.Object(self._context.llm.scenario_llm_pool))

        skill_indexer = self._context.skills.skill_indexer
        if skill_indexer is not None:
            container.skill_indexer.override(providers.Object(skill_indexer))

        skill_loader = self._context.skills.skill_loader
        if skill_loader is not None:
            container.skill_loader.override(providers.Object(skill_loader))

        skill_runner = self._context.skills.skill_runner
        if skill_runner is not None:
            container.skill_runner.override(providers.Object(skill_runner))

        logger.info("DI container providers registered")

    async def shutdown(self) -> None:
        container = get_container()
        container.message_bus.reset_override()
        container.runtime_command_queue.reset_override()
        container.chat_store.reset_override()
        container.agent_runtime.reset_override()
        container.memory_integration.reset_override()
        container.unified_memory.reset_override()
        container.hybrid_retrieval_service.reset_override()
        container.scheduler_service.reset_override()
        container.timeline_scheduler_contrib.reset_override()
        container.scenario_llm_pool.reset_override()
        container.other_memory.reset_override()
        container.plugin_manager.reset_override()
        container.sensor_registry.reset_override()
        container.action_registry.reset_override()
        container.runtime_trace_store.reset_override()
        container.skill_indexer.reset_override()
        container.skill_loader.reset_override()
        container.skill_runner.reset_override()
