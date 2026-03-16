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
    L8  SkillsModule              - Shared skills lifecycle
    L9  PersonalityModule         - Personality layer
    L10 SensorExecutorModule      - Sensors and actuators
    L11 ContextModule             - Context/prompt assembly
    L12 AgentRuntimeModule        - Agent runtime
    L13 TimelineModule            - Timeline service
    L14 SchedulerModule           - Scheduler engine
    L15 AgentScheduleRegistrationModule - Agent schedule registration
    L16 ActionScheduleRegistrationModule - Action schedule registration
    L17 TimelineScheduleRegistrationModule - Timeline schedule registration
    L18 RuntimeExportsModule      - DI container exports
    L19 OtherDependenciesModule   - Maintenance daemon

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
        SkillsModule(context),                # L8
        PersonalityModule(context),           # L9
        SensorExecutorModule(context),        # L10
        ContextModule(context),               # L11
        AgentRuntimeModule(context),          # L12
        TimelineModule(context),              # L13
        SchedulerModule(context),             # L14 (scheduler engine)
        AgentScheduleRegistrationModule(context),  # L15
        ActionScheduleRegistrationModule(context),  # L16
        TimelineScheduleRegistrationModule(context),  # L17
        RuntimeExportsModule(context),        # L18
        OtherDependenciesModule(context),     # L19
    ]
