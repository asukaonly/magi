"""
配置管理模块 - Pydantic模型定义
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class MessageBusBackend(str, Enum):
    """消息总线后端类型"""
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class DropPolicy(str, Enum):
    """队列丢弃策略"""
    OLDEST = "oldest"
    LOWEST_PRIORITY = "lowest_priority"
    REJECT = "reject"


class MessageBusConfig(BaseModel):
    """消息总线配置"""
    backend: MessageBusBackend = Field(default=MessageBusBackend.MEMORY)
    max_queue_size: int = Field(default=1000, ge=1)
    drop_policy: DropPolicy = Field(default=DropPolicy.LOWEST_PRIORITY)
    num_workers: int = Field(default=4, ge=1)

    # SQLite配置
    sqlite: Optional[Dict[str, Any]] = Field(default=None)

    # Redis配置
    redis: Optional[Dict[str, Any]] = Field(default=None)


class LLMProvider(str, Enum):
    """LLM提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


class LLMConfig(BaseModel):
    """LLM配置"""
    provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    model: str = Field(default="gpt-4")
    api_key: Optional[str] = Field(default=None)
    api_base: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)


class MemoryBackend(str, Enum):
    """记忆后端类型"""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class MemoryConfig(BaseModel):
    """记忆存储配置"""
    short_term: MemoryBackend = Field(default=MemoryBackend.MEMORY)
    long_term: MemoryBackend = Field(default=MemoryBackend.CHROMADB)

    # 路径配置
    db_path: str = Field(default="./data/memories")
    chromadb_path: str = Field(default="./data/chromadb")

    # 保留策略
    retention_days: int = Field(default=7, ge=1)


class PluginConfig(BaseModel):
    """插件配置"""
    enabled: bool = Field(default=True)
    priority: int = Field(default=0)
    config: Optional[Dict[str, Any]] = Field(default=None)


class AgentConfig(BaseModel):
    """Agent配置"""
    name: str
    llm: LLMConfig
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    message_bus: MessageBusConfig = Field(default_factory=MessageBusConfig)

    # TaskAgent配置
    num_task_agents: int = Field(default=3, ge=1)

    # 插件配置
    plugins: Dict[str, PluginConfig] = Field(default_factory=dict)

    # 循环配置
    loop_interval: float = Field(default=1.0, ge=0.0)

    # 监控配置
    enable_monitoring: bool = Field(default=True)


class Config(BaseModel):
    """全局配置"""
    agent: AgentConfig
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
