"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in config.example.yaml.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum


class LLMProvider(str, Enum):
    """LLM provider type."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    LOCAL = "local"


class MessageBusBackend(str, Enum):
    """Message bus backend type."""
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class MemoryBackend(str, Enum):
    """Memory storage backend type."""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """Embedding vector backend type."""
    LOCAL = "local"
    OPENAI = "openai"


# =============================================================================
# LLM Configuration
# =============================================================================

class LLMSettings(BaseModel):
    """LLM configuration."""
    provider: LLMProvider = Field(default=LLMProvider.OPENAI)
    model: str = Field(default="gpt-4o-mini")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1)
    timeout: int = Field(default=60, ge=1)


# =============================================================================
# Agent Configuration
# =============================================================================

class EmbeddingSettings(BaseModel):
    """Embedding configuration."""
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.LOCAL)
    local_model: str = Field(default="all-MiniLM-L6-v2")
    local_dimension: int = Field(default=384)


class MemorySettings(BaseModel):
    """Memory configuration."""
    db_path: str = Field(default="~/.magi/data/memories")
    retention_days: int = Field(default=7, ge=1)

    # L1-L5 layers
    enable_l1_raw: bool = Field(default=True)
    enable_l2_relations: bool = Field(default=True)
    enable_l3_embeddings: bool = Field(default=True)
    enable_l4_summaries: bool = Field(default=True)
    enable_l5_capabilities: bool = Field(default=True)
    async_embeddings: bool = Field(default=True)
    auto_extract_relations: bool = Field(default=True)
    summary_interval_minutes: int = Field(default=60, ge=1)

    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)


class PersonalitySettings(BaseModel):
    """Personality configuration."""
    name: str = Field(default="default")
    path: str = Field(default="~/.magi/personalities")
    enable_evolution: bool = Field(default=True)


class MessageBusSettings(BaseModel):
    """Message bus configuration."""
    backend: MessageBusBackend = Field(default=MessageBusBackend.SQLITE)
    max_queue_size: int = Field(default=1000, ge=1)
    num_workers: int = Field(default=4, ge=1)
    db_path: str = Field(default="~/.magi/data/events.db")


class AgentSettings(BaseModel):
    """Agent configuration."""
    name: str = Field(default="magi-agent")
    num_task_agents: int = Field(default=2, ge=1)
    loop_interval: float = Field(default=1.0, ge=0.0)
    enable_monitoring: bool = Field(default=True)

    memory: MemorySettings = Field(default_factory=MemorySettings)
    personality: PersonalitySettings = Field(default_factory=PersonalitySettings)
    message_bus: MessageBusSettings = Field(default_factory=MessageBusSettings)


# =============================================================================
# Server Configuration
# =============================================================================

class ServerSettings(BaseModel):
    """Server configuration."""
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    debug: bool = Field(default=False)
    cors_origins: List[str] = Field(default=["*"])


# =============================================================================
# Feature Flags
# =============================================================================

class FeatureFlags(BaseModel):
    """Feature flags."""
    enable_three_layer_arch: bool = Field(default=False)
    enable_skills: bool = Field(default=True)
    enable_websocket: bool = Field(default=True)


# =============================================================================
# Tools Configuration
# =============================================================================

class WeatherToolSettings(BaseModel):
    """Weather tool configuration (QWeather)."""
    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    default_location: str = Field(default="Beijing")


class WebSearchToolSettings(BaseModel):
    """Web search tool configuration."""
    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None)
    engine: str = Field(default="google")
    max_results: int = Field(default=5, ge=1, le=20)


class ToolsSettings(BaseModel):
    """Tools configuration."""
    weather: WeatherToolSettings = Field(default_factory=WeatherToolSettings)
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)


# =============================================================================
# Other Settings
# =============================================================================

class PluginSettings(BaseModel):
    """Plugin configuration."""
    enabled: bool = Field(default=True)
    priority: int = Field(default=0)
    config: Optional[Dict[str, Any]] = Field(default=None)


# =============================================================================
# Root Configuration
# =============================================================================

class AppConfig(BaseModel):
    """Root application configuration."""
    llm: LLMSettings = Field(default_factory=LLMSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")


# Type alias for backward compatibility
Config = AppConfig
