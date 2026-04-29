"""
Configuration Models - Pydantic model definitions for application configuration.

These models match the structure in backend/configs/config.example.yaml.
"""
from pydantic import BaseModel, Field

from .agent_models import (
    AgentSettings,
    BackgroundTasksSettings,
    MaintenanceSettings,
    MessageBusSettings,
    PersonalitySettings,
    RuntimeSettings,
)
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
from .memory_models import (
    CrossEncoderSettings,
    EmbeddingBackend,
    EmbeddingMode,
    EmbeddingSettings,
    EntitySemanticEdgeSettings,
    GraphSpreadingSettings,
    LocalEmbeddingModelSource,
    LocalEmbeddingSettings,
    MemoryBackend,
    MemoryHistoryBehavior,
    MemoryL0Settings,
    MemoryL1Settings,
    MemoryL2Settings,
    MemoryL3Settings,
    MemoryL4Settings,
    MemoryRerankerSettings,
    MemorySettings,
    QueryExpansionSettings,
)
from .network_models import NetworkProxySettings, ProxyType
from .plugin_models import PluginSettings, PluginsSettings
from .server_models import FeatureFlags, ServerSettings
from .timeline_models import (
    TimelineRetentionMode,
    TimelineSettings,
    TimelineSourceSettings,
    TimelineSourcesSettings,
    TimelineStorageMode,
    TimelineSyncMode,
)
from .tools_models import (
    ProviderConfig,
    ToolsSettings,
    WeatherToolSettings,
    WebFetchToolSettings,
    WebSearchToolSettings,
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
    network: NetworkProxySettings = Field(default_factory=NetworkProxySettings)
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")


# Type alias for backward compatibility
Config = AppConfig
