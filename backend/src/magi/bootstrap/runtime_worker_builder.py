"""Bootstrap builder for runtime-worker modules."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .exports import RuntimeExportsModule
from .lifecycle import LifecycleModule
from .maintenance import OtherDependenciesModule

from ..agent.lifecycle import AgentRuntimeModule
from ..awareness.lifecycle import (
    SensorModule,
    SensorScheduleRegistrationModule,
    SensorSyncExecutorModule,
)
from ..channels.lifecycle import ChannelsModule
from ..chat.lifecycle import ChatProjectorModule, ChatStoreModule
from ..config.lifecycle import ConfigurationModule
from ..context.lifecycle import ContextModule
from ..core.lifecycle import CoreDependenciesModule
from ..events.lifecycle import (
    MessageBusModule,
    PluginIngressProcessorModule,
    RuntimeCommandProcessorModule,
    RuntimeCommandQueueModule,
)
from ..llm.lifecycle import LLMRuntimeModule
from ..memory.lifecycle import (
    L2MaintenanceScheduleRegistrationModule,
    L3DigestScheduleRegistrationModule,
    L3SummaryScheduleRegistrationModule,
    MemoryStoreModule,
)
from ..personality.lifecycle import PersonalityModule
from ..plugins.lifecycle import PluginSystemModule
from ..runtime_trace import RuntimeTraceStore
from ..scheduler.lifecycle import SchedulerModule
from ..skills.lifecycle import SkillsModule
from ..timeline.lifecycle import TimelineModule
from ..tools.lifecycle import ToolsModule


def _build_runtime_trace_module(context: RuntimeBootstrapContext) -> LifecycleModule:
    async def _init_runtime_trace() -> None:
        from dependency_injector import providers as di_providers
        from ..core.container import get_container

        runtime_paths = context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        store = RuntimeTraceStore(db_path=str(runtime_paths.runtime_trace_db_path))
        await store.initialize()
        context.runtime_trace.store = store
        # Eagerly register DI binding so heartbeat and other infra consumers
        # work even when later modules (e.g. LLM) defer initialization.
        get_container().runtime_trace_store.override(di_providers.Object(store))

    async def _shutdown_runtime_trace() -> None:
        from ..core.container import get_container

        get_container().runtime_trace_store.reset_override()
        if context.runtime_trace.store is not None:
            await context.runtime_trace.store.shutdown()
            context.runtime_trace.store = None

    return LifecycleModule(
        name="runtime_trace",
        dependencies=("runtime_core_dependencies",),
        init=_init_runtime_trace,
        shutdown=_shutdown_runtime_trace,
    )


def build_runtime_worker_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build lifecycle modules required by the background runtime worker."""
    return [
        CoreDependenciesModule(context),
        ConfigurationModule(context),
        RuntimeCommandQueueModule(context),
        MessageBusModule(context),
        ChatStoreModule(context),
        PluginSystemModule(context),
        LLMRuntimeModule(context),
        MemoryStoreModule(context, start_memory_integration=True),
        ChatProjectorModule(context),
        _build_runtime_trace_module(context),
        ToolsModule(context),
        SkillsModule(context),
        PersonalityModule(context),
        SensorModule(context),
        ContextModule(context),
        AgentRuntimeModule(context),
        RuntimeCommandProcessorModule(context),
        PluginIngressProcessorModule(context),
        TimelineModule(context),
        SchedulerModule(context),
        SensorScheduleRegistrationModule(context),
        SensorSyncExecutorModule(context),
        RuntimeExportsModule(context),
        L2MaintenanceScheduleRegistrationModule(context),
        L3SummaryScheduleRegistrationModule(context),
        L3DigestScheduleRegistrationModule(context),
        OtherDependenciesModule(context),
        ChannelsModule(context),
    ]


__all__ = ["build_runtime_worker_modules"]
