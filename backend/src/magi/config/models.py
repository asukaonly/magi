"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in config.example.yaml.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from enum import Enum

from .constants import DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS


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
    SQLITE_VEC = "sqlite_vec"
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
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=MIN_MAX_TOKENS)
    timeout: int = Field(default=60, ge=1)


# =============================================================================
# Agent Configuration
# =============================================================================

class EmbeddingSettings(BaseModel):
    """Embedding configuration."""
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.SQLITE_VEC)
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
    broadcast_max_concurrency: int = Field(default=8, ge=1)
    handler_timeout_seconds: float = Field(default=2.0, ge=0.1)
    max_retries: int = Field(default=3, ge=0, description="Max retry attempts for failed message handling")
    retry_delay_seconds: float = Field(default=1.0, ge=0.1, description="Delay before retrying failed messages")


class MaintenanceSettings(BaseModel):
    """Maintenance daemon configuration."""
    enabled: bool = Field(default=True, description="Enable maintenance daemon")
    interval_seconds: float = Field(default=300.0, ge=10.0, description="Interval between maintenance runs")
    message_cleanup: bool = Field(default=True, description="Enable message queue cleanup")
    message_retain_hours: int = Field(default=24, ge=1, description="Retain completed messages for N hours")
    message_cleanup_batch_size: int = Field(default=1000, ge=100, description="Batch size for message cleanup")
    health_check: bool = Field(default=True, description="Enable health checks")
    log_rotation_check: bool = Field(default=True, description="Enable log rotation checks")


class RuntimeSettings(BaseModel):
    """Runtime configuration for P0/P1 features."""
    router_restart_backoff_seconds: float = Field(default=1.0, ge=0.1)
    task_agent_queue_maxsize: int = Field(default=100, ge=1)
    task_agent_enqueue_timeout_ms: float = Field(default=100.0, ge=1.0)
    task_agent_manager_idle_ttl_seconds: float = Field(default=1800.0, ge=60.0)
    task_agent_manager_max_dynamic_instances: int = Field(default=100, ge=1)
    chat_history_cache_max_sessions: int = Field(default=500, ge=1)
    chat_history_fetch_limit: int = Field(default=200, ge=1)


class AgentSettings(BaseModel):
    """Agent configuration."""
    name: str = Field(default="magi-agent")
    num_task_agents: int = Field(default=2, ge=1)
    loop_interval: float = Field(default=1.0, ge=0.0)
    enable_monitoring: bool = Field(default=True)

    memory: MemorySettings = Field(default_factory=MemorySettings)
    personality: PersonalitySettings = Field(default_factory=PersonalitySettings)
    message_bus: MessageBusSettings = Field(default_factory=MessageBusSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    maintenance: MaintenanceSettings = Field(default_factory=MaintenanceSettings)


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

class ProviderConfig(BaseModel):
    """Generic provider configuration."""
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)


class WeatherToolSettings(BaseModel):
    """Weather tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="qweather")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {"qweather": ProviderConfig()}
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class WebSearchToolSettings(BaseModel):
    """Web search tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="duckduckgo")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "duckduckgo": ProviderConfig(),
            "brave": ProviderConfig(),
            "perplexity": ProviderConfig(),
            "tavily": ProviderConfig(),
        }
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class WebFetchToolSettings(BaseModel):
    """Web fetch tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="http")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "http": ProviderConfig(),
            "browser": ProviderConfig(),
            "curl": ProviderConfig(),
        }
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class ToolsSettings(BaseModel):
    """Tools configuration."""
    weather: WeatherToolSettings = Field(default_factory=WeatherToolSettings)
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)
    web_fetch: WebFetchToolSettings = Field(default_factory=WebFetchToolSettings)


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
