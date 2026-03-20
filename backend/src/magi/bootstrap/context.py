"""Slice-based bootstrap context for layer-owned lifecycle modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import AppConfig
    from ..utils.runtime import RuntimePaths
    from ..core.database_initializer import DatabaseInitializer
    from ..core.maintenance import MaintenanceDaemon
    from ..llm import ScenarioLLMPool
    from ..llm.usage_events import LLMUsageEventPublisher
    from ..events.sqlite_backend import SQLiteMessageBackend
    from ..memory import UnifiedMemoryStore
    from ..memory.integration import MemoryIntegrationModule
    from ..memory.hybrid_retrieval import HybridRetrievalService
    from ..plugins import ActionRegistry, PluginManager, SensorRegistry
    from ..personality.self_memory import SelfMemory
    from ..personality.other_memory import OtherMemory
    from ..context.scenario_prompts import ScenarioPromptsStore
    from ..awareness.sensor_hub import SensorHub
    from ..agent.runtime import AgentRuntime, TaskAgentManager
    from ..awareness.action_emitter import ActionEmitter
    from ..timeline.service import TimelineService
    from ..timeline.scheduler_contrib import TimelineSchedulerContrib
    from ..scheduler import SchedulerService
    from ..runtime_trace import RuntimeTraceStore


def require_initialized(value: Any, name: str) -> Any:
    """Return value if not None, otherwise raise RuntimeError.

    Args:
        value: The value to check
        name: Name of the value for error message

    Returns:
        The value if not None

    Raises:
        RuntimeError: If value is None
    """
    if value is None:
        raise RuntimeError(f"{name} is not initialized")
    return value


@dataclass
class CoreBootstrapState:
    """L1 Application Infrastructure state slice."""

    config: AppConfig | None = None
    runtime_paths: RuntimePaths | None = None
    db_initializer: DatabaseInitializer | None = None
    current_personality: str = "default"


@dataclass
class LLMBootstrapState:
    """L5 LLM Runtime state slice."""

    scenario_llm_pool: ScenarioLLMPool | None = None
    llm_adapter: Any = None
    llm_usage_store: Any = None
    llm_usage_event_publisher: LLMUsageEventPublisher | None = None


@dataclass
class MessageBusBootstrapState:
    """L3 Message Bus state slice."""

    message_bus: SQLiteMessageBackend | None = None


@dataclass
class PluginBootstrapState:
    """L4 Plugin runtime state slice."""

    plugin_manager: PluginManager | None = None
    sensor_registry: SensorRegistry | None = None
    action_registry: ActionRegistry | None = None


@dataclass
class MemoryBootstrapState:
    """L6 Memory Layer state slice."""

    unified_memory: UnifiedMemoryStore | None = None
    memory_integration: MemoryIntegrationModule | None = None
    hybrid_retrieval_service: HybridRetrievalService | None = None


@dataclass
class SkillsBootstrapState:
    """L7 shared skills runtime state slice."""

    skill_indexer: Any = None
    skill_loader: Any = None
    skill_runner: Any = None


@dataclass
class PersonalityBootstrapState:
    """L8 Personality Layer state slice."""

    self_memory: SelfMemory | None = None
    other_memory: OtherMemory | None = None


@dataclass
class ContextBootstrapState:
    """L10 Context Layer state slice."""

    scenario_prompts_store: ScenarioPromptsStore | None = None


@dataclass
class AgentRuntimeBootstrapState:
    """L11 Agent Runtime state slice."""

    sensor_hub: SensorHub | None = None
    action_emitter: ActionEmitter | None = None
    agent_runtime: AgentRuntime | None = None
    task_agent_manager: TaskAgentManager | None = None


@dataclass
class TimelineBootstrapState:
    """L12 Timeline Domain state slice."""

    timeline_service: TimelineService | None = None
    timeline_scheduler_contrib: TimelineSchedulerContrib | None = None


@dataclass
class SchedulerBootstrapState:
    """Scheduler engine state slice (L1 infrastructure)."""

    scheduler_service: SchedulerService | None = None


@dataclass
class MaintenanceBootstrapState:
    """Maintenance daemon state slice."""

    maintenance_daemon: MaintenanceDaemon | None = None


@dataclass
class RuntimeTraceBootstrapState:
    """Runtime trace observability state slice."""

    store: RuntimeTraceStore | None = None


@dataclass
class RuntimeBootstrapContext:
    """Slice-based bootstrap context shared across layer lifecycle modules.

    This replaces the monolithic RuntimeBootstrapState with a cleaner
    slice-based approach where each layer owns its state slice.
    """

    core: CoreBootstrapState = field(default_factory=CoreBootstrapState)
    message_bus: MessageBusBootstrapState = field(default_factory=MessageBusBootstrapState)
    plugins: PluginBootstrapState = field(default_factory=PluginBootstrapState)
    llm: LLMBootstrapState = field(default_factory=LLMBootstrapState)
    memory: MemoryBootstrapState = field(default_factory=MemoryBootstrapState)
    skills: SkillsBootstrapState = field(default_factory=SkillsBootstrapState)
    personality: PersonalityBootstrapState = field(default_factory=PersonalityBootstrapState)
    context: ContextBootstrapState = field(default_factory=ContextBootstrapState)
    agent_runtime: AgentRuntimeBootstrapState = field(default_factory=AgentRuntimeBootstrapState)
    timeline: TimelineBootstrapState = field(default_factory=TimelineBootstrapState)
    scheduler: SchedulerBootstrapState = field(default_factory=SchedulerBootstrapState)
    runtime_trace: RuntimeTraceBootstrapState = field(default_factory=RuntimeTraceBootstrapState)
    maintenance: MaintenanceBootstrapState = field(default_factory=MaintenanceBootstrapState)
