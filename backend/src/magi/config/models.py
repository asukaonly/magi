"""
Configuration管理module - Pydanticmodel定义
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class MessageBusBackend(str, Enum):
    """message bus后端type"""
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class DropPolicy(str, Enum):
    """queue丢弃strategy"""
    oldEST = "oldest"
    LOWEST_PRI/ORITY = "lowest_priority"
    reject = "reject"


class MessageBusConfig(BaseModel):
    """message busConfiguration"""
    backend: MessageBusBackend = Field(default=MessageBusBackend.MEMORY)
    max_queue_size: int = Field(default=1000, ge=1)
    drop_policy: DropPolicy = Field(default=DropPolicy.LOWEST_PRI/ORITY)
    num_workers: int = Field(default=4, ge=1)

    # SQLiteConfiguration
    sqlite: Optional[Dict[str, Any]] = Field(default=None)

    # RedisConfiguration
    redis: Optional[Dict[str, Any]] = Field(default=None)


class LLMProvider(str, Enum):
    """LLM提供商"""
    openAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    local = "local"


class LLMConfig(BaseModel):
    """LLMConfiguration"""
    provider: LLMProvider = Field(default=LLMProvider.openAI)
    model: str = Field(default="gpt-4")
    api_key: Optional[str] = Field(default=None, description="APIkey")
    base_url: Optional[str] = Field(default=None, description="customAPI endpoint（如使用proxy或中转service）")
    api_base: Optional[str] = Field(default=None, description="compatibleoldConfiguration，等同于base_url")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    timeout: int = Field(default=60, ge=1, description="requesttimeout时间（seconds）")


class MemoryBackend(str, Enum):
    """memory后端type"""
    MEMORY = "memory"
    chrOMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """embeddingvector后端type"""
    local = "local"           # 本地 sentence-transformers
    openAI = "openai"         # OpenAI Embedding API
    ANTHROPIC = "anthropic"   # Anthropic Embeddings (待support)


class EmbeddingConfig(BaseModel):
    """embeddingvectorConfiguration"""
    # 后端type
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.local)

    # 本地Configuration
    local_model: str = Field(default="all-MiniLM-L6-v2", description="本地sentence-transformersmodelName")
    local_dimension: int = Field(default=384, description="vectordimension")

    # OpenAIConfiguration
    openai_model: str = Field(default="text-embedding-3-small", description="OpenAI embeddingmodel")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI APIkey（如不Setting则使用LLMConfiguration中的）")
    openai_base_url: Optional[str] = Field(default=None, description="customAPI endpoint")

    # 通用Configuration
    batch_size: int = Field(default=32, ge=1, description="批量processsize")
    timeout: int = Field(default=30, ge=1, description="requesttimeout时间（seconds）")


class MemoryConfig(BaseModel):
    """Memory StorageConfiguration"""
    short_term: MemoryBackend = Field(default=MemoryBackend.MEMORY)
    long_term: MemoryBackend = Field(default=MemoryBackend.chrOMADB)

    # pathConfiguration（使用 ~/.magi/data）
    db_path: str = Field(default="~/.magi/data/memories")
    chromadb_path: str = Field(default="~/.magi/data/chromadb")

    # 保留strategy
    retention_days: int = Field(default=7, ge=1)

    # embeddingvectorConfiguration（L3层）
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)

    # L1-L5 五层memoryarchitectureConfiguration
    enable_l1_raw: bool = Field(default=True, description="EnableL1Raw event Storage")
    enable_l2_relations: bool = Field(default=True, description="EnableL2event Relation Graph")
    enable_l3_embeddings: bool = Field(default=True, description="EnableL3Semantic Embeddings")
    enable_l4_summaries: bool = Field(default=True, description="EnableL4Time Summaries")
    enable_l5_capabilities: bool = Field(default=True, description="EnableL5capabilitymemory")

    # L3 embeddinggenerationConfiguration
    async_embeddings: bool = Field(default=True, description="asynchronotttusgenerationembeddingvector")
    embedding_queue_size: int = Field(default=100, ge=1, description="embeddingvectorqueuesize")

    # L2 relationship提取Configuration
    auto_extract_relations: bool = Field(default=True, description="自动提取eventrelationship")

    # L4 summarygenerationConfiguration
    summary_interval_minutes: int = Field(default=60, ge=1, description="summarygenerationinterval（minutes）")
    auto_generate_summaries: bool = Field(default=True, description="自动generationsummary")

    # L5 Capability ExtractionConfiguration
    capability_min_attempts: int = Field(default=3, ge=1, description="capabilityminimum尝试count")
    capability_min_success_rate: float = Field(default=0.7, ge=0.0, le=1.0, description="capabilityminimumsuccess率")
    capability_blacklist_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="capability黑名单阈Value")
    capability_blacklist_min_attempts: int = Field(default=5, ge=1, description="黑名单minimum尝试count")


class PersonalityConfig(BaseModel):
    """Personality configuration"""
    # Personality name（correspondpersonalitiesdirectory下的filename）
    name: str = Field(default="default")
    # Personality configurationfiledirectory
    path: str = Field(default="~/.magi/personalities")
    # is nottttEnablepersonalityevolution（L3/L4/L5层）
    enable_evolution: bool = Field(default=True)
    # personalitydatabasepath
    db_path: str = Field(default="~/.magi/data/memories/self_memory_v2.db")


class PluginConfig(BaseModel):
    """pluginConfiguration"""
    enabled: bool = Field(default=True)
    priority: int = Field(default=0)
    config: Optional[Dict[str, Any]] = Field(default=None)


class AgentConfig(BaseModel):
    """AgentConfiguration"""
    name: str
    llm: LLMConfig
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    message_bus: MessageBusConfig = Field(default_factory=MessageBusConfig)

    # TaskAgentConfiguration
    num_task_agents: int = Field(default=3, ge=1)

    # pluginConfiguration
    plugins: Dict[str, PluginConfig] = Field(default_factory=dict)

    # 循环Configuration
    loop_interval: float = Field(default=1.0, ge=0.0)

    # monitorConfiguration
    enable_monitoring: bool = Field(default=True)

    # Personality configuration
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)


class Config(BaseModel):
    """globalConfiguration"""
    agent: AgentConfig
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
