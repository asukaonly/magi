"""
Agent runtime bootstrap and lifecycle wiring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..config import get_config, AppConfig
from ..core.container import get_container
from dependency_injector import providers
from ..core.task_database import TaskDatabase
from ..core.runtime import (
    ActionExecutor,
    AgentRuntime,
    RouterAgent,
    SensorHub,
    TaskAgentManager,
)
from ..agent.task_agents import (
    ChatTaskAgent,
    DefaultTaskAgent,
    ExploreTaskAgent,
    TimelineTaskAgent,
)
from ..core.runtime.types import TaskAgentType
from ..events.sqlite_backend import SQLiteMessageBackend
from ..memory.self_memory import SelfMemory
from ..memory.other_memory import OtherMemory
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationModule, MemoryIntegrationConfig
from ..memory.scenario_prompts import ScenarioPromptsStore, initialize_default_prompts
from ..llm import LLMScenario, ScenarioLLMPool, create_llm_adapter, get_llm_usage_store
from ..llm.usage_events import configure_llm_usage_event_publisher
from ..plugins import get_action_registry, get_plugin_manager, get_sensor_registry, initialize_plugin_manager
from ..scheduler import SchedulerBootstrap, SchedulerService, set_scheduler_runtime
from ..timeline.service import TimelineService
from ..utils.runtime import get_runtime_paths, Runtimepaths, init_runtime_data
from ..core.logger import get_logger
from ..core.database_initializer import DatabaseInitializer, set_database_initializer
from .maintenance import MaintenanceDaemon, MaintenanceConfig, set_maintenance_daemon

logger = get_logger(__name__)

_memory_integration: MemoryIntegrationModule | None = None
_message_bus: SQLiteMessageBackend | None = None
_agent_runtime: AgentRuntime | None = None
_maintenance_daemon: MaintenanceDaemon | None = None
_scenario_prompts_store: ScenarioPromptsStore | None = None
_scenario_llm_pool: ScenarioLLMPool | None = None
_llm_usage_store = None
_scheduler_service: SchedulerService | None = None
_scheduler_bootstrap: SchedulerBootstrap | None = None


def _get_nested_setting(payload: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    return current


def _resolve_timeline_contribution(source_type: str):
    registry = get_sensor_registry()
    return registry.resolve_domain_sensor("timeline", source_type)


def _build_timeline_handler(
    config: AppConfig,
    unified_memory: UnifiedMemoryStore,
) -> Callable[[dict[str, Any]], Any]:
    service = TimelineService(unified_memory)

    async def _handle_timeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
        source_type = str(payload.get("source_type") or "").strip()
        if not config.timeline.enabled:
            return {"handled": False, "reason": "timeline_disabled"}
        resolved = _resolve_timeline_contribution(source_type)
        if resolved is None:
            return {"handled": False, "reason": "unsupported_source", "source_type": source_type}
        plugin_id, sensor_id, sensor, spec = resolved
        package_state = get_plugin_manager().get_package(plugin_id)
        current_settings = package_state.current_settings if package_state is not None else {}
        sensor_settings_path = f"sensors.{source_type}"
        default_settings = dict(spec.metadata.get("default_settings", {}))
        if not bool(
            _get_nested_setting(
                current_settings,
                f"{sensor_settings_path}.enabled",
                default_settings.get("enabled", True),
            )
        ):
            return {"handled": False, "reason": "source_disabled", "source_type": source_type}

        event = await sensor.build_timeline_event(payload)
        extracted = await sensor.extract_candidates(payload)
        event.entities = list(extracted.get("entities", []))
        event.tags = list(dict.fromkeys([*event.tags, *list(extracted.get("tags", []))]))
        event.provenance.update(
            {
                "correlation_id": str(payload.get("correlation_id") or ""),
                "timeline_task_agent_id": str(payload.get("target_task_agent_id") or ""),
            }
        )
        await service.upsert_event(
            event,
            relation_candidates=list(extracted.get("relation_candidates", [])),
            allowed_edge_whitelist=[
                str(edge_type)
                for edge_type in _get_nested_setting(
                    current_settings,
                    f"{sensor_settings_path}.edge_whitelist",
                    default_settings.get("edge_whitelist", []),
                )
            ],
        )
        return {"handled": True, "event_id": event.event_id, "source_type": source_type}

    return _handle_timeline_payload


@dataclass
class RuntimeBindings:
    """External callbacks used to bridge runtime with upper layers."""

    get_current_personality: Optional[Callable[[], str]] = None
    set_message_bus: Optional[Callable[[Any], None]] = None
    init_skills_module: Optional[Callable[[Any], None]] = None


_bindings = RuntimeBindings()


def configure_runtime_bindings(bindings: RuntimeBindings | None = None) -> None:
    """Configure runtime bridge callbacks from outer app entrypoint."""
    global _bindings
    _bindings = bindings or RuntimeBindings()


def get_master_agent():
    """Backward-compatible API: runtime mode has no MasterAgent instance."""
    return None


def get_memory_integration() -> MemoryIntegrationModule:
    """Get memory integration module."""
    # Try container first
    try:
        container = get_container()
        instance = container.memory_integration()
        if instance is not None and not isinstance(instance, object) or (
            isinstance(instance, object) and type(instance).__name__ != "object"
        ):
            return instance
    except Exception:
        pass
    # Fallback to global
    if _memory_integration is None:
        raise RuntimeError("MemoryIntegrationModule not initialized. Call initialize_chat_agent() first.")
    return _memory_integration


def get_unified_memory() -> UnifiedMemoryStore:
    """Get unified memory store."""
    return get_memory_integration().unified_memory


def get_agent_runtime() -> AgentRuntime:
    """Get agent runtime."""
    # Try container first
    try:
        container = get_container()
        instance = container.agent_runtime()
        if instance is not None and not isinstance(instance, object) or (
            isinstance(instance, object) and type(instance).__name__ != "object"
        ):
            return instance
    except Exception:
        pass
    # Fallback to global
    if _agent_runtime is None:
        raise RuntimeError("AgentRuntime not initialized. Call initialize_chat_agent() first.")
    return _agent_runtime


def get_scheduler_service() -> SchedulerService:
    """Get the active scheduler service."""

    if _scheduler_service is None:
        raise RuntimeError("SchedulerService not initialized. Call initialize_chat_agent() first.")
    return _scheduler_service


def _create_scenario_llm_pool(config: AppConfig) -> ScenarioLLMPool:
    return ScenarioLLMPool(config=config, adapter_factory=create_llm_adapter)


def _create_core_llm_adapter(llm_pool: ScenarioLLMPool):
    llm_adapter = llm_pool.get(LLMScenario.CORE)
    logger.info(
        "Creating LLM adapter | Provider: %s | Model: %s",
        getattr(llm_adapter, "provider_name", "unknown"),
        getattr(llm_adapter, "model_name", "unknown"),
    )
    return llm_adapter


def refresh_runtime_llm_config(config: AppConfig | None = None) -> None:
    """Refresh cached runtime LLM adapters after configuration changes."""
    global _scenario_llm_pool

    if _scenario_llm_pool is None:
        return

    next_config = config or get_config()
    _scenario_llm_pool.refresh(next_config)
    logger.info("Runtime LLM pool refreshed after configuration update")


async def initialize_chat_agent():
    """Initialize agent runtime on application startup."""
    global _memory_integration, _message_bus, _agent_runtime, _llm_usage_store, _scenario_llm_pool
    global _scheduler_service, _scheduler_bootstrap

    if _agent_runtime is not None:
        logger.warning("Agent runtime already initialized")
        return

    config = get_config()
    try:
        _scenario_llm_pool = _create_scenario_llm_pool(config)
        _scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
        llm_adapter = _create_core_llm_adapter(_scenario_llm_pool)
    except Exception as exc:
        logger.warning("=" * 60)
        logger.warning("LLM runtime configuration is incomplete: %s", exc)
        logger.warning("Agent runtime will NOT be initialized.")
        logger.warning("Configure an enabled core provider and model selection to enable AI responses.")
        logger.warning("=" * 60)
        return

    try:
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"Runtime directory: {runtime_paths.base_dir}")
        logger.info("Initializing Agent Runtime...")

        # 统一初始化所有数据库表
        current_personality = "default"
        if _bindings.get_current_personality is not None:
            try:
                current_personality = _bindings.get_current_personality() or "default"
            except Exception as exc:
                logger.warning(f"Failed to get current personality from bindings: {exc}")

        db_initializer = DatabaseInitializer(data_dir=runtime_paths.data_dir)
        await db_initializer.initialize_all()
        await db_initializer.insert_default_data(persona_name=current_personality)
        set_database_initializer(db_initializer)
        logger.info("Database initialization completed")

        initialize_plugin_manager(force=True)

        # Ensure built-in tools are loaded and inject runtime dependencies for agent tool.
        from ..tools import tool_registry

        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(llm_adapter=llm_adapter, tool_registry_instance=tool_registry)
            logger.info("Agent tool configured with runtime LLM adapter")

        _message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.events_db_path),
            max_queue_size=config.agent.message_bus.max_queue_size,
            num_workers=config.agent.message_bus.num_workers,
            broadcast_max_concurrency=config.agent.message_bus.broadcast_max_concurrency,
            handler_timeout_seconds=config.agent.message_bus.handler_timeout_seconds,
            max_retries=config.agent.message_bus.max_retries,
            retry_delay_seconds=config.agent.message_bus.retry_delay_seconds,
        )
        await _message_bus.start()
        logger.info("MessageBus started")

        configure_llm_usage_event_publisher(_message_bus)
        _llm_usage_store = get_llm_usage_store()
        await _llm_usage_store.start(_message_bus)
        logger.info("LLM usage store started")

        task_database = TaskDatabase(db_path=str(runtime_paths.data_dir / "tasks.db"))

        memory = SelfMemory(
            personality_name=current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        other_memory = OtherMemory()

        unified_memory = UnifiedMemoryStore(
            db_path=str(runtime_paths.events_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_l0=config.agent.memory.enable_l0,
            enable_l1=config.agent.memory.enable_l1,
            enable_l2=config.agent.memory.enable_l2,
            enable_l3=config.agent.memory.enable_l3,
            enable_l4=config.agent.memory.enable_l4,
            l0_checkpoint_interval_seconds=config.agent.memory.l0_checkpoint_interval_seconds,
        )
        await unified_memory.initialize()
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
        _memory_integration = MemoryIntegrationModule(
            unified_memory=unified_memory,
            message_bus=_message_bus,
            config=memory_integration_config,
        )
        await _memory_integration.start()
        logger.info("MemoryIntegrationModule started")

        # Scenario prompts store (table already initialized by DatabaseInitializer)
        global _scenario_prompts_store
        _scenario_prompts_store = ScenarioPromptsStore(
            db_path=str(runtime_paths.scenario_prompts_db_path)
        )
        await _scenario_prompts_store.init()
        await initialize_default_prompts(_scenario_prompts_store, persona_name=current_personality)

        sensor_hub = SensorHub(message_bus=_message_bus)
        action_executor = ActionExecutor(message_bus=_message_bus)
        task_agent_manager = TaskAgentManager(
            create_chat_agent=lambda agent_id: ChatTaskAgent(
                agent_id=agent_id,
                llm_adapter=llm_adapter,
                llm_pool=_scenario_llm_pool,
                memory=memory,
                other_memory=other_memory,
                unified_memory=unified_memory,
                memory_integration=_memory_integration,
                history_cache_max_sessions=config.agent.runtime.chat_history_cache_max_sessions,
                history_fetch_limit=config.agent.runtime.chat_history_fetch_limit,
                scenario_prompts_store=_scenario_prompts_store,
            ),
            create_default_agent=lambda agent_type, agent_id: (
                ExploreTaskAgent(agent_id=agent_id, llm_adapter=llm_adapter, llm_pool=_scenario_llm_pool)
                if agent_type == TaskAgentType.EXPLORE.value
                else TimelineTaskAgent(
                    agent_id=agent_id,
                    timeline_handler=_build_timeline_handler(config, unified_memory),
                    config=config,
                    unified_memory=unified_memory,
                )
                if agent_type == TaskAgentType.TIMELINE.value
                else DefaultTaskAgent(agent_type, agent_id)
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
        _agent_runtime = AgentRuntime(
            sensor_hub=sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )

        await _agent_runtime.start()

        timeline_service = TimelineService(unified_memory)
        _scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )
        _scheduler_bootstrap = SchedulerBootstrap(
            scheduler_service=_scheduler_service,
            sensor_registry=get_sensor_registry(),
            action_registry=get_action_registry(),
            plugin_manager=get_plugin_manager(),
            timeline_service=timeline_service,
            runtime_paths=runtime_paths,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
            get_config=get_config,
        )
        _scheduler_bootstrap.register_handlers()
        await _scheduler_service.start()
        await _scheduler_bootstrap.sync_timeline_sensor_schedules()
        set_scheduler_runtime(_scheduler_service, _scheduler_bootstrap)
        logger.info("Scheduler service started")

        # Register services in the DI container
        container = get_container()
        container.message_bus.override(providers.Object(_message_bus))
        container.agent_runtime.override(providers.Object(_agent_runtime))
        container.memory_integration.override(providers.Object(_memory_integration))
        container.unified_memory.override(providers.Object(unified_memory))
        logger.info("DI container providers registered")

        if _bindings.set_message_bus is not None:
            _bindings.set_message_bus(_message_bus)

        if config.features.enable_skills and _bindings.init_skills_module is not None:
            _bindings.init_skills_module(llm_adapter)
            logger.info("Skills module initialized")

        # Start maintenance daemon
        maintenance_config = MaintenanceConfig(
            enabled=config.agent.maintenance.enabled,
            interval_seconds=config.agent.maintenance.interval_seconds,
            message_cleanup=config.agent.maintenance.message_cleanup,
            message_retain_hours=config.agent.maintenance.message_retain_hours,
            message_cleanup_batch_size=config.agent.maintenance.message_cleanup_batch_size,
            health_check=config.agent.maintenance.health_check,
            log_rotation_check=config.agent.maintenance.log_rotation_check,
        )
        global _maintenance_daemon
        _maintenance_daemon = MaintenanceDaemon(
            message_bus=_message_bus,
            config=maintenance_config,
        )
        await _maintenance_daemon.start()
        set_maintenance_daemon(_maintenance_daemon)
        logger.info("Maintenance daemon started")

        logger.info("Agent runtime initialized successfully")

    except Exception as exc:
        logger.error(f"Failed to initialize agent runtime: {exc}", exc_info=True)
        raise


async def shutdown_chat_agent():
    """Shutdown agent runtime."""
    global _memory_integration, _message_bus, _agent_runtime, _maintenance_daemon, _llm_usage_store
    global _scenario_llm_pool
    global _scheduler_service, _scheduler_bootstrap

    try:
        if _scheduler_service is not None:
            await _scheduler_service.stop()
            _scheduler_service = None
            _scheduler_bootstrap = None
            set_scheduler_runtime(None, None)

        # Stop maintenance daemon first
        if _maintenance_daemon is not None:
            await _maintenance_daemon.stop()
            _maintenance_daemon = None

        if _llm_usage_store is not None:
            await _llm_usage_store.stop()
            _llm_usage_store = None
        configure_llm_usage_event_publisher(None)

        if _agent_runtime is not None:
            await _agent_runtime.stop()
            _agent_runtime = None

        if _memory_integration is not None:
            await _memory_integration.stop()
            _memory_integration = None

        if _message_bus is not None:
            await _message_bus.stop()
            _message_bus = None

        _scenario_llm_pool = None

        logger.info("Agent runtime stopped")
    except Exception as exc:
        logger.error(f"Failed to stop agent runtime: {exc}", exc_info=True)
