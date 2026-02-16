"""
系统ConfigurationAPIroute

提供系统Configuration的读取andupdatefunction
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

config_router = APIRouter()

# ============ data Models ============

class AgentConfigModel(BaseModel):
    """AgentConfiguration"""
    name: str = Field(default="magi-agent", description="AgentName")
    description: Optional[str] = Field(None, description="AgentDescription")


class LLMConfigModel(BaseModel):
    """LLMConfiguration"""
    provider: str = Field(default="openai", description="LLM提供商: openai, anthropic, glm, local")
    model: str = Field(default="gpt-4", description="modelName")
    api_key: Optional[str] = Field(None, description="APIkey")
    base_url: Optional[str] = Field(None, description="API endpoint url")


class LoopConfigModel(BaseModel):
    """循环Configuration"""
    strategy: str = Field(default="continuous", description="Loop strategy: step, wave, continuous")
    interval: float = Field(default=1.0, description="循环interval（seconds）")


class MessageBusConfigModel(BaseModel):
    """message busConfiguration"""
    backend: str = Field(default="memory", description="后端type: memory, sqlite, redis")
    max_size: Optional[int] = Field(None, description="maximumqueuesize")


class MemoryConfigModel(BaseModel):
    """Memory StorageConfiguration"""
    backend: str = Field(default="memory", description="后端type: memory, sqlite, chromadb")
    path: Optional[str] = Field(None, description="storagepath")


class WebSocketConfigModel(BaseModel):
    """WebSocketConfiguration"""
    enabled: bool = Field(default=True, description="is notEnableWebSocket")
    port: Optional[int] = Field(None, description="WebSocketport")


class LogConfigModel(BaseModel):
    """LogConfiguration"""
    level: str = Field(default="INFO", description="Loglevel: debug, INFO, warnING, error")
    path: Optional[str] = Field(None, description="Logfilepath")


class SystemConfigModel(BaseModel):
    """系统Configuration"""
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    loop: LoopConfigModel = Field(default_factory=LoopConfigModel)
    message_bus: MessageBusConfigModel = Field(default_factory=MessageBusConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    websocket: WebSocketConfigModel = Field(default_factory=WebSocketConfigModel)
    log: LogConfigModel = Field(default_factory=LogConfigModel)


class ConfigResponse(BaseModel):
    """Configurationresponse"""
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


# ============ defaultConfiguration ============

DEFAULT_CONFIG = SystemConfigModel(
    agent=AgentConfigModel(
        name="magi-agent",
        description="Magi AI Agent Framework",
    ),
    llm=LLMConfigModel(
        provider="openai",
        model="gpt-4",
        api_key=None,  # 从环境Variable读取
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


# ============ Configurationstorage（内存中） ============

_config: SystemConfigModel = DEFAULT_CONFIG


# ============ API Endpoints ============

@config_router.get("/", response_model=ConfigResponse)
async def get_config():
    """
    get系统Configuration

    Returns:
        current系统Configuration
    """
    # 从环境Variable读取LLMConfiguration
    llm_config = LLMConfigModel(
        provider=os.getenv("LLM_PROVidER", "openai"),
        model=os.getenv("LLM_MOdel", "gpt-4"),
        api_key="***" if os.getenv("LLM_API_KEY") else None,  # 隐藏key
        base_url=os.getenv("LLM_BasE_url"),
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
        message="getConfigurationsuccess",
        data=config,
    )


@config_router.put("/", response_model=ConfigResponse)
async def update_config(config: SystemConfigModel):
    """
    update系统Configuration

    Args:
        config: new的Configuration

    Returns:
        Updated configuration
    """
    global _config

    try:
        # updateConfiguration（不contains敏感info）
        _config = config

        # 如果提供了APIkey，Setting环境Variable
        if config.llm.api_key and config.llm.api_key != "***":
            os.environ["LLM_API_KEY"] = config.llm.api_key
            logger.info("LLM API Key 已update")

        if config.llm.base_url:
            os.environ["LLM_BasE_url"] = config.llm.base_url
            logger.info(f"LLM Base url 已update: {config.llm.base_url}")

        if config.llm.model:
            os.environ["LLM_MOdel"] = config.llm.model
            logger.info(f"LLM Model 已update: {config.llm.model}")

        if config.llm.provider:
            os.environ["LLM_PROVidER"] = config.llm.provider
            logger.info(f"LLM Provider 已update: {config.llm.provider}")

        logger.info("系统Configuration已update")

        return ConfigResponse(
            success=True,
            message="Configurationupdatesuccess",
            data=_config,
        )
    except Exception as e:
        logger.error(f"updateConfigurationfailure: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@config_router.post("/reset", response_model=ConfigResponse)
async def reset_config():
    """
    resetConfiguration为defaultValue

    Returns:
        defaultConfiguration
    """
    global _config
    _config = DEFAULT_CONFIG

    logger.info("Configuration已reset为defaultValue")

    return ConfigResponse(
        success=True,
        message="Configuration已reset",
        data=_config,
    )


@config_router.get("/template", response_model=ConfigResponse)
async def get_config_template():
    """
    getConfiguration模板

    Returns:
        Configuration模板
    """
    return ConfigResponse(
        success=True,
        message="getConfiguration模板success",
        data=DEFAULT_CONFIG,
    )


@config_router.post("/test", response_model=ConfigResponse)
async def test_config(config: SystemConfigModel):
    """
    TestConfigurationis notvalid

    Args:
        config: 要Test的Configuration

    Returns:
        TestResult
    """
    try:
        # Validate必填field
        if not config.llm.provider:
            raise ValueError("LLM provider is required")

        if not config.llm.model:
            raise ValueError("LLM model is required")

        # 这里可以addmore的Validate逻辑
        # 例如TestLLMconnection等

        return ConfigResponse(
            success=True,
            message="ConfigurationValidate通过",
            data=config,
        )
    except ValueError as e:
        return ConfigResponse(
            success=False,
            message=f"ConfigurationValidatefailure: {str(e)}",
            data=None,
        )
    except Exception as e:
        return ConfigResponse(
            success=False,
            message=f"ConfigurationTestfailure: {str(e)}",
            data=None,
        )
