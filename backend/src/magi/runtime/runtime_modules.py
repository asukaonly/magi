"""Runtime lifecycle modules and shared bootstrap state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from dependency_injector import providers

from ..agent.task_agents.factory import create_chat_agent_factory, create_default_agent_factory
from ..agent.scheduler_contrib import AgentSchedulerContrib
from ..config import AppConfig, get_config
from ..core.container import get_container
from ..core.database_initializer import DatabaseInitializer, set_database_initializer
from ..core.logger import get_logger
from ..core.runtime import (
    ActionExecutor,
    AgentRuntime,
    RouterAgent,
    SensorHub,
    TaskAgentManager,
)
from ..core.runtime.action_scheduler_contrib import ActionSchedulerContrib
from ..events.sqlite_backend import SQLiteMessageBackend
from ..llm import LLMScenario, ScenarioLLMPool, get_llm_usage_store
from ..llm.factory import create_core_llm_adapter, create_scenario_llm_pool, is_llm_selection_pending
from ..llm.usage_events import configure_llm_usage_event_publisher
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationConfig, MemoryIntegrationModule
from ..context.scenario_prompts import ScenarioPromptsStore, initialize_default_prompts
from ..personality.other_memory import OtherMemory
from ..personality.self_memory import SelfMemory
from ..plugins import (
    get_action_registry,
    get_plugin_manager,
    get_sensor_registry,
    initialize_plugin_manager,
)
from ..scheduler import SchedulerBootstrap, SchedulerService, set_scheduler_runtime
from ..timeline.scheduler_contrib import TimelineSchedulerContrib, set_timeline_scheduler_contrib
from ..timeline.service import TimelineService
from ..utils.runtime import RuntimePaths, get_runtime_paths, init_runtime_data
from .lifecycle import LifecycleModule
from .maintenance import MaintenanceConfig, MaintenanceDaemon, set_maintenance_daemon

logger = get_logger(__name__)


class RuntimeInitializationDeferred(Exception):
    """Raised when runtime initialization should be deferred (usually onboarding stage)."""

    def __init__(self, *, pending_selection: bool, cause: Exception | None = None) -> None:
        self.pending_selection = pending_selection
        self.cause = cause
        message = "runtime_llm_selection_pending" if pending_selection else "runtime_llm_configuration_invalid"
        super().__init__(message)


@dataclass
class RuntimeBootstrapState:
    """Mutable state shared across runtime lifecycle modules."""

    config: AppConfig | None = None
    runtime_paths: RuntimePaths | None = None
    current_personality: str = "default"
    scenario_llm_pool: ScenarioLLMPool | None = None
    llm_adapter: Any = None
    message_bus: SQLiteMessageBackend | None = None
    llm_usage_store: Any = None
    self_memory: SelfMemory | None = None
    other_memory: OtherMemory | None = None
    unified_memory: UnifiedMemoryStore | None = None
    memory_integration: MemoryIntegrationModule | None = None
    scenario_prompts_store: ScenarioPromptsStore | None = None
    sensor_hub: SensorHub | None = None
    action_executor: ActionExecutor | None = None
    agent_runtime: AgentRuntime | None = None
    task_agent_manager: TaskAgentManager | None = None
    timeline_service: TimelineService | None = None
    scheduler_service: SchedulerService | None = None
    scheduler_bootstrap: SchedulerBootstrap | None = None
    maintenance_daemon: MaintenanceDaemon | None = None
    db_initializer: DatabaseInitializer | None = None


def _require(value: Any, message: str) -> Any:
    if value is None:
        raise RuntimeError(message)
    return value






class CoreDependenciesModule(LifecycleModule):
    """Initialize low-level runtime paths and host resources."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(name="runtime_core_dependencies")
        self._state = state

    async def init(self) -> None:
        init_runtime_data()
        self._state.runtime_paths = get_runtime_paths()
        logger.info("Runtime directory: %s", self._state.runtime_paths.base_dir)

        db_initializer = DatabaseInitializer(data_dir=self._state.runtime_paths.data_dir)
        await db_initializer.initialize_all()
        set_database_initializer(db_initializer)
        self._state.db_initializer = db_initializer
        logger.info("Database initialization completed")


class ConfigurationModule(LifecycleModule):
    """Load runtime configuration and personality context."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_configuration",
            dependencies=("runtime_core_dependencies",),
        )
        self._state = state

    async def init(self) -> None:
        self._state.config = get_config()
        current_personality = "default"
        try:
            from .services.personality_state import get_current_personality

            current_personality = get_current_personality() or "default"
        except Exception as exc:
            logger.warning("Failed to get current personality: %s", exc)
        self._state.current_personality = current_personality


class MessageBusModule(LifecycleModule):
    """Start and stop message bus infrastructure."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_message_bus",
            dependencies=("runtime_configuration", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")
        self._state.message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.message_queue_db_path),
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
            broadcast_max_concurrency=config.agent.message_bus.broadcast_max_concurrency,
            handler_timeout_seconds=config.agent.message_bus.handler_timeout_seconds,
            max_retries=config.agent.message_bus.max_retries,
            retry_delay_seconds=config.agent.message_bus.retry_delay_seconds,
        )
        await self._state.message_bus.start()
        logger.info("MessageBus started")

    async def shutdown(self) -> None:
        if self._state.message_bus is not None:
            await self._state.message_bus.stop()
            self._state.message_bus = None


class PluginSystemModule(LifecycleModule):
    """Initialize plugin manager and plugin metadata."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_plugin_system",
            dependencies=("runtime_message_bus",),
        )
        self._state = state

    async def init(self) -> None:
        initialize_plugin_manager(force=True)


class LLMRuntimeModule(LifecycleModule):
    """Initialize scenario-based LLM pool and core adapter."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_llm",
            dependencies=("runtime_plugin_system", "runtime_configuration"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        try:
            self._state.scenario_llm_pool = create_scenario_llm_pool(config)
            self._state.scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
            self._state.llm_adapter = create_core_llm_adapter(self._state.scenario_llm_pool)
        except Exception as exc:
            raise RuntimeInitializationDeferred(
                pending_selection=is_llm_selection_pending(config),
                cause=exc,
            ) from exc

    async def shutdown(self) -> None:
        self._state.scenario_llm_pool = None
        self._state.llm_adapter = None


class MemoryStoreModule(LifecycleModule):
    """Initialize persistence, memory stores, usage metrics, and memory integration (L6)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_memory",
            dependencies=("runtime_llm", "runtime_message_bus", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")
        message_bus = _require(self._state.message_bus, "message bus is required")

        await self._state.db_initializer.insert_default_data(persona_name=self._state.current_personality)

        configure_llm_usage_event_publisher(message_bus)
        self._state.llm_usage_store = get_llm_usage_store()
        await self._state.llm_usage_store.start(message_bus)
        logger.info("LLM usage store started")

        self._state.unified_memory = UnifiedMemoryStore(
            l1_db_path=str(runtime_paths.l1_memory_db_path),
            memory_db_path=str(runtime_paths.memory_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_l0=config.agent.memory.enable_l0,
            enable_l1=config.agent.memory.enable_l1,
            enable_l2=config.agent.memory.enable_l2,
            enable_l3=config.agent.memory.enable_l3,
            enable_l4=config.agent.memory.enable_l4,
            l0_checkpoint_interval_seconds=config.agent.memory.l0_checkpoint_interval_seconds,
        )
        await self._state.unified_memory.initialize()
        logger.info("UnifiedMemoryStore initialized (L0-L4)")

        memory_integration_config = MemoryIntegrationConfig(
            enable_l0=config.agent.memory.enable_l0,
            enable_l1=config.agent.memory.enable_l1,
            enable_l2=config.agent.memory.enable_l2,
            enable_l3=config.agent.memory.enable_l3,
            enable_l4=config.agent.memory.enable_l4,
            enable_l1_raw=config.agent.memory.enable_l1,
            enable_l2_relations=config.agent.memory.enable_l2,
            enable_l3_embeddings=config.agent.memory.enable_l3,
            enable_l4_summaries=config.agent.memory.enable_l3,
            enable_l5_capabilities=config.agent.memory.enable_l4,
            summary_interval_minutes=config.agent.memory.summary_interval_minutes,
        )
        self._state.memory_integration = MemoryIntegrationModule(
            unified_memory=self._state.unified_memory,
            message_bus=message_bus,
            config=memory_integration_config,
        )
        await self._state.memory_integration.start()
        logger.info("MemoryIntegrationModule started")

    async def shutdown(self) -> None:
        if self._state.memory_integration is not None:
            await self._state.memory_integration.stop()
            self._state.memory_integration = None

        if self._state.llm_usage_store is not None:
            await self._state.llm_usage_store.stop()
            self._state.llm_usage_store = None
        configure_llm_usage_event_publisher(None)

        self._state.unified_memory = None


class PersonalityModule(LifecycleModule):
    """Initialize self-memory and other-memory personality stores (L8)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_personality",
            dependencies=("runtime_memory", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")

        self._state.self_memory = SelfMemory(
            personality_name=self._state.current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await self._state.self_memory.init()
        self._state.other_memory = OtherMemory()

    async def shutdown(self) -> None:
        self._state.self_memory = None
        self._state.other_memory = None


class ContextModule(LifecycleModule):
    """Initialize scenario prompts store and load default prompts (L10)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_context",
            dependencies=("runtime_personality", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")

        self._state.scenario_prompts_store = ScenarioPromptsStore(
            db_path=str(runtime_paths.scenario_prompts_db_path)
        )
        await self._state.scenario_prompts_store.init()
        await initialize_default_prompts(
            self._state.scenario_prompts_store,
            persona_name=self._state.current_personality,
        )

    async def shutdown(self) -> None:
        self._state.scenario_prompts_store = None


class ToolsModule(LifecycleModule):
    """Configure runtime tool integrations and skills runtime bridge."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_tools",
            dependencies=("runtime_llm", "runtime_configuration"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        llm_adapter = _require(self._state.llm_adapter, "llm adapter is required")

        from ..tools import tool_registry

        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(llm_adapter=llm_adapter, tool_registry_instance=tool_registry)
            logger.info("Agent tool configured with runtime LLM adapter")

        if config.features.enable_skills:
            from .services.skills import init_skills_module

            init_skills_module(llm_adapter)
            logger.info("Skills module initialized")


class SensorExecutorModule(LifecycleModule):
    """Initialize SensorHub and ActionExecutor (L9 - Sensors/Actuators layer)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_sensor_executor",
            dependencies=("runtime_message_bus",),
        )
        self._state = state

    async def init(self) -> None:
        message_bus = _require(self._state.message_bus, "message bus is required")

        self._state.sensor_hub = SensorHub(message_bus=message_bus)
        self._state.action_executor = ActionExecutor(message_bus=message_bus)
        logger.info("SensorHub and ActionExecutor initialized (L9)")

    async def shutdown(self) -> None:
        self._state.sensor_hub = None
        self._state.action_executor = None


class AgentRuntimeModule(LifecycleModule):
    """Initialize TaskAgentManager, RouterAgent, and AgentRuntime (L11 - Agent Runtime layer)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_agent_core",
            dependencies=("runtime_sensor_executor", "runtime_context", "runtime_personality", "runtime_memory", "runtime_llm", "runtime_configuration"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        llm_adapter = _require(self._state.llm_adapter, "llm adapter is required")
        llm_pool = _require(self._state.scenario_llm_pool, "llm pool is required")
        memory = _require(self._state.self_memory, "self memory is required")
        other_memory = _require(self._state.other_memory, "other memory is required")
        unified_memory = _require(self._state.unified_memory, "unified memory is required")
        memory_integration = _require(self._state.memory_integration, "memory integration is required")
        scenario_prompts_store = _require(self._state.scenario_prompts_store, "scenario prompts store is required")
        sensor_hub = _require(self._state.sensor_hub, "sensor hub is required")
        action_executor = _require(self._state.action_executor, "action executor is required")

        task_agent_manager = TaskAgentManager(
            create_chat_agent=create_chat_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                memory=memory,
                other_memory=other_memory,
                unified_memory=unified_memory,
                memory_integration=memory_integration,
                scenario_prompts_store=scenario_prompts_store,
                config=config,
            ),
            create_default_agent=create_default_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                config=config,
                unified_memory=unified_memory,
            ),
            idle_ttl_seconds=config.agent.runtime.task_agent_manager_idle_ttl_seconds,
            max_dynamic_instances=config.agent.runtime.task_agent_manager_max_dynamic_instances,
        )
        router_agent = RouterAgent(
            sensor_hub=sensor_hub,
            task_agent_manager=task_agent_manager,
            batch_size=max(8, config.agent.num_task_agents * 4),
            poll_timeout_seconds=0.2,
            restart_backoff_seconds=config.agent.runtime.router_restart_backoff_seconds,
        )

        self._state.task_agent_manager = task_agent_manager
        self._state.agent_runtime = AgentRuntime(
            sensor_hub=sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )
        await self._state.agent_runtime.start()
        logger.info("AgentRuntime started (L11)")

    async def shutdown(self) -> None:
        if self._state.agent_runtime is not None:
            await self._state.agent_runtime.stop()
            self._state.agent_runtime = None
        self._state.task_agent_manager = None


class TimelineModule(LifecycleModule):
    """Initialize TimelineService and timeline scheduler contributor (L12 - Timeline layer)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_timeline",
            dependencies=("runtime_memory", "runtime_plugin_system", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        unified_memory = _require(self._state.unified_memory, "unified memory is required")

        self._state.timeline_service = TimelineService(unified_memory)
        logger.info("TimelineService initialized (L12)")

    async def shutdown(self) -> None:
        self._state.timeline_service = None


class SchedulerModule(LifecycleModule):
    """Initialize runtime scheduler and coordinate schedule contributors."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_scheduler",
            dependencies=("runtime_agent_core", "runtime_timeline", "runtime_plugin_system", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._state = state
        self._agent_contrib: AgentSchedulerContrib | None = None
        self._action_contrib: ActionSchedulerContrib | None = None

    async def init(self) -> None:
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")
        task_agent_manager = _require(self._state.task_agent_manager, "task agent manager is required")
        action_executor = _require(self._state.action_executor, "action executor is required")
        timeline_service = _require(self._state.timeline_service, "timeline service is required")

        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )

        # Timeline layer contributor
        timeline_contrib = TimelineSchedulerContrib(
            scheduler_service=scheduler_service,
            sensor_registry=get_sensor_registry(),
            plugin_manager=get_plugin_manager(),
            timeline_service=timeline_service,
            runtime_paths=runtime_paths,
            get_config=get_config,
        )
        await timeline_contrib.register_schedules(scheduler_service)

        # Agent layer contributor (AGENT_TASK handler)
        self._agent_contrib = AgentSchedulerContrib(
            scheduler_service=scheduler_service,
            task_agent_manager=task_agent_manager,
        )
        await self._agent_contrib.register_schedules(scheduler_service)

        # Action executor contributor (ACTION_DISPATCH handler)
        self._action_contrib = ActionSchedulerContrib(
            scheduler_service=scheduler_service,
            action_registry=get_action_registry(),
            action_executor=action_executor,
        )
        await self._action_contrib.register_schedules(scheduler_service)

        # Legacy bootstrap kept for backward compatibility
        scheduler_bootstrap = SchedulerBootstrap(
            scheduler_service=scheduler_service,
            action_registry=get_action_registry(),
            runtime_paths=runtime_paths,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )

        await scheduler_service.start()
        set_scheduler_runtime(scheduler_service, scheduler_bootstrap)
        set_timeline_scheduler_contrib(timeline_contrib)

        self._state.scheduler_service = scheduler_service
        self._state.scheduler_bootstrap = scheduler_bootstrap
        logger.info("Scheduler service started with contributors: timeline, agent, action")

    async def shutdown(self) -> None:
        if self._state.scheduler_service is not None:
            await self._state.scheduler_service.stop()
        self._state.scheduler_service = None
        self._state.scheduler_bootstrap = None
        set_scheduler_runtime(None, None)
        set_timeline_scheduler_contrib(None)


class RuntimeExportsModule(LifecycleModule):
    """Expose initialized runtime objects to DI and API bindings."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_exports",
            dependencies=("runtime_agent_core", "runtime_memory", "runtime_message_bus", "runtime_scheduler", "runtime_llm"),
        )
        self._state = state

    async def init(self) -> None:
        message_bus = _require(self._state.message_bus, "message bus is required")
        agent_runtime = _require(self._state.agent_runtime, "agent runtime is required")
        memory_integration = _require(self._state.memory_integration, "memory integration is required")
        unified_memory = _require(self._state.unified_memory, "unified memory is required")

        container = get_container()
        container.message_bus.override(providers.Object(message_bus))
        container.agent_runtime.override(providers.Object(agent_runtime))
        container.memory_integration.override(providers.Object(memory_integration))
        container.unified_memory.override(providers.Object(unified_memory))

        if self._state.scheduler_service is not None:
            container.scheduler_service.override(providers.Object(self._state.scheduler_service))
        if self._state.scenario_llm_pool is not None:
            container.scenario_llm_pool.override(providers.Object(self._state.scenario_llm_pool))

        logger.info("DI container providers registered")

        from .services.message_bus import set_message_bus

        set_message_bus(message_bus)

    async def shutdown(self) -> None:
        container = get_container()
        container.message_bus.reset_override()
        container.agent_runtime.reset_override()
        container.memory_integration.reset_override()
        container.unified_memory.reset_override()
        container.scheduler_service.reset_override()
        container.scenario_llm_pool.reset_override()


class OtherDependenciesModule(LifecycleModule):
    """Initialize remaining runtime dependencies (maintenance daemon)."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_other_dependencies",
            dependencies=("runtime_scheduler", "runtime_message_bus", "runtime_configuration"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        message_bus = _require(self._state.message_bus, "message bus is required")

        maintenance_config = MaintenanceConfig(
            enabled=config.agent.maintenance.enabled,
            interval_seconds=config.agent.maintenance.interval_seconds,
            message_cleanup=config.agent.maintenance.message_cleanup,
            message_retain_hours=config.agent.maintenance.message_retain_hours,
            message_cleanup_batch_size=config.agent.maintenance.message_cleanup_batch_size,
            health_check=config.agent.maintenance.health_check,
            log_rotation_check=config.agent.maintenance.log_rotation_check,
        )
        self._state.maintenance_daemon = MaintenanceDaemon(
            message_bus=message_bus,
            config=maintenance_config,
        )
        await self._state.maintenance_daemon.start()
        set_maintenance_daemon(self._state.maintenance_daemon)
        logger.info("Maintenance daemon started")

    async def shutdown(self) -> None:
        if self._state.maintenance_daemon is not None:
            await self._state.maintenance_daemon.stop()
            self._state.maintenance_daemon = None
        set_maintenance_daemon(None)


def build_runtime_modules(state: RuntimeBootstrapState) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules.

    Order aligns with the 15-layer architecture:
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
    L14 RuntimeExportsModule      - DI container exports
    L15 OtherDependenciesModule   - Maintenance daemon
    """
    return [
        CoreDependenciesModule(state),      # L1
        ConfigurationModule(state),         # L2
        MessageBusModule(state),            # L3
        PluginSystemModule(state),          # L4
        LLMRuntimeModule(state),            # L5
        MemoryStoreModule(state),           # L6
        ToolsModule(state),                 # L7
        PersonalityModule(state),           # L8
        SensorExecutorModule(state),        # L9
        ContextModule(state),               # L10
        AgentRuntimeModule(state),          # L11
        TimelineModule(state),              # L12
        SchedulerModule(state),             # L13 (scheduler engine)
        RuntimeExportsModule(state),        # L14
        OtherDependenciesModule(state),     # L15
    ]
