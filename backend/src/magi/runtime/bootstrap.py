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
    DailyReportTaskAgent,
    DefaultTaskAgent,
    MemoryDigestTaskAgent,
)
from ..events.sqlite_backend import SQLiteMessageBackend
from ..memory.self_memory import SelfMemory
from ..memory.other_memory import OtherMemory
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationModule, MemoryIntegrationConfig
from ..llm import create_llm_adapter
from ..utils.runtime import get_runtime_paths, init_runtime_data
from ..core.logger import get_logger

logger = get_logger(__name__)

_memory_integration: MemoryIntegrationModule | None = None
_message_bus: SQLiteMessageBackend | None = None
_agent_runtime: AgentRuntime | None = None


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


def _create_llm_adapter(config: AppConfig):
    llm_adapter = create_llm_adapter(config)
    logger.info(
        "Creating LLM adapter | Provider: %s | Model: %s",
        getattr(llm_adapter, "provider_name", "unknown"),
        getattr(llm_adapter, "model_name", "unknown"),
    )
    return llm_adapter


async def initialize_chat_agent():
    """Initialize agent runtime on application startup."""
    global _memory_integration, _message_bus, _agent_runtime

    if _agent_runtime is not None:
        logger.warning("Agent runtime already initialized")
        return

    config = get_config()
    if not config.llm.api_key:
        logger.warning("=" * 60)
        logger.warning("LLM_API_KEY not set!")
        logger.warning("Agent runtime will NOT be initialized.")
        logger.warning("Set LLM_API_KEY environment variable to enable AI responses.")
        logger.warning("=" * 60)
        return

    try:
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"Runtime directory: {runtime_paths.base_dir}")
        logger.info("Initializing Agent Runtime...")

        llm_adapter = _create_llm_adapter(config)
        _message_bus = SQLiteMessageBackend(db_path=str(runtime_paths.events_db_path))
        await _message_bus.start()
        logger.info("MessageBus started")

        task_database = TaskDatabase(db_path=str(runtime_paths.data_dir / "tasks.db"))

        current_personality = "default"
        if _bindings.get_current_personality is not None:
            try:
                current_personality = _bindings.get_current_personality() or "default"
            except Exception as exc:
                logger.warning(f"Failed to get current personality from bindings: {exc}")
        logger.info(f"Current personality: {current_personality}")

        memory = SelfMemory(
            personality_name=current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        other_memory = OtherMemory()

        unified_memory = UnifiedMemoryStore(
            db_path=str(runtime_paths.events_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={
                "backend": config.agent.memory.embedding.backend.value,
                "local_model": config.agent.memory.embedding.local_model,
                "local_dimension": config.agent.memory.embedding.local_dimension,
            },
            llm_adapter=llm_adapter,
        )
        await unified_memory.initialize()
        logger.info("UnifiedMemoryStore initialized (L1-L5)")

        memory_integration_config = MemoryIntegrationConfig(
            enable_l1_raw=config.agent.memory.enable_l1_raw,
            enable_l2_relations=config.agent.memory.enable_l2_relations,
            enable_l3_embeddings=config.agent.memory.enable_l3_embeddings,
            enable_l4_summaries=config.agent.memory.enable_l4_summaries,
            enable_l5_capabilities=config.agent.memory.enable_l5_capabilities,
            async_embeddings=config.agent.memory.async_embeddings,
            auto_extract_relations=config.agent.memory.auto_extract_relations,
            summary_interval_minutes=config.agent.memory.summary_interval_minutes,
        )
        _memory_integration = MemoryIntegrationModule(
            unified_memory=unified_memory,
            message_bus=_message_bus,
            config=memory_integration_config,
        )
        await _memory_integration.start()
        logger.info("MemoryIntegrationModule started")

        sensor_hub = SensorHub(message_bus=_message_bus)
        action_executor = ActionExecutor(message_bus=_message_bus)
        task_agent_manager = TaskAgentManager(
            create_chat_agent=lambda agent_id: ChatTaskAgent(
                agent_id=agent_id,
                llm_adapter=llm_adapter,
                memory=memory,
                other_memory=other_memory,
                unified_memory=unified_memory,
                memory_integration=_memory_integration,
            ),
            create_memory_digest_agent=lambda agent_id: MemoryDigestTaskAgent(agent_id),
            create_daily_report_agent=lambda agent_id: DailyReportTaskAgent(agent_id),
            create_default_agent=lambda agent_type, agent_id: DefaultTaskAgent(agent_type, agent_id),
        )
        router_agent = RouterAgent(
            sensor_hub=sensor_hub,
            task_agent_manager=task_agent_manager,
            batch_size=max(8, config.agent.num_task_agents * 4),
            poll_timeout_seconds=0.2,
        )
        _agent_runtime = AgentRuntime(
            sensor_hub=sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )

        await task_database._init_db()
        await _agent_runtime.start()

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

        logger.info("Agent runtime initialized successfully")

    except Exception as exc:
        logger.error(f"Failed to initialize agent runtime: {exc}", exc_info=True)
        raise


async def shutdown_chat_agent():
    """Shutdown agent runtime."""
    global _memory_integration, _message_bus, _agent_runtime

    try:
        if _agent_runtime is not None:
            await _agent_runtime.stop()
            _agent_runtime = None

        if _memory_integration is not None:
            await _memory_integration.stop()
            _memory_integration = None

        if _message_bus is not None:
            await _message_bus.stop()
            _message_bus = None

        logger.info("Agent runtime stopped")
    except Exception as exc:
        logger.error(f"Failed to stop agent runtime: {exc}", exc_info=True)
