"""
Agentinitializemodule

在应用启动时initializeChatAgent并register传感器
"""
import os
import logging
from ..core.agent import AgentConfig
from ..events.sqlite_backend import SQLiteMessageBackend
from ..agent.chat import ChatAgent
from ..awareness.sensors import UserMessageSensor
from ..memory.self_memory import SelfMemory
from ..memory.other_memory import OtherMemory
from ..memory import UnifiedMemoryStore
from ..memory.integration import MemoryIntegrationModule, MemoryIntegrationConfig
from ..utils.runtime import get_runtime_paths, init_runtime_data

logger = logging.getLogger(__name__)

# globalAgentInstance
_chat_agent: ChatAgent = None

# Memory Integration ModuleInstance
_memory_integration: MemoryIntegrationModule = None


def get_chat_agent() -> ChatAgent:
    """
    getChatAgentInstance

    Returns:
        ChatAgentInstance
    """
    global _chat_agent
    if _chat_agent is None:
        raise Runtimeerror("ChatAgent not initialized. Call initialize_chat_agent() first.")
    return _chat_agent


def get_memory_integration() -> MemoryIntegrationModule:
    """
    getMemory Integration ModuleInstance

    Returns:
        MemoryIntegrationModuleInstance
    """
    global _memory_integration
    if _memory_integration is None:
        raise Runtimeerror("MemoryIntegrationModule not initialized. Call initialize_chat_agent() first.")
    return _memory_integration


def get_unified_memory() -> UnifiedMemoryStore:
    """
    getUnified Memory StorageInstance

    Returns:
        UnifiedMemoryStoreInstance
    """
    memory_integration = get_memory_integration()
    return memory_integration.unified_memory


def _create_llm_adapter():
    """
    根据环境VariableCreate LLM adapter

    Returns:
        LLMAdapterInstance
    """
    # getLLM提供商Configuration
    provider = os.getenv("LLM_PROVidER", "openai").lower()
    api_key = os.getenv("LLM_API_key")
    base_url = os.getenv("LLM_BasE_url")
    model = os.getenv("LLM_MOdel", "gpt-4o-mini")

    if not api_key:
        raise Valueerror("LLM_API_key must be set")

    logger.info(f"🔧 Creating LLM adapter | Provider: {provider} | Model: {model} | Base url: {base_url or 'default'}")

    # 根据提供商选择Adapter
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
        raise Valueerror(
            f"Unsupported LLM provider: {provider}. Supported: 'openai', 'anthropic', 'glm'"
        )


async def initialize_chat_agent():
    """
    initializeChatAgent

    在应用启动时调用
    """
    global _chat_agent

    if _chat_agent is not None:
        logger.warning("ChatAgent already initialized")
        return

    try:
        # initializerun时datadirectory
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"📁 Runtime directory: {runtime_paths.base_dir}")

        # get环境Variable
        api_key = os.getenv("LLM_API_key")

        if not api_key:
            logger.warning("=" * 60)
            logger.warning("⚠️  LLM_API_key not set!")
            logger.warning("⚠️  ChatAgent will NOT be initialized.")
            logger.warning("⚠️  Set LLM_API_key environment variable to enable AI responses.")
            logger.warning("⚠️  Example: export LLM_API_key='sk-...'")
            logger.warning("=" * 60)
            return

        logger.info("🔧 Initializing ChatAgent...")

        # Create LLM adapter（自动选择提供商）
        llm_adapter = _create_llm_adapter()

        # createmessage bus（使用SQLite持久化后端）
        message_bus = SQLiteMessageBackend(
            db_path=str(runtime_paths.events_db_path),
        )
        await message_bus.start()

        # createAgentConfiguration
        config = AgentConfig(
            name="chat_agent",
            llm_config={},  # temporary空Configuration，实际使用传入的 llm_adapter
        )

        # getCurrent personality name
        from ..api.routers.personality import get_current_personality
        current_personality = get_current_personality()
        logger.info(f"📋 Current personality: {current_personality}")

        # create自我Memory System
        memory = SelfMemory(
            personality_name=current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        logger.info("✅ SelfMemory initialized")

        # create他人Memory System
        other_memory = OtherMemory()
        logger.info("✅ OtherMemory initialized")

        # createUnified Memory Storage（L1-L5）
        unified_memory = UnifiedMemoryStore(
            db_path=str(runtime_paths.events_db_path),
            persist_dir=str(runtime_paths.memories_dir),
            enable_embeddings=True,
            enable_summaries=True,
            enable_capabilities=True,
            embedding_config={
                "backend": "local",
                "local_model": "all-MiniLM-L6-v2",
                "local_dimension": 384,
            },
            llm_adapter=llm_adapter,
        )
        await unified_memory.initialize()
        logger.info("✅ UnifiedMemoryStore initialized (L1-L5)")

        # createMemory Integration Module
        memory_integration_config = MemoryIntegrationConfig(
            enable_l1_raw=True,
            enable_l2_relations=True,
            enable_l3_embeddings=True,
            enable_l4_summaries=True,
            enable_l5_capabilities=True,
            async_embeddings=True,
            auto_extract_relations=True,
            summary_interval_minutes=60,
        )
        memory_integration = MemoryIntegrationModule(
            unified_memory=unified_memory,
            message_bus=message_bus,
            config=memory_integration_config,
        )
        await memory_integration.start()
        logger.info("✅ MemoryIntegrationModule started")

        # 将Memory System附加到globalVariable
        global _memory_integration
        _memory_integration = memory_integration

        # createChatAgent
        _chat_agent = ChatAgent(
            config=config,
            message_bus=message_bus,
            llm_adapter=llm_adapter,
            memory=memory,
            other_memory=other_memory,
            unified_memory=unified_memory,
            memory_integration=memory_integration,
        )

        # Settingmessage bus到messages router，使其可以Publish event
        from ..api.routers.messages import set_message_bus
        set_message_bus(message_bus)
        logger.info("✅ MessageBus set to messages router")

        # initialize Skills module
        from ..api.routers.skills import init_skills_module
        init_skills_module(llm_adapter)
        logger.info("✅ Skills module initialized")

        # registerUserMessageSensor并subscribemessage bus
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        user_sensor.set_message_bus(message_bus)
        _chat_agent.perception_module.register_sensor("user_message", user_sensor)

        # subscribeuser_MESSAGEevent
        await user_sensor.subscribe_to_message_bus("UserMessage")
        logger.info("✅ UserMessageSensor subscribed to message bus")

        logger.info("✅ UserMessageSensor registered to ChatAgent")

        # 启动Agent（会自动启动LoopEngine）
        await _chat_agent.start()

        logger.info("✅ ChatAgent started successfully")

    except Exception as e:
        logger.error(f"❌ Failed to initialize ChatAgent: {e}", exc_info=True)
        raise


async def shutdown_chat_agent():
    """
    关闭ChatAgent

    在应用关闭时调用
    """
    global _chat_agent, _memory_integration

    if _chat_agent is None:
        return

    try:
        logger.info("🛑 Stopping ChatAgent...")

        # stopMemory Integration Module
        if _memory_integration:
            await _memory_integration.stop()
            logger.info("✅ MemoryIntegrationModule stopped")
            _memory_integration = None

        # cancelUserMessageSensor的message bussubscribe
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        await user_sensor.unsubscribe_from_message_bus()
        logger.info("✅ UserMessageSensor unsubscribed from message bus")

        # stop message bus
        if _chat_agent.message_bus:
            await _chat_agent.message_bus.stop()

        await _chat_agent.stop()
        _chat_agent = None
        logger.info("✅ ChatAgent stopped")
    except Exception as e:
        logger.error(f"❌ Failed to stop ChatAgent: {e}", exc_info=True)
