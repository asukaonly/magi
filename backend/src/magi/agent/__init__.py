"""
Agent初始化模块

在应用启动时初始化ChatAgent并注册传感器
"""
import os
import logging
from ..core.agent import AgentConfig
from ..events.memory_backend import MemoryMessageBackend
from ..agent.chat import ChatAgent
from ..awareness.sensors import UserMessageSensor
from ..memory.self_memory_v2 import SelfMemoryV2
from ..utils.runtime import get_runtime_paths, init_runtime_data

logger = logging.getLogger(__name__)

# 全局Agent实例
_chat_agent: ChatAgent = None


def get_chat_agent() -> ChatAgent:
    """
    获取ChatAgent实例

    Returns:
        ChatAgent实例
    """
    global _chat_agent
    if _chat_agent is None:
        raise RuntimeError("ChatAgent not initialized. Call initialize_chat_agent() first.")
    return _chat_agent


def _create_llm_adapter():
    """
    根据环境变量创建LLM适配器

    Returns:
        LLM适配器实例
    """
    # 获取LLM提供商配置
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if not api_key:
        raise ValueError("LLM_API_KEY or OPENAI_API_KEY must be set")

    logger.info(f"🔧 Creating LLM adapter | Provider: {provider} | Model: {model} | Base URL: {base_url or 'default'}")

    # 根据提供商选择适配器
    if provider == "anthropic":
        from ..llm.anthropic import AnthropicAdapter
        return AnthropicAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    elif provider == "openai":
        from ..llm.openai import OpenAIAdapter
        return OpenAIAdapter(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}. Supported: 'openai', 'anthropic'")


async def initialize_chat_agent():
    """
    初始化ChatAgent

    在应用启动时调用
    """
    global _chat_agent

    if _chat_agent is not None:
        logger.warning("ChatAgent already initialized")
        return

    try:
        # 初始化运行时数据目录
        init_runtime_data()
        runtime_paths = get_runtime_paths()
        logger.info(f"📁 Runtime directory: {runtime_paths.base_dir}")

        # 获取环境变量
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

        if not api_key:
            logger.warning("LLM_API_KEY or OPENAI_API_KEY not set, ChatAgent will not be initialized")
            return

        logger.info("🔧 Initializing ChatAgent...")

        # 创建LLM适配器（自动选择提供商）
        llm_adapter = _create_llm_adapter()

        # 创建消息总线
        message_bus = MemoryMessageBackend()
        await message_bus.start()

        # 创建Agent配置
        config = AgentConfig(
            name="chat_agent",
            llm_config={},  # 临时空配置，实际使用传入的 llm_adapter
        )

        # 创建自我记忆系统
        memory = SelfMemoryV2(
            personality_name="default",
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await memory.init()
        logger.info("✅ SelfMemoryV2 initialized")

        # 创建ChatAgent
        _chat_agent = ChatAgent(
            config=config,
            message_bus=message_bus,
            llm_adapter=llm_adapter,
            memory=memory,
        )

        # 设置消息总线到messages router，使其可以发布事件
        from ..api.routers.messages import set_message_bus
        set_message_bus(message_bus)
        logger.info("✅ MessageBus set to messages router")

        # 注册UserMessageSensor并订阅消息总线
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        user_sensor.set_message_bus(message_bus)
        _chat_agent.perception_module.register_sensor("user_message", user_sensor)

        # 订阅USER_MESSAGE事件
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
    global _chat_agent

    if _chat_agent is None:
        return

    try:
        logger.info("🛑 Stopping ChatAgent...")

        # 取消UserMessageSensor的消息总线订阅
        from ..api.routers.messages import get_user_message_sensor
        user_sensor = get_user_message_sensor()
        await user_sensor.unsubscribe_from_message_bus()
        logger.info("✅ UserMessageSensor unsubscribed from message bus")

        # 停止消息总线
        if _chat_agent.message_bus:
            await _chat_agent.message_bus.stop()

        await _chat_agent.stop()
        _chat_agent = None
        logger.info("✅ ChatAgent stopped")
    except Exception as e:
        logger.error(f"❌ Failed to stop ChatAgent: {e}", exc_info=True)
