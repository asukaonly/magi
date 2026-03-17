"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in backend/configs/config.example.yaml.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, model_validator
from enum import Enum

from .constants import DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS


class LLMProvider(str, Enum):
    """LLM provider type."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    MINIMAX = "minimax"
    LOCAL = "local"
    CUSTOM = "custom"


class LLMCapabilitiesSettings(BaseModel):
    """Declared capability flags for the active LLM."""

    vision: bool = Field(default=False)
    image_output: bool = Field(default=False)
    tool_calling: bool = Field(default=True)
    reasoning: bool = Field(default=True)
    embedding: bool = Field(default=False)


class LLMLimitsSettings(BaseModel):
    """Capability-adjacent numeric limits for the active LLM."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class MemoryBackend(str, Enum):
    """Memory storage backend type."""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """Embedding vector backend type."""
    SQLITE_VEC = "sqlite_vec"
    OPENAI = "openai"


class TimelineSyncMode(str, Enum):
    """Timeline source sync mode."""

    MANUAL = "manual"
    INTERVAL = "interval"
    WATCH = "watch"


class TimelineRetentionMode(str, Enum):
    """Timeline raw-data retention behavior."""

    RETAIN_RAW = "retain_raw"
    ANALYZE_ONLY = "analyze_only"


class TimelineStorageMode(str, Enum):
    """Timeline asset storage mode."""

    MANAGED = "managed"
    EXTERNAL_REFERENCE = "external_reference"


# =============================================================================
# LLM Configuration
# =============================================================================

class LLMScenario(str, Enum):
    """Supported runtime LLM scenarios."""

    CONTEXT_DECIDER = "context_decider"
    CORE = "core"
    EMBEDDING = "embedding"


class LLMProviderSettings(BaseModel):
    """Reusable provider connection settings."""

    enabled: bool = Field(default=True)
    provider_type: LLMProvider = Field(default=LLMProvider.OPENAI)
    display_name: str = Field(default="OpenAI")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def validate_custom_model_defaults(self) -> "LLMProviderSettings":
        if self.provider_type == LLMProvider.CUSTOM:
            if self.custom_default_model and self.custom_default_model not in self.custom_models:
                raise ValueError("Custom default model must exist in custom_models")
        return self


class LLMSelectionSettings(BaseModel):
    """Per-scenario model selection."""

    provider_id: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    """Scenario-based LLM configuration."""

    providers: Dict[str, LLMProviderSettings] = Field(
        default_factory=lambda: {
            "openai": LLMProviderSettings(
                provider_type=LLMProvider.OPENAI,
                display_name="OpenAI",
            )
        }
    )
    selections: Dict[str, LLMSelectionSettings] = Field(
        default_factory=lambda: {
            LLMScenario.CONTEXT_DECIDER.value: LLMSelectionSettings(),
            LLMScenario.CORE.value: LLMSelectionSettings(),
            LLMScenario.EMBEDDING.value: LLMSelectionSettings(
                capabilities=LLMCapabilitiesSettings(embedding=True),
            ),
        }
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=MIN_MAX_TOKENS)
    timeout: int = Field(default=60, ge=1)

    @model_validator(mode="after")
    def validate_builtin_provider_uniqueness(self) -> "LLMSettings":
        # EMBEDDING is optional - system falls back to local model if not configured
        required_scenarios = {
            LLMScenario.CONTEXT_DECIDER.value,
            LLMScenario.CORE.value,
        }
        missing_scenarios = required_scenarios.difference(self.selections.keys())
        if missing_scenarios:
            missing_names = ", ".join(sorted(missing_scenarios))
            raise ValueError(f"Missing required LLM selections: {missing_names}")

        seen_provider_types: set[str] = set()
        for provider in self.providers.values():
            provider_type = str(
                getattr(provider.provider_type, "value", provider.provider_type)
            )
            if provider_type == LLMProvider.CUSTOM.value:
                continue
            if provider_type in seen_provider_types:
                raise ValueError(f"Duplicate built-in LLM provider type: {provider_type}")
            seen_provider_types.add(provider_type)
        return self


# =============================================================================
# Agent Configuration
# =============================================================================

class EmbeddingSettings(BaseModel):
    """Embedding configuration. Note: embedding model is configured via LLM EMBEDDING scenario."""
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.SQLITE_VEC)


class MemorySettings(BaseModel):
    """Memory configuration."""
    db_path: str = Field(default="~/.magi/data/memories")
    retention_days: int = Field(default=7, ge=1)

    enable_l0: bool = Field(default=True)
    enable_l1: bool = Field(default=True)
    enable_l2: bool = Field(default=True)
    enable_l3: bool = Field(default=True)
    enable_l4: bool = Field(default=True)
    l0_checkpoint_interval_seconds: int = Field(default=30, ge=1)
    runtime_replay_include_l0_only: bool = Field(default=False)
    enable_t1_importance: bool = Field(default=True)
    enable_l2_llm_extraction: bool = Field(default=True)
    enable_l3_llm_summary: bool = Field(default=True)
    enable_l4_skill_extraction: bool = Field(default=True)

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
    max_queue_size: int = Field(default=1000, ge=1)
    num_workers: int = Field(default=4, ge=1)
    db_path: str = Field(default="~/.magi/data/message_queue.db")
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


class TimelineSourceSettings(BaseModel):
    """Per-source timeline ingestion settings."""

    enabled: bool = Field(default=True)
    sync_mode: TimelineSyncMode = Field(default=TimelineSyncMode.INTERVAL)
    sync_interval_minutes: int = Field(default=15, ge=1)
    default_retention_mode: TimelineRetentionMode = Field(default=TimelineRetentionMode.ANALYZE_ONLY)
    storage_mode: TimelineStorageMode = Field(default=TimelineStorageMode.MANAGED)
    source_path: Optional[str] = Field(default=None)
    fetch_page_content: bool = Field(default=False)
    edge_whitelist: List[str] = Field(default_factory=list)


class TimelineSourcesSettings(BaseModel):
    """Timeline source collection settings."""

    chat: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            sync_mode=TimelineSyncMode.WATCH,
            sync_interval_minutes=1,
            default_retention_mode=TimelineRetentionMode.ANALYZE_ONLY,
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH"],
        )
    )
    manual_journal: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            sync_mode=TimelineSyncMode.MANUAL,
            sync_interval_minutes=1,
            default_retention_mode=TimelineRetentionMode.RETAIN_RAW,
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO"],
        )
    )
    browser_history: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            sync_mode=TimelineSyncMode.INTERVAL,
            sync_interval_minutes=30,
            default_retention_mode=TimelineRetentionMode.ANALYZE_ONLY,
            edge_whitelist=["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
        )
    )
    photo_library: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            sync_mode=TimelineSyncMode.INTERVAL,
            sync_interval_minutes=60,
            default_retention_mode=TimelineRetentionMode.RETAIN_RAW,
            storage_mode=TimelineStorageMode.EXTERNAL_REFERENCE,
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )


class TimelineSettings(BaseModel):
    """Timeline domain settings."""

    enabled: bool = Field(default=True)
    expert_mode_edge_override: bool = Field(default=True)
    sources: TimelineSourcesSettings = Field(default_factory=TimelineSourcesSettings)


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
    reload: bool = Field(default=True)
    debug: bool = Field(default=False)
    desktop_session_token: str = Field(default="")
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
    skills: List[str] = Field(default_factory=list)


# =============================================================================
# Other Settings
# =============================================================================

class PluginSettings(BaseModel):
    """Per-plugin persisted runtime state."""

    enabled: bool = Field(default=False)
    trusted: bool = Field(default=False)
    settings: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = Field(default=None)
    manifest_path: Optional[str] = Field(default=None)


class PluginsSettings(BaseModel):
    """Unified plugin runtime configuration."""

    scan_paths: List[str] = Field(default_factory=lambda: ["plugins", "~/.magi/plugins"])
    packages: Dict[str, PluginSettings] = Field(
        default_factory=lambda: {
            "core-tools": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "core-timeline": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "core-actions": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "chrome-history": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
        }
    )


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
    timeline: TimelineSettings = Field(default_factory=TimelineSettings)
    plugins: PluginsSettings = Field(default_factory=PluginsSettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")


# Type alias for backward compatibility
Config = AppConfig
