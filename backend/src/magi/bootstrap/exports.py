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
                "runtime_memory",
                "runtime_message_bus",
                "runtime_scheduler",
                "runtime_llm",
            ),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        agent_runtime = require_initialized(self._context.agent_runtime.agent_runtime, "agent runtime")
        memory_integration = require_initialized(self._context.memory.memory_integration, "memory integration")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        other_memory = require_initialized(self._context.personality.other_memory, "other memory")

        container = get_container()
        container.message_bus.override(providers.Object(message_bus))
        container.agent_runtime.override(providers.Object(agent_runtime))
        container.memory_integration.override(providers.Object(memory_integration))
        container.unified_memory.override(providers.Object(unified_memory))
        container.other_memory.override(providers.Object(other_memory))

        if self._context.scheduler.scheduler_service is not None:
            container.scheduler_service.override(providers.Object(self._context.scheduler.scheduler_service))
        if self._context.llm.scenario_llm_pool is not None:
            container.scenario_llm_pool.override(providers.Object(self._context.llm.scenario_llm_pool))

        skill_indexer = self._context.skills.skill_indexer
        if skill_indexer is not None:
            container.skill_indexer.override(providers.Object(skill_indexer))

        skill_loader = self._context.skills.skill_loader
        if skill_loader is not None:
            container.skill_loader.override(providers.Object(skill_loader))

        skill_executor = self._context.skills.skill_executor
        if skill_executor is not None:
            container.skill_executor.override(providers.Object(skill_executor))

        logger.info("DI container providers registered")

    async def shutdown(self) -> None:
        container = get_container()
        container.message_bus.reset_override()
        container.agent_runtime.reset_override()
        container.memory_integration.reset_override()
        container.unified_memory.reset_override()
        container.scheduler_service.reset_override()
        container.scenario_llm_pool.reset_override()
        container.other_memory.reset_override()
        container.skill_indexer.reset_override()
        container.skill_loader.reset_override()
        container.skill_executor.reset_override()
