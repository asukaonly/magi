"""Bootstrap builder for assembling lifecycle modules from owning layers."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule
from .exports import RuntimeExportsModule
from .maintenance import OtherDependenciesModule

from ..core.lifecycle import CoreDependenciesModule
from ..config.lifecycle import ConfigurationModule
from ..events.lifecycle import MessageBusModule
from ..plugins.lifecycle import PluginSystemModule
from ..llm.lifecycle import LLMRuntimeModule
from ..memory.lifecycle import MemoryStoreModule
from ..skills.lifecycle import SkillsModule
from ..tools.lifecycle import ToolsModule
from ..personality.lifecycle import PersonalityModule
from ..awareness.lifecycle import SensorsAndActionsModule, ActionScheduleRegistrationModule
from ..context.lifecycle import ContextModule
from ..agent.lifecycle import AgentRuntimeModule, AgentScheduleRegistrationModule
from ..timeline.lifecycle import TimelineModule, TimelineScheduleRegistrationModule
from ..scheduler.lifecycle import SchedulerModule
from ..runtime_trace import RuntimeTraceStore


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


def build_runtime_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules from layer-owned contributions.

    Order aligns with the layered architecture:
    L1  CoreDependenciesModule    - Application-level infrastructure
    L2  ConfigurationModule       - Configuration loading
    L3  MessageBusModule          - Message bus
    L4  PluginSystemModule        - Plugin system
    L5  LLMRuntimeModule          - LLM runtime
    L6  MemoryStoreModule         - Memory stores (L0-L4)
    L7  Runtime trace module      - Execution observability store
    L8  ToolsModule               - Tool integrations
    L9  SkillsModule              - Shared skills lifecycle
    L10 PersonalityModule         - Personality layer
    L11 SensorsAndActionsModule   - Sensors and actuators
    L12 ContextModule             - Context/prompt assembly
    L13 AgentRuntimeModule        - Agent runtime
    L14 TimelineModule            - Timeline service
    L15 SchedulerModule           - Scheduler engine
    L16 AgentScheduleRegistrationModule - Agent schedule registration
    L17 ActionScheduleRegistrationModule - Action schedule registration
    L18 TimelineScheduleRegistrationModule - Timeline schedule registration
    L19 RuntimeExportsModule      - DI container exports
    L20 OtherDependenciesModule   - Maintenance daemon

    Args:
        context: The shared bootstrap context containing layer state slices

    Returns:
        Ordered list of lifecycle modules ready for orchestration
    """
    return [
        CoreDependenciesModule(context),      # L1
        ConfigurationModule(context),         # L2
        MessageBusModule(context),            # L3
        PluginSystemModule(context),          # L4
        LLMRuntimeModule(context),            # L5
        MemoryStoreModule(context),           # L6
        _build_runtime_trace_module(context),  # L7
        ToolsModule(context),                 # L8
        SkillsModule(context),                # L9
        PersonalityModule(context),           # L10
        SensorsAndActionsModule(context),     # L11
        ContextModule(context),               # L12
        AgentRuntimeModule(context),          # L13
        TimelineModule(context),              # L14
        SchedulerModule(context),             # L15 (scheduler engine)
        AgentScheduleRegistrationModule(context),  # L16
        ActionScheduleRegistrationModule(context),  # L17
        TimelineScheduleRegistrationModule(context),  # L18
        RuntimeExportsModule(context),        # L19
        OtherDependenciesModule(context),     # L20
    ]
