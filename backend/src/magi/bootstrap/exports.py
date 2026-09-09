"""Capability-owned exports for product API dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dependency_injector import providers

from .lifecycle import LifecycleModule
from .context import RuntimeBootstrapContext, require_initialized
from ..core.container import get_container


class CapabilityExportsModule(LifecycleModule):
    """Publish bindings only after their owning capability becomes available."""

    def __init__(
        self, name: str, *, dependencies: tuple[str, ...],
        bindings: Callable[[], dict[str, Any]],
    ) -> None:
        super().__init__(name=name, dependencies=dependencies)
        self._bindings = bindings
        self._exported: list[str] = []

    async def init(self) -> None:
        container = get_container()
        for name, instance in self._bindings().items():
            if instance is None:
                continue
            getattr(container, name).override(providers.Object(instance))
            self._exported.append(name)

    async def shutdown(self) -> None:
        container = get_container()
        for name in reversed(self._exported):
            getattr(container, name).reset_override()
        self._exported.clear()


def build_capability_exports(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Bind management, plugin metadata, storage and collection independently."""
    from ..chat.message_notifications import chat_message_notifier
    from ..chat import get_chat_read_service
    from ..chat.portrait.factory import build_chat_portrait_service

    return [
        CapabilityExportsModule(
            "runtime_base_exports",
            dependencies=("runtime_configuration", "runtime_database_migrations",
                          "runtime_control_plane", "runtime_chat_projector", "runtime_trace"),
            bindings=lambda: {
                "message_bus": context.message_bus.message_bus,
                "runtime_command_queue": context.runtime_commands.runtime_command_queue,
                "chat_store": context.chat.store,
                "chat_projector": context.chat.projector,
                "runtime_trace_store": context.runtime_trace.store,
                "chat_message_notifier": chat_message_notifier,
                "chat_portrait_service": build_chat_portrait_service(
                    chat_read_service_factory=get_chat_read_service),
            },
        ),
        CapabilityExportsModule(
            "runtime_plugin_exports", dependencies=("runtime_plugin_system", "runtime_llm_pool"),
            bindings=lambda: {
                "plugin_manager": context.plugins.plugin_manager,
                "plugin_projection_service": context.plugins.plugin_projection_service,
                "source_registry": context.plugins.source_registry,
                "skill_indexer": context.skills.skill_indexer,
                "skill_loader": context.skills.skill_loader,
                "scenario_llm_pool": context.llm.scenario_llm_pool,
            },
        ),
        CapabilityExportsModule(
            "runtime_memory_exports", dependencies=("runtime_memory",),
            bindings=lambda: {
                "unified_memory": context.memory.unified_memory,
                "memory_integration": context.memory.memory_integration,
            },
        ),
        CapabilityExportsModule(
            "runtime_scheduler_exports", dependencies=("runtime_scheduler",),
            bindings=lambda: {"scheduler_service": context.scheduler.scheduler_service},
        ),
        CapabilityExportsModule(
            "runtime_source_exports", dependencies=("runtime_source_scheduler",),
            bindings=lambda: {
                "source_scheduler_contrib": context.agent_runtime.source_scheduler_contrib,
            },
        ),
    ]


class RuntimeExportsModule(CapabilityExportsModule):
    """Publish execution services after their dependencies are ready."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        self._context = context
        super().__init__(
            "runtime_exports",
            dependencies=("runtime_agent_core", "runtime_memory_processing",
                          "runtime_base_exports", "runtime_plugin_exports", "runtime_memory_exports"),
            bindings=self._runtime_bindings,
        )

    def _runtime_bindings(self) -> dict[str, Any]:
        if self._context.runtime_commands.full_clear_recovery_pending:
            return {"background_task_manager": self._context.agent_runtime.background_task_manager}
        from ..chat.ingress import dispatch_user_message

        return {
            "agent_runtime": require_initialized(self._context.agent_runtime.agent_runtime, "agent runtime"),
            "background_task_manager": self._context.agent_runtime.background_task_manager,
            "hybrid_retrieval_service": self._context.memory.hybrid_retrieval_service,
            "skill_runner": self._context.skills.skill_runner,
            "user_message_dispatcher": dispatch_user_message,
        }

    async def init(self) -> None:
        await super().init()
        from ..tools.capabilities import configure_tool_capabilities_provider
        from .tool_capabilities import build_tool_capabilities

        configure_tool_capabilities_provider(build_tool_capabilities)

    async def shutdown(self) -> None:
        await super().shutdown()
        from ..tools.capabilities import reset_tool_capabilities_provider
        from .tool_capabilities import reset_tool_capabilities

        reset_tool_capabilities_provider()
        reset_tool_capabilities()
