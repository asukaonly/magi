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
    GLM = "glm"
    LOCAL = "local"


class LLMConfig(BaseModel):
    """LLM配置"""
    provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    model: str = Field(default="gpt-4")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    base_url: Optional[str] = Field(default=None, description="自定义API endpoint（如使用代理或中转服务）")
    api_base: Optional[str] = Field(default=None, description="兼容旧配置，等同于base_url")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    timeout: int = Field(default=60, ge=1, description="请求超时时间（秒）")


class MemoryBackend(str, Enum):
    """记忆后端类型"""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """嵌入向量后端类型"""
    LOCAL = "local"           # 本地 sentence-transformers
    OPENAI = "openai"         # OpenAI Embedding API
    ANTHROPIC = "anthropic"   # Anthropic Embeddings (待支持)


class EmbeddingConfig(BaseModel):
    """嵌入向量配置"""
    # 后端类型
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.LOCAL)

    # 本地配置
    local_model: str = Field(default="all-MiniLM-L6-v2", description="本地sentence-transformers模型名称")
    local_dimension: int = Field(default=384, description="向量维度")

    # OpenAI配置
    openai_model: str = Field(default="text-embedding-3-small", description="OpenAI embedding模型")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API密钥（如不设置则使用LLM配置中的）")
    openai_base_url: Optional[str] = Field(default=None, description="自定义API endpoint")

    # 通用配置
    batch_size: int = Field(default=32, ge=1, description="批量处理大小")
    timeout: int = Field(default=30, ge=1, description="请求超时时间（秒）")


class MemoryConfig(BaseModel):
    """记忆存储配置"""
    short_term: MemoryBackend = Field(default=MemoryBackend.MEMORY)
    long_term: MemoryBackend = Field(default=MemoryBackend.CHROMADB)

    # 路径配置（使用 ~/.magi/data）
    db_path: str = Field(default="~/.magi/data/memories")
    chromadb_path: str = Field(default="~/.magi/data/chromadb")

    # 保留策略
    retention_days: int = Field(default=7, ge=1)

    # 嵌入向量配置（L3层）
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    # L1-L5 五层记忆架构配置
    enable_l1_raw: bool = Field(default=True, description="启用L1原始事件存储")
    enable_l2_relations: bool = Field(default=True, description="启用L2事件关系图")
    enable_l3_embeddings: bool = Field(default=True, description="启用L3语义嵌入")
    enable_l4_summaries: bool = Field(default=True, description="启用L4时间摘要")
    enable_l5_capabilities: bool = Field(default=True, description="启用L5能力记忆")

    # L3 嵌入生成配置
    async_embeddings: bool = Field(default=True, description="异步生成嵌入向量")
    embedding_queue_size: int = Field(default=100, ge=1, description="嵌入向量队列大小")

    # L2 关系提取配置
    auto_extract_relations: bool = Field(default=True, description="自动提取事件关系")

    # L4 摘要生成配置
    summary_interval_minutes: int = Field(default=60, ge=1, description="摘要生成间隔（分钟）")
    auto_generate_summaries: bool = Field(default=True, description="自动生成摘要")

    # L5 能力提取配置
    capability_min_attempts: int = Field(default=3, ge=1, description="能力最小尝试次数")
    capability_min_success_rate: float = Field(default=0.7, ge=0.0, le=1.0, description="能力最小成功率")
    capability_blacklist_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="能力黑名单阈值")
    capability_blacklist_min_attempts: int = Field(default=5, ge=1, description="黑名单最小尝试次数")


class PersonalityConfig(BaseModel):
    """人格配置"""
    # 人格名称（对应personalities目录下的文件名）
    name: str = Field(default="default")
    # 人格配置文件目录
    path: str = Field(default="~/.magi/personalities")
    # 是否启用人格演化（L3/L4/L5层）
    enable_evolution: bool = Field(default=True)
    # 人格数据库路径
    db_path: str = Field(default="~/.magi/data/memories/self_memory_v2.db")


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

    # 人格配置
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)


class Config(BaseModel):
    """全局配置"""
    agent: AgentConfig
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
