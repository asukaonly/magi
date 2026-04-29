"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in backend/configs/config.example.yaml.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, model_validator
from enum import Enum

from .llm_models import (
    LLMCapabilitiesSettings,
    LLMCapabilityOverridesSettings,
    LLMConcurrencyOverrideSettings,
    LLMLimitsOverrideSettings,
    LLMLimitsSettings,
    LLMModelMetadataOverrideSettings,
    LLMProvider,
    LLMProviderSettings,
    LLMScenario,
    LLMSelectionLimitsSettings,
    LLMSelectionSettings,
    LLMSettings,
    ThinkingDepth,
)


class MemoryBackend(str, Enum):
    """Memory storage backend type."""
    MEMORY = "memory"
    CHROMADB = "chromadb"
    FAISS = "faiss"


class EmbeddingBackend(str, Enum):
    """Embedding vector backend type."""
    SQLITE_VEC = "sqlite_vec"
    OPENAI = "openai"


class EmbeddingMode(str, Enum):
    """Embedding execution mode."""
    OFF = "off"
    REMOTE = "remote"
    LOCAL = "local"


class LocalEmbeddingModelSource(str, Enum):
    """How a local embedding model is referenced."""
    MANAGED = "managed"
    EXTERNAL = "external"


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


class EmbeddingSettings(BaseModel):
    """Embedding configuration. Note: embedding model is configured via LLM EMBEDDING scenario."""
    backend: EmbeddingBackend = Field(default=EmbeddingBackend.SQLITE_VEC)
    mode: EmbeddingMode = Field(default=EmbeddingMode.OFF)
    local: "LocalEmbeddingSettings" = Field(default_factory=lambda: LocalEmbeddingSettings())


class LocalEmbeddingSettings(BaseModel):
    """Local ONNX embedding model settings."""

    model_source: LocalEmbeddingModelSource = Field(default=LocalEmbeddingModelSource.MANAGED)
    managed_model_id: Optional[str] = Field(default=None)
    model_dir_path: Optional[str] = Field(default=None)
    idle_timeout_seconds: int = Field(default=1800, ge=60)


class MemoryHistoryBehavior(str, Enum):
    """Retention behavior for historical memory once it ages out of the hot path."""

    DELETE = "delete"
    ARCHIVE = "archive"


class MemoryL0Settings(BaseModel):
    """L0 working-memory settings."""

    enabled: bool = Field(default=True)
    checkpoint_interval_seconds: int = Field(default=30, ge=1)


class MemoryL1Settings(BaseModel):
    """L1 long-term event memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)


class MemoryL2Settings(BaseModel):
    """L2 structured cognition settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    batch_flush_interval_seconds: int = Field(default=60, ge=30)
    auto_extract_relations: bool = Field(default=True)
    conflict_arbitration_enabled: bool = Field(default=True)
    conflict_arbitration_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    maintenance_enabled: bool = Field(
        default=True,
        description="Register periodic L2 entity/graph maintenance with the runtime scheduler.",
    )
    maintenance_interval_seconds: float = Field(
        default=86_400.0,
        ge=300.0,
        description="Interval between L2 maintenance runs (seconds). Minimum 300 to avoid excessive load.",
    )
    maintenance_min_mentions: int = Field(
        default=2,
        ge=1,
        description="Orphan prune keeps entities with at least this many resolved mentions (unless referenced in graph).",
    )


class MemoryL3Settings(BaseModel):
    """L3 reflection-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)


class MemoryL4Settings(BaseModel):
    """L4 procedural-memory settings."""

    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    strategy_extraction_threshold: int = Field(
        default=5,
        description="Number of new traces before triggering LLM strategy extraction.",
    )


class CrossEncoderSettings(BaseModel):
    """Cross-encoder reranker model settings."""

    enabled: bool = Field(default=False)
    managed_model_id: Optional[str] = Field(default=None)


class MemoryRerankerSettings(BaseModel):
    """Retrieval reranker settings.

    Heuristic reranking is always active. The cross-encoder is an optional
    second stage that adds semantic relevance scoring on top of heuristic
    metadata adjustments.
    """

    top_k: int = Field(default=8, ge=1)
    cross_encoder: CrossEncoderSettings = Field(default_factory=CrossEncoderSettings)


class QueryExpansionSettings(BaseModel):
    """LLM-based query expansion settings for retrieval."""

    enabled: bool = Field(default=True)


class GraphSpreadingSettings(BaseModel):
    """Graph spreading activation settings for L2 knowledge graph BFS."""

    enabled: bool = Field(default=False)


class EntitySemanticEdgeSettings(BaseModel):
    """Entity-scoped semantic edge builder settings."""

    enabled: bool = Field(default=False)


class MemorySettings(BaseModel):
    """Memory configuration."""
    db_path: str = Field(default="~/.magi/data/memory")
    retention_days: int = Field(default=90, ge=1)
    history_behavior: MemoryHistoryBehavior = Field(default=MemoryHistoryBehavior.DELETE)
    async_embeddings: bool = Field(default=True)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    reranker: MemoryRerankerSettings = Field(default_factory=MemoryRerankerSettings)
    query_expansion: QueryExpansionSettings = Field(default_factory=QueryExpansionSettings)
    graph_spreading: GraphSpreadingSettings = Field(default_factory=GraphSpreadingSettings)
    entity_semantic_edges: EntitySemanticEdgeSettings = Field(default_factory=EntitySemanticEdgeSettings)
    l0: MemoryL0Settings = Field(default_factory=MemoryL0Settings)
    l1: MemoryL1Settings = Field(default_factory=MemoryL1Settings)
    l2: MemoryL2Settings = Field(default_factory=MemoryL2Settings)
    l3: MemoryL3Settings = Field(default_factory=MemoryL3Settings)
    l4: MemoryL4Settings = Field(default_factory=MemoryL4Settings)

    @model_validator(mode="after")
    def enforce_fixed_vector_runtime(self) -> "MemorySettings":
        """Keep vector processing on the fixed async sqlite runtime path."""
        self.async_embeddings = True
        self.embedding.backend = EmbeddingBackend.SQLITE_VEC
        return self


class PersonalitySettings(BaseModel):
    """Personality configuration."""
    name: str = Field(default="default")
    path: str = Field(default="~/.magi/personalities")
    enable_evolution: bool = Field(default=True)
    enable_state_memory: bool = Field(default=True)
    enable_state_transition: bool = Field(default=True)
    enable_deep_persona: bool = Field(default=True)

    @model_validator(mode="after")
    def normalize_runtime_feature_dependencies(self) -> "PersonalitySettings":
        """Keep persona sub-features disabled when state memory is off."""
        self.enable_evolution = bool(self.enable_state_memory)
        if not self.enable_state_memory:
            self.enable_state_transition = False
            self.enable_deep_persona = False
        return self


class MessageBusSettings(BaseModel):
    """Message bus configuration."""
    max_queue_size: int = Field(default=1000, ge=1)
    num_workers: int = Field(default=4, ge=1)
    broadcast_max_concurrency: int = Field(default=8, ge=1)
    handler_timeout_seconds: float = Field(default=2.0, ge=0.1)


class MaintenanceSettings(BaseModel):
    """Maintenance daemon configuration."""
    enabled: bool = Field(default=True, description="Enable maintenance daemon")
    interval_seconds: float = Field(default=300.0, ge=10.0, description="Interval between maintenance runs")
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


class BackgroundTasksSettings(BaseModel):
    """Background-task subsystem configuration.

    Controls the detach-and-run pipeline that lets a chat session spawn
    long-running work without blocking the foreground turn loop. The
    ``enabled`` flag is a hard kill-switch: when ``false`` the dispatcher
    short-circuits to a foreground decision and the manager is still
    constructed but never receives work.
    """

    enabled: bool = Field(default=True, description="Feature flag; default on.")
    max_concurrent: int = Field(default=2, ge=1, description="Hard cap on simultaneously running tasks.")
    queue_when_full: bool = Field(
        default=True,
        description="Queue tasks when at cap; when false, falls back to foreground.",
    )
    auto_detect_long_task: bool = Field(
        default=True,
        description="Enable the dispatcher's LLM classifier fallback.",
    )
    auto_detect_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum classifier confidence to pick background.",
    )
    default_task_timeout_seconds: int = Field(
        default=1800,
        ge=60,
        description="Wall-clock timeout applied to each attempt.",
    )
    history_retention_days: int = Field(
        default=30,
        ge=1,
        description="How long terminal rows are kept for the history tab.",
    )


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

    photo_library: TimelineSourceSettings = Field(
        default_factory=lambda: TimelineSourceSettings(
            enabled=False,
            sync_mode=TimelineSyncMode.MANUAL,
            sync_interval_minutes=60,
            default_retention_mode=TimelineRetentionMode.ANALYZE_ONLY,
            storage_mode=TimelineStorageMode.EXTERNAL_REFERENCE,
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )


class TimelineSettings(BaseModel):
    """Timeline domain settings."""

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
    background_tasks: BackgroundTasksSettings = Field(default_factory=BackgroundTasksSettings)


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
    registry_url: Optional[str] = Field(default=None)
    packages: Dict[str, PluginSettings] = Field(
        default_factory=lambda: {
            "core-tools": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "photo-library": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "chrome-history": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "calendar": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "git-activity": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "screen-time": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
            "terminal-history": PluginSettings(
                enabled=True,
                trusted=True,
                source="builtin",
            ),
        }
    )


# =============================================================================
# Network Proxy
# =============================================================================

class ProxyType(str, Enum):
    """Supported network proxy types."""
    HTTP = "http"
    SOCKS5 = "socks5"


class NetworkProxySettings(BaseModel):
    """Network proxy configuration.

    When ``enabled`` is False (the default), the application ignores system
    proxy settings and connects directly.  When enabled, all outbound LLM
    requests are routed through the configured proxy.
    """

    enabled: bool = Field(default=False)
    proxy_type: ProxyType = Field(default=ProxyType.HTTP)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7890, ge=1, le=65535)

    def proxy_url(self) -> str | None:
        """Build proxy URL string, or ``None`` when disabled."""
        if not self.enabled:
            return None
        scheme = "socks5" if self.proxy_type == ProxyType.SOCKS5 else "http"
        return f"{scheme}://{self.host}:{self.port}"


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
    network: NetworkProxySettings = Field(default_factory=NetworkProxySettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")


# Type alias for backward compatibility
Config = AppConfig
