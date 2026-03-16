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
from ..tools.lifecycle import ToolsModule
from ..personality.lifecycle import PersonalityModule
from ..awareness.lifecycle import SensorExecutorModule, ActionScheduleRegistrationModule
from ..context.lifecycle import ContextModule
from ..agent.lifecycle import AgentRuntimeModule, AgentScheduleRegistrationModule
from ..timeline.lifecycle import TimelineModule, TimelineScheduleRegistrationModule
from ..scheduler.lifecycle import SchedulerModule


def build_runtime_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules from layer-owned contributions.

    Order aligns with the layered architecture:
    L1  CoreDependenciesModule    - Application-level infrastructure
    L2  ConfigurationModule       - Configuration loading
    L3  MessageBusModule          - Message bus
    L4  PluginSystemModule        - Plugin system
    L5  LLMRuntimeModule          - LLM runtime
    L6  MemoryStoreModule         - Memory stores (L0-L5)
    L7  ToolsModule               - Tool integrations
    L8  PersonalityModule         - Personality layer
    L9  SensorExecutorModule      - Sensors and actuators
    L10 ContextModule             - Context/prompt assembly
    L11 AgentRuntimeModule        - Agent runtime
    L12 TimelineModule            - Timeline service
    L13 SchedulerModule           - Scheduler engine
    L14 AgentScheduleRegistrationModule - Agent schedule registration
    L15 ActionScheduleRegistrationModule - Action schedule registration
    L16 TimelineScheduleRegistrationModule - Timeline schedule registration
    L17 RuntimeExportsModule      - DI container exports
    L18 OtherDependenciesModule   - Maintenance daemon

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
        ToolsModule(context),                 # L7
        PersonalityModule(context),           # L8
        SensorExecutorModule(context),        # L9
        ContextModule(context),               # L10
        AgentRuntimeModule(context),          # L11
        TimelineModule(context),              # L12
        SchedulerModule(context),             # L13 (scheduler engine)
        AgentScheduleRegistrationModule(context),  # L14
        ActionScheduleRegistrationModule(context),  # L15
        TimelineScheduleRegistrationModule(context),  # L16
        RuntimeExportsModule(context),        # L17
        OtherDependenciesModule(context),     # L18
    ]
