"""Slice-based bootstrap context for layer-owned lifecycle modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ..chat import ChatProjector, ChatStore
    from ..config import AppConfig
    from ..utils.runtime import RuntimePaths
    from ..core.initialization_state import InitializationStateStore
    from ..core.maintenance import MaintenanceDaemon
    from ..llm import ScenarioLLMPool
    from ..events.backend import MessageBusBackend
    from ..events.runtime_queue import SQLiteRuntimeCommandQueue
    from ..events.lifecycle import RuntimeCommandProcessorModule
    from ..memory import UnifiedMemoryStore
    from ..memory.integration import MemoryIntegrationModule
    from ..memory.hybrid_retrieval import HybridRetrievalService
    from ..media.source_registry import MediaSourceRegistry
    from ..plugins import PluginManager, PluginProjectionService, SensorRegistry
    from ..personality.self_memory import SelfMemory
    from ..awareness.scheduler_contrib import SensorSchedulerContrib
    from ..awareness.sensor_hub import SensorHub
    from ..agent.runtime import AgentRuntime, TaskAgentManager
    from ..awareness.event_emitter import RuntimeEventEmitter
    from ..timeline.service import TimelineService
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
    initialization_state: InitializationStateStore | None = None
    # Empty string until PersonalityModule.init() resolves the active persona
    # from the registry. ConfigModule may set a preliminary preferred name from
    # config.agent.personality.name; an empty value means "no preference,
    # use the first builtin from the registry."
    current_personality: str = ""


@dataclass
class LLMBootstrapState:
    """L5 LLM Runtime state slice."""

    scenario_llm_pool: ScenarioLLMPool | None = None
    llm_adapter: Any = None
    llm_usage_store: Any = None
    llm_usage_subscriber: Any = None


@dataclass
class MessageBusBootstrapState:
    """L3 Message Bus state slice."""

    message_bus: MessageBusBackend | None = None


@dataclass
class RuntimeCommandBootstrapState:
    """Persisted runtime command queue state slice."""

    runtime_command_queue: SQLiteRuntimeCommandQueue | None = None
    runtime_command_processor: RuntimeCommandProcessorModule | None = None


@dataclass
class ChatBootstrapState:
    """Dedicated chat-domain persistence slice."""

    store: ChatStore | None = None
    projector: ChatProjector | None = None
    assistant_memory_projection_service: Any | None = None
    delivery_scheduler: Any | None = None
    channel_session_provisioner: Any | None = None
    channel_attachment_store: Any | None = None
    # Phase F: ChatStoreModule sets ``module`` to itself so lifecycle
    # assembly can pass the live ConversationLog into chat runtime wiring.
    module: Any | None = None


@dataclass
class PluginBootstrapState:
    """L4 Plugin runtime state slice."""

    plugin_manager: PluginManager | None = None
    plugin_projection_service: PluginProjectionService | None = None
    sensor_registry: SensorRegistry | None = None


@dataclass
class MemoryBootstrapState:
    """L6 Memory Layer state slice."""

    unified_memory: UnifiedMemoryStore | None = None
    memory_integration: MemoryIntegrationModule | None = None
    hybrid_retrieval_service: HybridRetrievalService | None = None
    ingestion_subscriber: Any = None
    media_source_registry: "MediaSourceRegistry | None" = None


@dataclass
class LocationBootstrapState:
    """Location subsystem state slice — owned by LocationModule.

    Built once and read by timeline (resolver for viewport, sources for the
    pollers). The sample store is also exposed via the ``location_sample_store``
    DI binding for the manual-entry API router.
    """

    sample_store: Any = None
    geocode_cache: Any = None
    resolver: Any = None
    wifi_source: Any = None
    ipgeo_source: Any = None


@dataclass
class ManualEntriesBootstrapState:
    """Manual-entry subsystem state slice — owned by ManualEntriesModule.

    A timeline-surface feature (notes added/rendered on the timeline page).
    Built once and exposed via DI for the manual-entry API router; the asset
    store is also injected into TimelineService for asset resolution. Memory's
    only stake is the L1 projection, built at the API boundary from the L1 store.
    """

    store: Any = None
    asset_store: Any = None
    weather_fetcher: Any = None
    recovery_service: Any = None


@dataclass
class HistoryImportsBootstrapState:
    """One-shot history import state owned by HistoryImportsModule."""

    store: Any = None
    service: Any = None


@dataclass
class SkillsBootstrapState:
    """L7 shared skills runtime state slice."""

    skill_indexer: Any = None
    skill_loader: Any = None
    skill_runner: Any = None


@dataclass
class HooksBootstrapState:
    """Programmable hooks subsystem state slice.

    Lives next to skills/permission so the agent runtime can resolve a
    single ``HookGateway`` instance regardless of which subsystem triggered
    the dispatch.
    """

    registry: Any = None
    gateway: Any = None


@dataclass
class PersonalityBootstrapState:
    """L8 Personality Layer state slice."""

    self_memory: SelfMemory | None = None


@dataclass
class ContextBootstrapState:
    """L10 Context Layer state slice."""

    pass


@dataclass
class AgentRuntimeBootstrapState:
    """L11 Agent Runtime state slice."""

    sensor_hub: SensorHub | None = None
    event_emitter: RuntimeEventEmitter | None = None
    sensor_ingestion_gateway: Any = None
    sensor_scheduler_contrib: SensorSchedulerContrib | None = None
    sensor_sync_executor: Any = None
    agent_runtime: AgentRuntime | None = None
    task_agent_manager: TaskAgentManager | None = None
    post_turn_understanding_service: Any = None
    background_task_manager: Any = None
    background_task_retention_schedule: Any = None


@dataclass
class TimelineBootstrapState:
    """L12 Timeline Domain state slice."""

    timeline_service: TimelineService | None = None


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
    subscriber: Any = None


@dataclass
class ChannelsBootstrapState:
    """External messaging channels state slice."""

    module: Any | None = None


@dataclass
class OutreachBootstrapState:
    """Proactive delivery state shared with destructive data boundaries."""

    service: Any | None = None


@dataclass
class ControlPlaneBootstrapState:
    """Control-plane state slice — exposes ControlPlaneModule so later-
    initializing modules (ChannelsModule for the Phase H+2 control
    fanout binding) can reach the prompter without a hard module
    dependency."""

    module: Any | None = None


@dataclass
class IdentityBootstrapState:
    """L1 Identity Layer state slice.

    Exposes the active resolver + store for the four ingress sites
    (channels dispatcher, api dispatch, sensor_hub, session_mapper)
    to pull at module-init time.
    """

    store: Any | None = None
    resolver: Any | None = None
    module: Any | None = None


@dataclass
class RuntimeBootstrapContext:
    """Slice-based bootstrap context shared across layer lifecycle modules.

    This replaces the monolithic RuntimeBootstrapState with a cleaner
    slice-based approach where each layer owns its state slice.
    """

    core: CoreBootstrapState = field(default_factory=CoreBootstrapState)
    runtime_commands: RuntimeCommandBootstrapState = field(
        default_factory=RuntimeCommandBootstrapState
    )
    chat: ChatBootstrapState = field(default_factory=ChatBootstrapState)
    message_bus: MessageBusBootstrapState = field(default_factory=MessageBusBootstrapState)
    plugins: PluginBootstrapState = field(default_factory=PluginBootstrapState)
    llm: LLMBootstrapState = field(default_factory=LLMBootstrapState)
    memory: MemoryBootstrapState = field(default_factory=MemoryBootstrapState)
    location: LocationBootstrapState = field(default_factory=LocationBootstrapState)
    manual_entries: ManualEntriesBootstrapState = field(default_factory=ManualEntriesBootstrapState)
    history_imports: HistoryImportsBootstrapState = field(
        default_factory=HistoryImportsBootstrapState
    )
    skills: SkillsBootstrapState = field(default_factory=SkillsBootstrapState)
    hooks: HooksBootstrapState = field(default_factory=HooksBootstrapState)
    personality: PersonalityBootstrapState = field(default_factory=PersonalityBootstrapState)
    context: ContextBootstrapState = field(default_factory=ContextBootstrapState)
    agent_runtime: AgentRuntimeBootstrapState = field(default_factory=AgentRuntimeBootstrapState)
    timeline: TimelineBootstrapState = field(default_factory=TimelineBootstrapState)
    scheduler: SchedulerBootstrapState = field(default_factory=SchedulerBootstrapState)
    runtime_trace: RuntimeTraceBootstrapState = field(default_factory=RuntimeTraceBootstrapState)
    maintenance: MaintenanceBootstrapState = field(default_factory=MaintenanceBootstrapState)
    channels: ChannelsBootstrapState = field(default_factory=ChannelsBootstrapState)
    outreach: OutreachBootstrapState = field(default_factory=OutreachBootstrapState)
    control_plane: ControlPlaneBootstrapState = field(default_factory=ControlPlaneBootstrapState)
    identity: IdentityBootstrapState = field(default_factory=IdentityBootstrapState)
