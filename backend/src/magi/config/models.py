"""
Configuration Models - Pydantic model definitions for application configuration.

This module defines the configuration schema using Pydantic models.
All configuration access should go through the config module, not direct env reads.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class MessageBusBackend(str, Enum):
    """Message bus backend type."""
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class DropPolicy(str, Enum):
    """Queue drop strategy when full."""
    OLDEST = "oldest"
    LOWEST_PRIORITY = "lowest_priority"
    REJECT = "reject"


class MessageBusSettings(BaseModel):
    """Message bus configuration settings."""
    backend: MessageBusBackend = Field(default=MessageBusBackend.SQLITE)
    max_queue_size: int = Field(default=1000, ge=1)
    drop_policy: DropPolicy = Field(default=DropPolicy.LOWEST_PRIORITY)
    num_workers: int = Field(default=4, ge=1)
    sqlite_db_path: Optional[str] = Field(default=None)
    redis_url: Optional[str] = Field(default=None)


class LLMProvider(str, Enum):
    """LLM provider type."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    LOCAL = "local"


class LLMSettings(BaseModel):
    """LLM configuration settings."""
    provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    model: str = Field(default="gpt-4o-mini")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1000, ge=1)
    timeout: int = Field(default=60, ge=1)


class MemoryBackend(str, Enum):
    """Memory storage backend type."""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """Embedding vector backend type."""
    LOCAL = "local"
    OPENAI = "openai"


class EmbeddingSettings(BaseModel):
    """Embedding vector configuration settings."""
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.LOCAL)
    local_model: str = Field(default="all-MiniLM-L6-v2")
    local_dimension: int = Field(default=384)
    openai_model: str = Field(default="text-embedding-3-small")
    openai_api_key: Optional[str] = Field(default=None)
    batch_size: int = Field(default=32, ge=1)
    timeout: int = Field(default=30, ge=1)


class MemorySettings(BaseModel):
    """Memory storage configuration settings."""
    short_term_backend: MemoryBackend = Field(default=MemoryBackend.MEMORY)
    long_term_backend: MemoryBackend = Field(default=MemoryBackend.CHROMADB)
    db_path: str = Field(default="~/.magi/data/memories")
    chromadb_path: str = Field(default="~/.magi/data/chromadb")
    retention_days: int = Field(default=7, ge=1)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)

    # L1-L5 layers
    enable_l1_raw: bool = Field(default=True)
    enable_l2_relations: bool = Field(default=True)
    enable_l3_embeddings: bool = Field(default=True)
    enable_l4_summaries: bool = Field(default=True)
    enable_l5_capabilities: bool = Field(default=True)
    async_embeddings: bool = Field(default=True)
    embedding_queue_size: int = Field(default=100, ge=1)
    auto_extract_relations: bool = Field(default=True)
    summary_interval_minutes: int = Field(default=60, ge=1)
    auto_generate_summaries: bool = Field(default=True)
    capability_min_attempts: int = Field(default=3, ge=1)
    capability_min_success_rate: float = Field(default=0.7, ge=0.0, le=1.0)
    capability_blacklist_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    capability_blacklist_min_attempts: int = Field(default=5, ge=1)


class PersonalitySettings(BaseModel):
    """Personality configuration settings."""
    name: str = Field(default="default")
    path: str = Field(default="~/.magi/personalities")
    enable_evolution: bool = Field(default=True)
    db_path: str = Field(default="~/.magi/data/memories/self_memory_v2.db")


class PluginSettings(BaseModel):
    """Plugin configuration settings."""
    enabled: bool = Field(default=True)
    priority: int = Field(default=0)
    config: Optional[Dict[str, Any]] = Field(default=None)


class AgentSettings(BaseModel):
    """Agent configuration settings."""
    name: str = Field(default="magi-agent")
    llm: LLMSettings = Field(default_factory=LLMSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    message_bus: MessageBusSettings = Field(default_factory=MessageBusSettings)
    num_task_agents: int = Field(default=2, ge=1)
    plugins: Dict[str, PluginSettings] = Field(default_factory=dict)
    loop_interval: float = Field(default=1.0, ge=0.0)
    enable_monitoring: bool = Field(default=True)
    personality: PersonalitySettings = Field(default_factory=PersonalitySettings)


class ServerSettings(BaseModel):
    """Server configuration settings."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    cors_origins: List[str] = Field(default=["*"])
    websocket_ping_interval: int = Field(default=30)


class FeatureFlags(BaseModel):
    """Feature flags for enabling/disabling features."""
    enable_three_layer_arch: bool = Field(default=False)
    enable_skills: bool = Field(default=True)
    enable_websocket: bool = Field(default=True)


class WeatherToolSettings(BaseModel):
    """Weather tool configuration."""
    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None, description="Weather API key (e.g., OpenWeatherMap)")
    base_url: Optional[str] = Field(default=None, description="Custom API endpoint")
    default_location: str = Field(default="Beijing", description="Default location for weather queries")


class WebSearchToolSettings(BaseModel):
    """Web search tool configuration."""
    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None, description="Search API key")
    engine: str = Field(default="google", description="Search engine: google, bing, duckduckgo")
    max_results: int = Field(default=5, ge=1, le=20)


class ToolsSettings(BaseModel):
    """Tools configuration container."""
    weather: WeatherToolSettings = Field(default_factory=WeatherToolSettings)
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)

    # Generic tool API keys (for tools that don't have dedicated settings)
    api_keys: Dict[str, str] = Field(default_factory=dict, description="Generic API keys by tool name")


class AppConfig(BaseModel):
    """Root application configuration."""
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")


# Type alias for backward compatibility
Config = AppConfig
