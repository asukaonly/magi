"""
Agent Initialize Module

Initialize agents and register sensors on application startup.

Supported modes:
- Three-layer architecture: MasterAgent -> TaskAgent -> ChatWorkerAgent
- Legacy mode: ChatAgent (fallback)
"""
import logging
from ..config import get_config, AppConfig, LLMProvider
from ..core.agent import AgentConfig
from ..core.master_agent import MasterAgent
from ..core.task_agent import TaskAgent
from ..core.task_database import TaskDatabase
from ..events.sqlite_backend import SQLiteMessageBackend
from ..agent.chat import ChatAgent
from ..awareness.sensors import UserMessageSensor
from ..memory.self_memory import SelfMemory
from ..memory.other_memory import OtherMemory
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationModule, MemoryIntegrationConfig
from ..tools.registry import tool_registry
from ..utils.runtime import get_runtime_paths, init_runtime_data

logger = logging.getLogger(__name__)

# Global variables for three-layer architecture
_master_agent: MasterAgent = None
_task_agents: list = []

# Legacy ChatAgent (fallback mode)
_chat_agent: ChatAgent = None

# Memory Integration Module instance
_memory_integration: MemoryIntegrationModule = None

# Message bus (shared)
_message_bus: SQLiteMessageBackend = None


def get_chat_agent() -> ChatAgent:
    """Get ChatAgent instance (for backward compatibility)."""
    global _chat_agent
    return _chat_agent


def get_master_agent() -> MasterAgent:
    """Get MasterAgent instance."""
    global _master_agent
    return _master_agent


def get_memory_integration() -> MemoryIntegrationModule:
    """Get MemoryIntegrationModule instance."""
    global _memory_integration
    if _memory_integration is None:
        raise RuntimeError("MemoryIntegrationModule not initialized. Call initialize_chat_agent() first.")
    return _memory_integration


def get_unified_memory() -> UnifiedMemoryStore:
    """Get UnifiedMemoryStore instance."""
    return get_memory_integration().unified_memory


def _create_llm_adapter(config: AppConfig):
    """
    Create LLM adapter from configuration.

    Args:
        config: Application configuration

    Returns:
        LLMAdapter instance
    """
    llm_config = config.agent.llm
    provider = llm_config.provider.value  # Get string value from enum
    api_key = llm_config.api_key
    base_url = llm_config.base_url
    model = llm_config.model

    if not api_key:
        raise ValueError("LLM_API_KEY must be set")

    logger.info(f"Creating LLM adapter | Provider: {provider} | Model: {model} | Base URL: {base_url or 'default'}")

    if provider == "anthropic":
        from ..llm.anthropic import AnthropicAdapter
        return AnthropicAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    elif provider in ("openai", "glm"):
        from ..llm.openai import OpenAIAdapter
        return OpenAIAdapter(
            api_key=api_key,
            model=model,
            provider=provider,
            base_url=base_url,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}. Supported: 'openai', 'anthropic', 'glm'")


async def initialize_chat_agent():
    """
    Initialize agent on application startup.

    Mode is determined by config.features.enable_three_layer_arch.
    """
    config = get_config()

    if config.features.enable_three_layer_arch:
        await _initialize_three_layer_architecture(config)
    else:
        await _initialize_chat_agent_legacy(config)


async def _initialize_three_layer_architecture(config: AppConfig):
    """
    Initialize three-layer architecture.

    Architecture:
    - MasterAgent (Layer 1): Task recognition and dispatch
    - TaskAgent x N (Layer 2): Task orchestration
    - ChatWorkerAgent (Layer 3): Task execution
    """
    global _master_agent, _task_agents, _memory_integration, _message_bus

    if _master_agent is not None:
        logger.warning("Three-layer architecture already initialized")
        return

    try:
        # Check API key
        if not config.agent.llm.api_key:
            logger.warning("=" * 60)
            logger.warning("LLM_API_KEY not set!")
            logger.warning("Agent will NOT be initialized.")
            logger.warning("Set LLM_API_KEY environment variable to enable AI responses.")
            logger.warning("=" * 60)
            return

        # Initialize runtime data directory
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"Runtime directory: {runtime_paths.base_dir}")
        logger.info("Initializing Three-Layer Architecture...")

        # Create LLM adapter
        llm_adapter = _create_llm_adapter(config)

        # Create message bus
        _message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.events_db_path),
        )
        await _message_bus.start()
        logger.info("MessageBus started")

        # Create task database
        task_database = TaskDatabase(
            db_path=str(runtime_paths.data_dir / "tasks.db"),
        )
        logger.info("TaskDatabase created")

        # Get current personality name
        from ..api.routers.personality import get_current_personality
        current_personality = get_current_personality()
        logger.info(f"Current personality: {current_personality}")

        # Create memory systems
        memory = SelfMemory(
            personality_name=current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        logger.info("SelfMemory initialized")

        other_memory = OtherMemory()
        logger.info("OtherMemory initialized")

        unified_memory = UnifiedMemoryStore(
            db_path=str(runtime_paths.events_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={
                "backend": "local",
                "local_model": config.agent.memory.embedding.local_model,
                "local_dimension": config.agent.memory.embedding.local_dimension,
            },
            llm_adapter=llm_adapter,
        )
        await unified_memory.initialize()
        logger.info("UnifiedMemoryStore initialized (L1-L5)")

        # Create memory integration module
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

        # Create TaskAgents (Layer 2)
        num_task_agents = config.agent.num_task_agents
        _task_agents = []

        for i in range(num_task_agents):
            task_agent_config = AgentConfig(name=f"task_agent_{i}", llm_config={})
            task_agent = TaskAgent(
                agent_id=i,
                config=task_agent_config,
                message_bus=_message_bus,
                task_database=task_database,
                llm_adapter=llm_adapter,
                tool_registry=tool_registry,
                memory=memory,
                other_memory=other_memory,
                unified_memory=unified_memory,
                memory_integration=_memory_integration,
            )
            _task_agents.append(task_agent)
            logger.info(f"TaskAgent-{i} created")

        # Create MasterAgent (Layer 1)
        master_config = AgentConfig(name="master_agent", llm_config={})
        _master_agent = MasterAgent(
            config=master_config,
            message_bus=_message_bus,
            task_agents=_task_agents,
            task_database=task_database,
            llm_adapter=llm_adapter,
        )
        logger.info("MasterAgent created")

        # Set message bus to messages router
        from ..api.routers.messages import set_message_bus
        set_message_bus(_message_bus)

        # Initialize skills module
        if config.features.enable_skills:
            from ..api.routers.skills import init_skills_module
            init_skills_module(llm_adapter)
            logger.info("Skills module initialized")

        # Register UserMessageSensor
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        user_sensor.set_message_bus(_message_bus)
        await user_sensor.subscribe_to_message_bus("UserMessage")
        logger.info("UserMessageSensor subscribed to message bus")

        # Start MasterAgent (will start TaskAgents automatically)
        await _master_agent.start()
        logger.info("MasterAgent started (TaskAgents started automatically)")

        logger.info("=" * 60)
        logger.info("Three-Layer Architecture initialized successfully!")
        logger.info(f"  Layer 1: MasterAgent (task recognition & dispatch)")
        logger.info(f"  Layer 2: {num_task_agents} TaskAgents (task orchestration)")
        logger.info(f"  Layer 3: ChatWorkerAgent (task execution)")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Failed to initialize three-layer architecture: {e}", exc_info=True)
        raise


async def _initialize_chat_agent_legacy(config: AppConfig):
    """Initialize legacy ChatAgent (fallback mode)."""
    global _chat_agent, _memory_integration

    if _chat_agent is not None:
        logger.warning("ChatAgent already initialized")
        return

    try:
        # Initialize runtime data directory
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"Runtime directory: {runtime_paths.base_dir}")

        # Check API key
        if not config.agent.llm.api_key:
            logger.warning("=" * 60)
            logger.warning("LLM_API_KEY not set!")
            logger.warning("ChatAgent will NOT be initialized.")
            logger.warning("Set LLM_API_KEY environment variable to enable AI responses.")
            logger.warning("=" * 60)
            return

        logger.info("Initializing ChatAgent (Legacy Mode)...")

        # Create LLM adapter
        llm_adapter = _create_llm_adapter(config)

        # Create message bus
        message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.events_db_path),
        )
        await message_bus.start()

        # Create Agent Configuration
        agent_config = AgentConfig(
            name=config.agent.name,
            llm_config={},
        )

        # Get current personality name
        from ..api.routers.personality import get_current_personality
        current_personality = get_current_personality()
        logger.info(f"Current personality: {current_personality}")

        # Create memory systems
        memory = SelfMemory(
            personality_name=current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        logger.info("SelfMemory initialized")

        other_memory = OtherMemory()
        logger.info("OtherMemory initialized")

        unified_memory = UnifiedMemoryStore(
            db_path=str(runtime_paths.events_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={
                "backend": "local",
                "local_model": config.agent.memory.embedding.local_model,
                "local_dimension": config.agent.memory.embedding.local_dimension,
            },
            llm_adapter=llm_adapter,
        )
        await unified_memory.initialize()
        logger.info("UnifiedMemoryStore initialized (L1-L5)")

        # Create memory integration module
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
        memory_integration = MemoryIntegrationModule(
            unified_memory=unified_memory,
            message_bus=message_bus,
            config=memory_integration_config,
        )
        await memory_integration.start()
        logger.info("MemoryIntegrationModule started")

        _memory_integration = memory_integration

        # Create ChatAgent
        _chat_agent = ChatAgent(
            config=agent_config,
            message_bus=message_bus,
            llm_adapter=llm_adapter,
            memory=memory,
            other_memory=other_memory,
            unified_memory=unified_memory,
            memory_integration=memory_integration,
        )

        # Set message bus to messages router
        from ..api.routers.messages import set_message_bus
        set_message_bus(message_bus)

        # Initialize skills module
        if config.features.enable_skills:
            from ..api.routers.skills import init_skills_module
            init_skills_module(llm_adapter)
            logger.info("Skills module initialized")

        # Register UserMessageSensor
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        user_sensor.set_message_bus(message_bus)
        _chat_agent.perception_module.register_sensor("user_message", user_sensor)
        await user_sensor.subscribe_to_message_bus("UserMessage")
        logger.info("UserMessageSensor subscribed to message bus")

        # Start Agent
        await _chat_agent.start()
        logger.info("ChatAgent started successfully (Legacy Mode)")

    except Exception as e:
        logger.error(f"Failed to initialize ChatAgent: {e}", exc_info=True)
        raise


async def shutdown_chat_agent():
    """Shutdown agent on application close."""
    global _chat_agent, _master_agent, _task_agents, _memory_integration, _message_bus

    if _master_agent is not None:
        await _shutdown_three_layer_architecture()
    elif _chat_agent is not None:
        await _shutdown_chat_agent_legacy()


async def _shutdown_three_layer_architecture():
    """Shutdown three-layer architecture."""
    global _master_agent, _task_agents, _memory_integration, _message_bus

    logger.info("Stopping Three-Layer Architecture...")

    try:
        if _master_agent:
            await _master_agent.stop()
            logger.info("MasterAgent stopped")
            _master_agent = None

        _task_agents = []

        if _memory_integration:
            await _memory_integration.stop()
            logger.info("MemoryIntegrationModule stopped")
            _memory_integration = None

        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        await user_sensor.unsubscribe_from_message_bus()
        logger.info("UserMessageSensor unsubscribed from message bus")

        if _message_bus:
            await _message_bus.stop()
            logger.info("MessageBus stopped")
            _message_bus = None

        logger.info("Three-Layer Architecture stopped successfully")

    except Exception as e:
        logger.error(f"Failed to stop three-layer architecture: {e}", exc_info=True)


async def _shutdown_chat_agent_legacy():
    """Shutdown legacy ChatAgent."""
    global _chat_agent, _memory_integration

    if _chat_agent is None:
        return

    try:
        logger.info("Stopping ChatAgent (Legacy Mode)...")

        if _memory_integration:
            await _memory_integration.stop()
            logger.info("MemoryIntegrationModule stopped")
            _memory_integration = None

        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        await user_sensor.unsubscribe_from_message_bus()
        logger.info("UserMessageSensor unsubscribed from message bus")

        if _chat_agent.message_bus:
            await _chat_agent.message_bus.stop()

        await _chat_agent.stop()
        _chat_agent = None
        logger.info("ChatAgent stopped")

    except Exception as e:
        logger.error(f"Failed to stop ChatAgent: {e}", exc_info=True)
