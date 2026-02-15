"""
系统配置API路由

提供系统配置的读取和更新功能
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

config_router = APIRouter()

# ============ 数据模型 ============

class AgentConfigModel(BaseModel):
    """Agent配置"""
    name: str = Field(default="magi-agent", description="Agent名称")
    description: Optional[str] = Field(None, description="Agent描述")


class LLMConfigModel(BaseModel):
    """LLM配置"""
    provider: str = Field(default="openai", description="LLM提供商: openai, anthropic, glm, local")
    model: str = Field(default="gpt-4", description="模型名称")
    api_key: Optional[str] = Field(None, description="API密钥")
    base_url: Optional[str] = Field(None, description="API endpoint URL")


class LoopConfigModel(BaseModel):
    """循环配置"""
    strategy: str = Field(default="continuous", description="循环策略: step, wave, continuous")
    interval: float = Field(default=1.0, description="循环间隔（秒）")


class MessageBusConfigModel(BaseModel):
    """消息总线配置"""
    backend: str = Field(default="memory", description="后端类型: memory, sqlite, redis")
    max_size: Optional[int] = Field(None, description="最大队列大小")


class MemoryConfigModel(BaseModel):
    """记忆存储配置"""
    backend: str = Field(default="memory", description="后端类型: memory, sqlite, chromadb")
    path: Optional[str] = Field(None, description="存储路径")


class WebSocketConfigModel(BaseModel):
    """WebSocket配置"""
    enabled: bool = Field(default=True, description="是否启用WebSocket")
    port: Optional[int] = Field(None, description="WebSocket端口")


class LogConfigModel(BaseModel):
    """日志配置"""
    level: str = Field(default="INFO", description="日志级别: DEBUG, INFO, WARNING, ERROR")
    path: Optional[str] = Field(None, description="日志文件路径")


class SystemConfigModel(BaseModel):
    """系统配置"""
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    loop: LoopConfigModel = Field(default_factory=LoopConfigModel)
    message_bus: MessageBusConfigModel = Field(default_factory=MessageBusConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    websocket: WebSocketConfigModel = Field(default_factory=WebSocketConfigModel)
    log: LogConfigModel = Field(default_factory=LogConfigModel)


class ConfigResponse(BaseModel):
    """配置响应"""
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


# ============ 默认配置 ============

DEFAULT_CONFIG = SystemConfigModel(
    agent=AgentConfigModel(
        name="magi-agent",
        description="Magi AI Agent Framework",
    ),
    llm=LLMConfigModel(
        provider="openai",
        model="gpt-4",
        api_key=None,  # 从环境变量读取
        base_url=None,
    ),
    loop=LoopConfigModel(
        strategy="continuous",
        interval=1.0,
    ),
    message_bus=MessageBusConfigModel(
        backend="memory",
        max_size=1000,
    ),
    memory=MemoryConfigModel(
        backend="memory",
        path=None,
    ),
    websocket=WebSocketConfigModel(
        enabled=True,
        port=8000,
    ),
    log=LogConfigModel(
        level="INFO",
        path=None,
    ),
)


# ============ 配置存储（内存中） ============

_config: SystemConfigModel = DEFAULT_CONFIG


# ============ API端点 ============

@config_router.get("/", response_model=ConfigResponse)
async def get_config():
    """
    获取系统配置

    Returns:
        当前系统配置
    """
    # 从环境变量读取LLM配置
    llm_config = LLMConfigModel(
        provider=os.getenv("LLM_PROVIDER", "openai"),
        model=os.getenv("LLM_MODEL", "gpt-4"),
        api_key="***" if os.getenv("LLM_API_KEY") else None,  # 隐藏密钥
        base_url=os.getenv("LLM_BASE_URL"),
    )

    config = SystemConfigModel(
        agent=_config.agent,
        llm=llm_config,
        loop=_config.loop,
        message_bus=_config.message_bus,
        memory=_config.memory,
        websocket=_config.websocket,
        log=_config.log,
    )

    return ConfigResponse(
        success=True,
        message="获取配置成功",
        data=config,
    )


@config_router.put("/", response_model=ConfigResponse)
async def update_config(config: SystemConfigModel):
    """
    更新系统配置

    Args:
        config: 新的配置

    Returns:
        更新后的配置
    """
    global _config

    try:
        # 更新配置（不包含敏感信息）
        _config = config

        # 如果提供了API密钥，设置环境变量
        if config.llm.api_key and config.llm.api_key != "***":
            os.environ["LLM_API_KEY"] = config.llm.api_key
            logger.info("LLM API Key 已更新")

        if config.llm.base_url:
            os.environ["LLM_BASE_URL"] = config.llm.base_url
            logger.info(f"LLM Base URL 已更新: {config.llm.base_url}")

        if config.llm.model:
            os.environ["LLM_MODEL"] = config.llm.model
            logger.info(f"LLM Model 已更新: {config.llm.model}")

        if config.llm.provider:
            os.environ["LLM_PROVIDER"] = config.llm.provider
            logger.info(f"LLM Provider 已更新: {config.llm.provider}")

        logger.info("系统配置已更新")

        return ConfigResponse(
            success=True,
            message="配置更新成功",
            data=_config,
        )
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@config_router.post("/reset", response_model=ConfigResponse)
async def reset_config():
    """
    重置配置为默认值

    Returns:
        默认配置
    """
    global _config
    _config = DEFAULT_CONFIG

    logger.info("配置已重置为默认值")

    return ConfigResponse(
        success=True,
        message="配置已重置",
        data=_config,
    )


@config_router.get("/template", response_model=ConfigResponse)
async def get_config_template():
    """
    获取配置模板

    Returns:
        配置模板
    """
    return ConfigResponse(
        success=True,
        message="获取配置模板成功",
        data=DEFAULT_CONFIG,
    )


@config_router.post("/test", response_model=ConfigResponse)
async def test_config(config: SystemConfigModel):
    """
    测试配置是否有效

    Args:
        config: 要测试的配置

    Returns:
        测试结果
    """
    try:
        # 验证必填字段
        if not config.llm.provider:
            raise ValueError("LLM provider is required")

        if not config.llm.model:
            raise ValueError("LLM model is required")

        # 这里可以添加更多的验证逻辑
        # 例如测试LLM连接等

        return ConfigResponse(
            success=True,
            message="配置验证通过",
            data=config,
        )
    except ValueError as e:
        return ConfigResponse(
            success=False,
            message=f"配置验证失败: {str(e)}",
            data=None,
        )
    except Exception as e:
        return ConfigResponse(
            success=False,
            message=f"配置测试失败: {str(e)}",
            data=None,
        )
