"""Runtime lifecycle modules and shared bootstrap state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from dependency_injector import providers

from ..agent.task_agents.factory import create_chat_agent_factory, create_default_agent_factory
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
from ..events.sqlite_backend import SQLiteMessageBackend
from ..llm import LLMScenario, ScenarioLLMPool, get_llm_usage_store
from ..llm.factory import create_core_llm_adapter, create_scenario_llm_pool
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
from ..timeline.service import TimelineService
from ..utils.runtime import RuntimePaths, get_runtime_paths, init_runtime_data
from .lifecycle import LifecycleModule
from .maintenance import MaintenanceConfig, MaintenanceDaemon, set_maintenance_daemon

logger = get_logger(__name__)

REQUIRED_RUNTIME_LLM_SCENARIOS = (
    LLMScenario.CONTEXT_DECIDER.value,
    LLMScenario.CORE.value,
)


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

    bindings: Any
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
    agent_runtime: AgentRuntime | None = None
    action_executor: ActionExecutor | None = None
    task_agent_manager: TaskAgentManager | None = None
    scheduler_service: SchedulerService | None = None
    scheduler_bootstrap: SchedulerBootstrap | None = None
    maintenance_daemon: MaintenanceDaemon | None = None
    db_initializer: DatabaseInitializer | None = None


def _require(value: Any, message: str) -> Any:
    if value is None:
        raise RuntimeError(message)
    return value


def _is_llm_selection_pending(config: AppConfig) -> bool:
    for scenario_name in REQUIRED_RUNTIME_LLM_SCENARIOS:
        selection = config.llm.selections.get(scenario_name)
        if selection is None:
            return True
        if not str(selection.provider_id or "").strip():
            return True
        if not str(selection.model or "").strip():
            return True
    return False





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
        get_current_personality = getattr(self._state.bindings, "get_current_personality", None)
        if get_current_personality is not None:
            try:
                current_personality = get_current_personality() or "default"
            except Exception as exc:
                logger.warning("Failed to get current personality from bindings: %s", exc)
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
                pending_selection=_is_llm_selection_pending(config),
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

        init_skills_module = getattr(self._state.bindings, "init_skills_module", None)
        if config.features.enable_skills and init_skills_module is not None:
            init_skills_module(llm_adapter)
            logger.info("Skills module initialized")


class AgentRuntimeCoreModule(LifecycleModule):
    """Initialize and run SensorHub/Router/TaskAgentManager/AgentRuntime."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_agent_core",
            dependencies=("runtime_context", "runtime_personality", "runtime_memory", "runtime_llm", "runtime_message_bus", "runtime_configuration"),
        )
        self._state = state

    async def init(self) -> None:
        config = _require(self._state.config, "runtime config is required")
        llm_adapter = _require(self._state.llm_adapter, "llm adapter is required")
        llm_pool = _require(self._state.scenario_llm_pool, "llm pool is required")
        message_bus = _require(self._state.message_bus, "message bus is required")
        memory = _require(self._state.self_memory, "self memory is required")
        other_memory = _require(self._state.other_memory, "other memory is required")
        unified_memory = _require(self._state.unified_memory, "unified memory is required")
        memory_integration = _require(self._state.memory_integration, "memory integration is required")
        scenario_prompts_store = _require(self._state.scenario_prompts_store, "scenario prompts store is required")

        sensor_hub = SensorHub(message_bus=message_bus)
        action_executor = ActionExecutor(message_bus=message_bus)
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

        self._state.action_executor = action_executor
        self._state.task_agent_manager = task_agent_manager
        self._state.agent_runtime = AgentRuntime(
            sensor_hub=sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )
        await self._state.agent_runtime.start()

    async def shutdown(self) -> None:
        if self._state.agent_runtime is not None:
            await self._state.agent_runtime.stop()
            self._state.agent_runtime = None
        self._state.task_agent_manager = None
        self._state.action_executor = None


class SchedulerModule(LifecycleModule):
    """Initialize runtime scheduler and timeline sync hooks."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_scheduler",
            dependencies=("runtime_agent_core", "runtime_memory", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._state = state

    async def init(self) -> None:
        runtime_paths = _require(self._state.runtime_paths, "runtime paths are required")
        unified_memory = _require(self._state.unified_memory, "unified memory is required")
        task_agent_manager = _require(self._state.task_agent_manager, "task agent manager is required")
        action_executor = _require(self._state.action_executor, "action executor is required")

        timeline_service = TimelineService(unified_memory)
        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )
        scheduler_bootstrap = SchedulerBootstrap(
            scheduler_service=scheduler_service,
            sensor_registry=get_sensor_registry(),
            action_registry=get_action_registry(),
            plugin_manager=get_plugin_manager(),
            timeline_service=timeline_service,
            runtime_paths=runtime_paths,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
            get_config=get_config,
        )
        scheduler_bootstrap.register_handlers()
        await scheduler_service.start()
        await scheduler_bootstrap.sync_timeline_sensor_schedules()
        set_scheduler_runtime(scheduler_service, scheduler_bootstrap)

        self._state.scheduler_service = scheduler_service
        self._state.scheduler_bootstrap = scheduler_bootstrap
        logger.info("Scheduler service started")

    async def shutdown(self) -> None:
        if self._state.scheduler_service is not None:
            await self._state.scheduler_service.stop()
        self._state.scheduler_service = None
        self._state.scheduler_bootstrap = None
        set_scheduler_runtime(None, None)


class RuntimeExportsModule(LifecycleModule):
    """Expose initialized runtime objects to DI and API bindings."""

    def __init__(self, state: RuntimeBootstrapState):
        super().__init__(
            name="runtime_exports",
            dependencies=("runtime_agent_core", "runtime_memory", "runtime_message_bus"),
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
        logger.info("DI container providers registered")

        set_message_bus = getattr(self._state.bindings, "set_message_bus", None)
        if set_message_bus is not None:
            set_message_bus(message_bus)


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
    """Build ordered runtime lifecycle modules."""
    return [
        CoreDependenciesModule(state),
        ConfigurationModule(state),
        MessageBusModule(state),
        PluginSystemModule(state),
        LLMRuntimeModule(state),
        MemoryStoreModule(state),
        ToolsModule(state),
        PersonalityModule(state),
        ContextModule(state),
        AgentRuntimeCoreModule(state),
        SchedulerModule(state),
        RuntimeExportsModule(state),
        OtherDependenciesModule(state),
    ]
