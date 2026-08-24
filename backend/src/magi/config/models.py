"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in backend/configs/config.example.yaml.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, model_validator
from enum import Enum
from urllib.parse import quote

from .constants import DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS
from .memory_models import (
    CrossEncoderSettings as CrossEncoderSettings,
    EmbeddingBackend as EmbeddingBackend,
    EmbeddingMode as EmbeddingMode,
    EmbeddingSettings as EmbeddingSettings,
    EntitySemanticEdgeSettings as EntitySemanticEdgeSettings,
    GraphSpreadingSettings as GraphSpreadingSettings,
    LocalEmbeddingModelSource as LocalEmbeddingModelSource,
    LocalEmbeddingSettings as LocalEmbeddingSettings,
    MemoryBackend as MemoryBackend,
    MemoryHistoryBehavior as MemoryHistoryBehavior,
    MemoryL0Settings as MemoryL0Settings,
    MemoryL1Settings as MemoryL1Settings,
    MemoryL2AssertionSettings as MemoryL2AssertionSettings,
    MemoryL2ConfidenceSettings as MemoryL2ConfidenceSettings,
    MemoryL2EpisodeSettings as MemoryL2EpisodeSettings,
    MemoryL2ExperienceSettings as MemoryL2ExperienceSettings,
    MemoryL2LifecycleSettings as MemoryL2LifecycleSettings,
    MemoryL2LimitsSettings as MemoryL2LimitsSettings,
    MemoryL2Settings as MemoryL2Settings,
    MemoryL3Settings as MemoryL3Settings,
    MemoryL4Settings as MemoryL4Settings,
    MemoryRerankerSettings as MemoryRerankerSettings,
    MemorySettings,
    QueryExpansionSettings as QueryExpansionSettings,
)
from .plugin_models import (
    PluginSettings as PluginSettings,
    PluginsSettings,
)


class LLMProvider(str, Enum):
    """LLM provider type."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    GEMINI = "gemini"
    GROK = "grok"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    KIMI = "kimi"
    MINIMAX = "minimax"
    XIAOMIMIMO = "xiaomimimo"
    LOCAL = "local"
    CUSTOM = "custom"


class ModelVendor(str, Enum):
    """The behavioral vendor a model belongs to.

    ``provider`` is *who hosts the endpoint* (which can be an OneAPI-style
    gateway). ``vendor`` is *who built the model* and therefore decides
    payload shape: how reasoning is expressed, how tool-calling is
    serialized, where system prompts live, etc.

    A single OneAPI gateway may proxy ``glm-4-plus`` (vendor=GLM),
    ``qwen-max`` (vendor=DASHSCOPE), and ``claude-sonnet-4-6``
    (vendor=ANTHROPIC) under the same ``provider``. Routing dialects off
    provider name would misroute each of these; routing off vendor is
    correct.

    ``GENERIC`` means "OpenAI-compatible transport, no vendor-specific
    extensions"; reasoning / thinking knobs are not injected.
    """

    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    DASHSCOPE = "dashscope"
    GROK = "grok"
    GEMINI = "gemini"
    KIMI = "kimi"
    MINIMAX = "minimax"
    GENERIC = "generic"


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


class LLMCapabilityOverridesSettings(BaseModel):
    """Per-model capability overrides applied on top of registry metadata."""

    vision: Optional[bool] = Field(default=None)
    image_output: Optional[bool] = Field(default=None)
    tool_calling: Optional[bool] = Field(default=None)
    reasoning: Optional[bool] = Field(default=None)
    embedding: Optional[bool] = Field(default=None)


class LLMLimitsOverrideSettings(BaseModel):
    """Per-model numeric limit overrides applied on top of registry metadata."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class LLMModelCostModel(BaseModel):
    """Provider-published pricing metadata for a model."""

    currency: str = Field(default="USD")
    input_per_million_tokens: Optional[float] = Field(default=None, ge=0)
    cached_input_per_million_tokens: Optional[float] = Field(default=None, ge=0)
    cache_write_per_million_tokens: Optional[float] = Field(default=None, ge=0)
    output_per_million_tokens: Optional[float] = Field(default=None, ge=0)
    per_image: Optional[float] = Field(default=None, ge=0)
    source: Optional[str] = Field(default=None)
    source_note: Optional[str] = Field(default=None)


class LLMModelMetadataOverrideSettings(BaseModel):
    """User-defined metadata override for any provider model."""

    label: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    vendor: Optional[ModelVendor] = Field(
        default=None,
        description=(
            "Behavioral vendor override. Set this on custom-gateway models "
            "(OneAPI etc.) so the runtime picks the correct reasoning / "
            "tool-calling payload shape rather than guessing from URL."
        ),
    )
    capabilities: LLMCapabilityOverridesSettings = Field(
        default_factory=LLMCapabilityOverridesSettings
    )
    limits: LLMLimitsOverrideSettings = Field(default_factory=LLMLimitsOverrideSettings)
    input_modalities: Optional[List[str]] = Field(default=None)
    output_modalities: Optional[List[str]] = Field(default=None)
    provider_options_example: Optional[Dict[str, Any]] = Field(default=None)
    cost: Optional[LLMModelCostModel] = Field(default=None)
    hidden: Optional[bool] = Field(default=None)
    preferred: Optional[bool] = Field(default=None)
    source_note: Optional[str] = Field(default=None)
    dimensions: Optional[List[int]] = Field(default=None)


class LLMSelectionLimitsSettings(BaseModel):
    """Per-scenario numeric limits that remain local to scenario selection."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class LLMConcurrencyOverrideSettings(BaseModel):
    """Shared concurrency override for a concrete provider-model family."""

    max_concurrency: Optional[int] = Field(default=None, ge=1)


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


class ThinkingDepth(str, Enum):
    """Reasoning effort level requested by a caller for a single LLM call.

    This is orthogonal to LLMScenario: the scenario selects which model to
    use, while ThinkingDepth controls how hard the model should reason on
    this particular invocation.  Provider adapters map these levels to
    vendor-specific APIs (e.g. OpenAI reasoning_effort, Anthropic thinking
    budget, GLM thinking toggle).
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class LLMScenario(str, Enum):
    """Supported runtime LLM scenarios."""

    CONTEXT_COMPACT = "context_compact"
    AUXILIARY = "auxiliary"
    CORE = "core"
    MEMORY_SUMMARIZER = "memory_summarizer"
    EMBEDDING = "embedding"
    IMAGE_GENERATION = "image_generation"
    TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"


class LLMProviderConnectionSettings(BaseModel):
    """Connection settings for one provider-backed service."""

    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)


class LLMProviderImageGenerationSettings(LLMProviderConnectionSettings):
    """Provider-specific image generation service settings."""

    enabled: bool = Field(default=False)
    timeout: int = Field(default=180, ge=1)
    native_protocol: Optional[str] = Field(default=None)


class LLMProviderTTSSettings(LLMProviderConnectionSettings):
    """Provider-specific speech generation service settings."""

    enabled: bool = Field(default=False)
    model: Optional[str] = Field(default=None)
    voice: Optional[str] = Field(default=None)
    response_format: Optional[str] = Field(default=None)


class LLMProviderServicesSettings(BaseModel):
    """Service-specific provider configuration."""

    chat: LLMProviderConnectionSettings = Field(default_factory=LLMProviderConnectionSettings)
    embedding: LLMProviderConnectionSettings = Field(default_factory=LLMProviderConnectionSettings)
    image_generation: LLMProviderImageGenerationSettings = Field(
        default_factory=LLMProviderImageGenerationSettings
    )
    tts: LLMProviderTTSSettings = Field(default_factory=LLMProviderTTSSettings)


class LLMProviderSettings(BaseModel):
    """Reusable provider instance settings."""

    enabled: bool = Field(default=True)
    provider_type: LLMProvider = Field(default=LLMProvider.OPENAI)
    display_name: str = Field(default="OpenAI")
    provider_plan: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    services: LLMProviderServicesSettings = Field(default_factory=LLMProviderServicesSettings)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)
    model_metadata_overrides: Dict[str, LLMModelMetadataOverrideSettings] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_custom_model_defaults(self) -> "LLMProviderSettings":
        if self.provider_type == LLMProvider.CUSTOM:
            if self.custom_default_model and self.custom_default_model not in self.custom_models:
                raise ValueError("Custom default model must exist in custom_models")
        return self


class LLMSelectionSettings(BaseModel):
    """Per-scenario model selection."""

    provider_id: str = Field(default="")
    model: str = Field(default="")
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMSelectionLimitsSettings = Field(default_factory=LLMSelectionLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    """Scenario-based LLM configuration."""

    providers: Dict[str, LLMProviderSettings] = Field(default_factory=dict)
    selections: Dict[str, LLMSelectionSettings] = Field(
        default_factory=lambda: {
            LLMScenario.AUXILIARY.value: LLMSelectionSettings(),
            LLMScenario.CORE.value: LLMSelectionSettings(),
            LLMScenario.MEMORY_SUMMARIZER.value: LLMSelectionSettings(),
            LLMScenario.EMBEDDING.value: LLMSelectionSettings(
                capabilities=LLMCapabilitiesSettings(embedding=True),
            ),
            LLMScenario.IMAGE_GENERATION.value: LLMSelectionSettings(
                capabilities=LLMCapabilitiesSettings(image_output=True),
            ),
        }
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=MIN_MAX_TOKENS)
    timeout: int = Field(default=60, ge=1)
    model_runtime_overrides: Dict[str, LLMConcurrencyOverrideSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_selections(self) -> "LLMSettings":
        # EMBEDDING is optional - system falls back to local model if not configured
        required_scenarios = {
            LLMScenario.CORE.value,
        }
        missing_scenarios = required_scenarios.difference(self.selections.keys())
        if missing_scenarios:
            missing_names = ", ".join(sorted(missing_scenarios))
            raise ValueError(f"Missing required LLM selections: {missing_names}")

        return self


# =============================================================================
# Agent Configuration
# =============================================================================


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
    interval_seconds: float = Field(
        default=300.0, ge=10.0, description="Interval between maintenance runs"
    )
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


class BackgroundTasksSettings(BaseModel):
    """Background-task subsystem configuration.

    Controls the detach-and-run pipeline that lets a chat session spawn
    long-running work without blocking the foreground turn loop. The
    ``enabled`` flag is a hard kill-switch: when ``false`` the dispatcher
    short-circuits to a foreground decision and the manager is still
    constructed but never receives work.
    """

    enabled: bool = Field(default=True, description="Feature flag; default on.")
    max_concurrent: int = Field(
        default=2, ge=1, description="Hard cap on simultaneously running tasks."
    )
    queue_when_full: bool = Field(
        default=True,
        description="Queue tasks when at cap; when false, falls back to foreground.",
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
    default_retention_mode: TimelineRetentionMode = Field(
        default=TimelineRetentionMode.ANALYZE_ONLY
    )
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
    default_provider: str = Field(default="openmeteo")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "openmeteo": ProviderConfig(),
            "qweather": ProviderConfig(),
        }
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
            "searxng": ProviderConfig(),
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
    allow_rfc2544_benchmark_range: bool = Field(default=True)
    allow_private_network: bool = Field(default=False)
    private_network_allowlist: List[str] = Field(default_factory=list)
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
    username: str = Field(default="")
    password: str = Field(default="")

    def proxy_url(self) -> str | None:
        """Build proxy URL string, or ``None`` when disabled."""
        if not self.enabled:
            return None
        scheme = "socks5" if self.proxy_type == ProxyType.SOCKS5 else "http"
        username = self.username.strip()
        password = self.password.strip()
        auth = ""
        if username:
            auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
        return f"{scheme}://{auth}{self.host}:{self.port}"


# =============================================================================
# Diagnostics
# =============================================================================


class DiagnosticsSettings(BaseModel):
    """Local diagnostic logging policy."""

    full_content_logging_enabled: bool = Field(default=True)


# =============================================================================
# Data Lifecycle Configuration
# =============================================================================


class RuntimeTraceLifecycleSettings(BaseModel):
    """Retention policy for runtime trace and notification rows."""

    raw_retention_days: int = Field(default=7, ge=1)
    notifications_retention_days: int = Field(default=7, ge=1)
    plugin_ingress_retention_days: int = Field(default=7, ge=1)
    user_notifications_retention_days: int = Field(default=30, ge=1)


class LLMCacheObservabilitySettings(BaseModel):
    """Lightweight prompt-cache diagnostics policy."""

    enabled: bool = Field(default=True)
    retention_days: int = Field(default=30, ge=1)
    max_rows: int = Field(default=50_000, ge=1)
    store_tool_names: bool = Field(default=True)


class LLMUsageLifecycleSettings(BaseModel):
    """Retention, rollup, and diagnostics policy for LLM usage rows."""

    raw_retention_days: int = Field(default=7, ge=1)
    rollup_retention_days: int = Field(default=180, ge=1)
    rollup_granularity: str = Field(default="day")
    cache_observability: LLMCacheObservabilitySettings = Field(
        default_factory=LLMCacheObservabilitySettings
    )


class MessageQueueCompletedLifecycleSettings(BaseModel):
    """Lifecycle policy for completed runtime command rows."""

    raw_retention_hours: int = Field(default=24, ge=1)
    rollup_retention_days: int = Field(default=30, ge=1)
    rollup_granularity: str = Field(default="hour")


class MessageQueueFailedLifecycleSettings(BaseModel):
    """Lifecycle policy for failed runtime command rows."""

    raw_retention_days: int = Field(default=7, ge=1)


class MessageQueueLifecycleSettings(BaseModel):
    """Lifecycle policy for runtime command queue history."""

    completed: MessageQueueCompletedLifecycleSettings = Field(
        default_factory=MessageQueueCompletedLifecycleSettings
    )
    failed: MessageQueueFailedLifecycleSettings = Field(
        default_factory=MessageQueueFailedLifecycleSettings
    )


class SchedulerHistoryLifecycleSettings(BaseModel):
    """Retention policy for scheduler history tables."""

    success_retention_days: int = Field(default=30, ge=1)
    failed_retention_days: int = Field(default=60, ge=1)


class SchedulerLifecycleSettings(BaseModel):
    """Lifecycle policy for scheduler operational history."""

    executions: SchedulerHistoryLifecycleSettings = Field(
        default_factory=SchedulerHistoryLifecycleSettings
    )
    sensor_sync_jobs: SchedulerHistoryLifecycleSettings = Field(
        default_factory=SchedulerHistoryLifecycleSettings
    )


class SensorStateLifecycleSettings(BaseModel):
    """Lifecycle policy for sensor runtime state."""

    fingerprints_keep_latest: int = Field(default=10000, ge=1)


class ChatAssetsLifecycleSettings(BaseModel):
    """Lifecycle policy for managed chat attachment resources."""

    delete_on_session_delete: bool = Field(default=True)
    orphan_grace_hours: int = Field(default=24, ge=0)


class EphemeralJobsLifecycleSettings(BaseModel):
    """Lifecycle policy for in-memory pollable job snapshots."""

    personality_generation_ttl_seconds: int = Field(default=1800, ge=60)


class LifecycleSettings(BaseModel):
    """Local data lifecycle and cleanup policy."""

    runtime_trace: RuntimeTraceLifecycleSettings = Field(
        default_factory=RuntimeTraceLifecycleSettings
    )
    llm_usage: LLMUsageLifecycleSettings = Field(default_factory=LLMUsageLifecycleSettings)
    message_queue: MessageQueueLifecycleSettings = Field(
        default_factory=MessageQueueLifecycleSettings
    )
    scheduler: SchedulerLifecycleSettings = Field(default_factory=SchedulerLifecycleSettings)
    sensor_state: SensorStateLifecycleSettings = Field(default_factory=SensorStateLifecycleSettings)
    chat_assets: ChatAssetsLifecycleSettings = Field(default_factory=ChatAssetsLifecycleSettings)
    ephemeral_jobs: EphemeralJobsLifecycleSettings = Field(
        default_factory=EphemeralJobsLifecycleSettings
    )


# =============================================================================
# Root Configuration
# =============================================================================


class AppConfig(BaseModel):
    """Root application configuration."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    tools: ToolsSettings = Field(default_factory=ToolsSettings)
    timeline: TimelineSettings = Field(default_factory=TimelineSettings)
    plugins: PluginsSettings = Field(default_factory=PluginsSettings)
    network: NetworkProxySettings = Field(default_factory=NetworkProxySettings)
    diagnostics: DiagnosticsSettings = Field(default_factory=DiagnosticsSettings)
    lifecycle: LifecycleSettings = Field(default_factory=LifecycleSettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
