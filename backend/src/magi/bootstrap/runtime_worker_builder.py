"""Bootstrap builder for runtime-worker modules."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .exports import RuntimeExportsModule
from .lifecycle import LifecycleModule
from .maintenance import OtherDependenciesModule

from ..agent.lifecycle import AgentRuntimeModule
from ..awareness.lifecycle import (
    SensorsAndActionsModule,
    SensorScheduleRegistrationModule,
    SensorSyncExecutorModule,
)
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
from ..memory.lifecycle import L2MaintenanceScheduleRegistrationModule, L3SummaryScheduleRegistrationModule, MemoryStoreModule
from ..personality.lifecycle import PersonalityModule
from ..plugins.lifecycle import PluginSystemModule
from ..scheduler.lifecycle import SchedulerModule
from ..skills.lifecycle import SkillsModule
from ..timeline.lifecycle import TimelineModule
from ..tools.lifecycle import ToolsModule

from .api_builder import _build_runtime_trace_module


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
        SensorsAndActionsModule(context),
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
        OtherDependenciesModule(context),
    ]


__all__ = ["build_runtime_worker_modules"]
