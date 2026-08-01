"""Bootstrap exports module for exposing runtime objects to DI container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dependency_injector import providers

from .lifecycle import LifecycleModule
from .context import RuntimeBootstrapContext, require_initialized
from ..core.container import get_container
from ..core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _RequiredRuntimeExports:
    message_bus: Any
    runtime_command_queue: Any
    chat_store: Any
    chat_projector: Any
    agent_runtime: Any
    memory_integration: Any
    unified_memory: Any
    hybrid_retrieval_service: Any
    plugin_manager: Any
    plugin_projection_service: Any
    sensor_registry: Any
    runtime_trace_store: Any


class RuntimeExportsModule(LifecycleModule):
    """Expose initialized runtime objects to DI and API bindings."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_exports",
            dependencies=(
                "runtime_agent_core",
                "runtime_command_queue",
                "runtime_chat_store",
                "runtime_chat_projector",
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
        container = get_container()
        if self._context.runtime_commands.full_clear_recovery_pending:
            self._override_full_clear_recovery_providers(container)
            self._override_background_task_manager(container)
            _override_chat_providers(container)
            self._override_optional_runtime_providers(container)
            logger.warning("Only full-clear recovery providers registered")
            return
        _override_required_providers(container, self._required_exports())
        self._override_background_task_manager(container)
        _override_chat_providers(container)
        _override_user_message_dispatcher(container)
        _configure_tool_capabilities()
        self._override_optional_runtime_providers(container)
        self._override_skill_providers(container)
        logger.info("DI container providers registered")

    def _override_full_clear_recovery_providers(self, container: Any) -> None:
        """Bind only services required to finish one pending global clear."""

        required = {
            "message_bus": self._context.message_bus.message_bus,
            "runtime_command_queue": (self._context.runtime_commands.runtime_command_queue),
            "chat_store": self._context.chat.store,
            "chat_projector": self._context.chat.projector,
            "memory_integration": self._context.memory.memory_integration,
            "unified_memory": self._context.memory.unified_memory,
            "plugin_manager": self._context.plugins.plugin_manager,
            "plugin_projection_service": (self._context.plugins.plugin_projection_service),
            "sensor_registry": self._context.plugins.sensor_registry,
            "runtime_trace_store": self._context.runtime_trace.store,
        }
        for provider_name, instance in required.items():
            resolved = require_initialized(instance, provider_name.replace("_", " "))
            getattr(container, provider_name).override(providers.Object(resolved))

    def _required_exports(self) -> _RequiredRuntimeExports:
        return _RequiredRuntimeExports(
            message_bus=require_initialized(self._context.message_bus.message_bus, "message bus"),
            runtime_command_queue=require_initialized(
                self._context.runtime_commands.runtime_command_queue,
                "runtime command queue",
            ),
            chat_store=require_initialized(self._context.chat.store, "chat store"),
            chat_projector=require_initialized(self._context.chat.projector, "chat projector"),
            agent_runtime=require_initialized(
                self._context.agent_runtime.agent_runtime, "agent runtime"
            ),
            memory_integration=require_initialized(
                self._context.memory.memory_integration, "memory integration"
            ),
            unified_memory=require_initialized(
                self._context.memory.unified_memory, "unified memory"
            ),
            hybrid_retrieval_service=require_initialized(
                self._context.memory.hybrid_retrieval_service,
                "hybrid retrieval service",
            ),
            plugin_manager=require_initialized(
                self._context.plugins.plugin_manager, "plugin manager"
            ),
            plugin_projection_service=require_initialized(
                self._context.plugins.plugin_projection_service,
                "plugin projection service",
            ),
            sensor_registry=require_initialized(
                self._context.plugins.sensor_registry, "sensor registry"
            ),
            runtime_trace_store=require_initialized(
                self._context.runtime_trace.store, "runtime trace store"
            ),
        )

    def _override_background_task_manager(self, container: Any) -> None:
        background_task_manager = self._context.agent_runtime.background_task_manager
        if background_task_manager is not None:
            container.background_task_manager.override(providers.Object(background_task_manager))

    def _override_optional_runtime_providers(self, container: Any) -> None:
        if self._context.scheduler.scheduler_service is not None:
            container.scheduler_service.override(
                providers.Object(self._context.scheduler.scheduler_service)
            )
        if self._context.agent_runtime.sensor_scheduler_contrib is not None:
            container.sensor_scheduler_contrib.override(
                providers.Object(self._context.agent_runtime.sensor_scheduler_contrib)
            )
        if self._context.llm.scenario_llm_pool is not None:
            container.scenario_llm_pool.override(
                providers.Object(self._context.llm.scenario_llm_pool)
            )

    def _override_skill_providers(self, container: Any) -> None:
        skill_indexer = self._context.skills.skill_indexer
        if skill_indexer is not None:
            container.skill_indexer.override(providers.Object(skill_indexer))
        skill_loader = self._context.skills.skill_loader
        if skill_loader is not None:
            container.skill_loader.override(providers.Object(skill_loader))
        skill_runner = self._context.skills.skill_runner
        if skill_runner is not None:
            container.skill_runner.override(providers.Object(skill_runner))

    async def shutdown(self) -> None:
        container = get_container()
        container.message_bus.reset_override()
        container.runtime_command_queue.reset_override()
        container.chat_store.reset_override()
        container.chat_projector.reset_override()
        container.agent_runtime.reset_override()
        container.memory_integration.reset_override()
        container.unified_memory.reset_override()
        container.hybrid_retrieval_service.reset_override()
        container.scheduler_service.reset_override()
        container.sensor_scheduler_contrib.reset_override()
        container.scenario_llm_pool.reset_override()
        container.plugin_manager.reset_override()
        container.plugin_projection_service.reset_override()
        container.sensor_registry.reset_override()
        container.runtime_trace_store.reset_override()
        container.skill_indexer.reset_override()
        container.skill_loader.reset_override()
        container.skill_runner.reset_override()
        container.background_task_manager.reset_override()
        container.chat_portrait_service.reset_override()
        container.chat_message_notifier.reset_override()
        container.user_message_dispatcher.reset_override()

        from ..tools.capabilities import reset_tool_capabilities_provider
        from .tool_capabilities import reset_tool_capabilities

        reset_tool_capabilities_provider()
        reset_tool_capabilities()


def _override_required_providers(container: Any, exports: _RequiredRuntimeExports) -> None:
    container.message_bus.override(providers.Object(exports.message_bus))
    container.runtime_command_queue.override(providers.Object(exports.runtime_command_queue))
    container.chat_store.override(providers.Object(exports.chat_store))
    container.chat_projector.override(providers.Object(exports.chat_projector))
    container.agent_runtime.override(providers.Object(exports.agent_runtime))
    container.memory_integration.override(providers.Object(exports.memory_integration))
    container.unified_memory.override(providers.Object(exports.unified_memory))
    container.hybrid_retrieval_service.override(providers.Object(exports.hybrid_retrieval_service))
    container.plugin_manager.override(providers.Object(exports.plugin_manager))
    container.plugin_projection_service.override(
        providers.Object(exports.plugin_projection_service)
    )
    container.sensor_registry.override(providers.Object(exports.sensor_registry))
    container.runtime_trace_store.override(providers.Object(exports.runtime_trace_store))


def _override_chat_providers(container: Any) -> None:
    from ..chat import get_chat_read_service
    from ..chat.message_notifications import chat_message_notifier
    from ..chat.portrait.factory import build_chat_portrait_service

    chat_portrait_service = build_chat_portrait_service(
        chat_read_service_factory=get_chat_read_service,
    )
    container.chat_portrait_service.override(providers.Object(chat_portrait_service))
    container.chat_message_notifier.override(providers.Object(chat_message_notifier))


def _override_user_message_dispatcher(container: Any) -> None:
    from ..chat.ingress import dispatch_user_message

    container.user_message_dispatcher.override(providers.Object(dispatch_user_message))


def _configure_tool_capabilities() -> None:
    from ..tools.capabilities import configure_tool_capabilities_provider
    from .tool_capabilities import build_tool_capabilities

    configure_tool_capabilities_provider(build_tool_capabilities)
