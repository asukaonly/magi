"""Pydantic schemas for the system configuration API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...config.models import (
    LLMCapabilitiesSettings,
    LLMConcurrencyOverrideSettings,
    LLMModelMetadataOverrideSettings,
    LLMSelectionLimitsSettings,
)
from ...system_suggestions.contracts import DismissalRecord
from .personality_config_schemas import PersonalityConfigModel as FullPersonalityConfigModel


class BackgroundTasksConfigModel(BaseModel):
    auto_detect_long_task: bool = Field(default=False)


class AgentConfigModel(BaseModel):
    name: str = Field(default="magi-agent")
    description: Optional[str] = Field(default="Magi AI Agent Framework")
    background_tasks: BackgroundTasksConfigModel = Field(default_factory=BackgroundTasksConfigModel)


class LLMProviderConnectionConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)


class LLMProviderImageGenerationConfigModel(LLMProviderConnectionConfigModel):
    enabled: bool = Field(default=False)
    timeout: int = Field(default=180, ge=1)
    native_protocol: Optional[str] = Field(default=None)


class LLMProviderTTSConfigModel(LLMProviderConnectionConfigModel):
    enabled: bool = Field(default=False)
    model: Optional[str] = Field(default=None)
    voice: Optional[str] = Field(default=None)
    response_format: Optional[str] = Field(default=None)


class LLMProviderServicesConfigModel(BaseModel):
    chat: LLMProviderConnectionConfigModel = Field(default_factory=LLMProviderConnectionConfigModel)
    embedding: LLMProviderConnectionConfigModel = Field(
        default_factory=LLMProviderConnectionConfigModel
    )
    image_generation: LLMProviderImageGenerationConfigModel = Field(
        default_factory=LLMProviderImageGenerationConfigModel
    )
    tts: LLMProviderTTSConfigModel = Field(default_factory=LLMProviderTTSConfigModel)


class LLMProviderConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider_type: str = Field(default="openai")
    display_name: str = Field(default="OpenAI")
    provider_plan: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    services: LLMProviderServicesConfigModel = Field(default_factory=LLMProviderServicesConfigModel)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)
    model_metadata_overrides: Dict[str, LLMModelMetadataOverrideSettings] = Field(
        default_factory=dict
    )


class LLMSelectionConfigModel(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMSelectionLimitsSettings = Field(default_factory=LLMSelectionLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMConfigModel(BaseModel):
    providers: Dict[str, LLMProviderConfigModel] = Field(default_factory=dict)
    selections: Dict[str, LLMSelectionConfigModel] = Field(
        default_factory=lambda: {
            "context_decider": LLMSelectionConfigModel(),
            "core": LLMSelectionConfigModel(),
            "memory_summarizer": LLMSelectionConfigModel(),
            "embedding": LLMSelectionConfigModel(
                capabilities=LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=False,
                    reasoning=False,
                    embedding=True,
                ),
            ),
            "image_generation": LLMSelectionConfigModel(
                capabilities=LLMCapabilitiesSettings(
                    vision=False,
                    image_output=True,
                    tool_calling=False,
                    reasoning=False,
                    embedding=False,
                ),
            ),
        }
    )
    model_runtime_overrides: Dict[str, LLMConcurrencyOverrideSettings] = Field(default_factory=dict)


class MemoryL0ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    checkpoint_interval_seconds: int = Field(default=30, ge=1)
    attention_update_turn_threshold: int = Field(default=3, ge=1, le=20)
    attention_update_idle_seconds: int = Field(default=30, ge=1, le=300)
    attention_update_max_delay_seconds: int = Field(default=90, ge=1, le=600)

    @model_validator(mode="after")
    def validate_attention_update_delays(self) -> "MemoryL0ConfigModel":
        """Keep the hard update deadline at or beyond the idle deadline."""
        if self.attention_update_max_delay_seconds < self.attention_update_idle_seconds:
            raise ValueError(
                "attention_update_max_delay_seconds must be greater than or equal to "
                "attention_update_idle_seconds"
            )
        return self


class MemoryL1ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    retention_days: int = Field(default=30, ge=1)
    vectors_enabled: bool = Field(default=True)


class MemoryL2ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    batch_flush_interval_seconds: int = Field(default=60, ge=30)
    auto_extract_relations: bool = Field(default=True)
    conflict_arbitration_enabled: bool = Field(default=True)
    conflict_arbitration_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    shadow_conflict_notification_enabled: bool = Field(default=True)
    portrait_projection_refresh_delay_seconds: float = Field(default=120.0, ge=0.0)


class MemoryL3ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    retention_days: int = Field(default=180, ge=1)
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)


class MemoryL4ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    inactive_skill_retention_days: int = Field(default=30, ge=1)
    inactive_skill_min_attempts: int = Field(default=5, ge=1)


class CrossEncoderConfigModel(BaseModel):
    enabled: bool = Field(default=False)
    managed_model_id: Optional[str] = Field(default=None)


class MemoryRerankerConfigModel(BaseModel):
    top_k: int = Field(default=8, ge=1)
    cross_encoder: CrossEncoderConfigModel = Field(default_factory=CrossEncoderConfigModel)


class EmbeddingLocalConfigModel(BaseModel):
    model_source: str = Field(default="managed")
    managed_model_id: Optional[str] = Field(default=None)
    model_dir_path: Optional[str] = Field(default=None)
    idle_timeout_seconds: int = Field(default=1800, ge=60)
    variant: Optional[str] = Field(default=None)


class EmbeddingConfigModel(BaseModel):
    mode: str = Field(default="remote")
    local: EmbeddingLocalConfigModel = Field(default_factory=EmbeddingLocalConfigModel)


class QueryExpansionConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    max_expansions: int = Field(default=2, ge=1, le=5)


class GraphSpreadingConfigModel(BaseModel):
    enabled: bool = Field(default=True)


class EntitySemanticEdgeConfigModel(BaseModel):
    enabled: bool = Field(default=False)


class MemoryConfigModel(BaseModel):
    db_path: Optional[str] = Field(default="~/.magi/data/memory")
    retention_days: int = Field(default=90, ge=1)
    history_behavior: str = Field(default="delete")
    archive_path: Optional[str] = Field(default="~/.magi/data/memory/archive")
    embedding: EmbeddingConfigModel = Field(default_factory=EmbeddingConfigModel)
    reranker: MemoryRerankerConfigModel = Field(default_factory=MemoryRerankerConfigModel)
    query_expansion: QueryExpansionConfigModel = Field(default_factory=QueryExpansionConfigModel)
    graph_spreading: GraphSpreadingConfigModel = Field(default_factory=GraphSpreadingConfigModel)
    entity_semantic_edges: EntitySemanticEdgeConfigModel = Field(
        default_factory=EntitySemanticEdgeConfigModel
    )
    l0: MemoryL0ConfigModel = Field(default_factory=MemoryL0ConfigModel)
    l1: MemoryL1ConfigModel = Field(default_factory=MemoryL1ConfigModel)
    l2: MemoryL2ConfigModel = Field(default_factory=MemoryL2ConfigModel)
    l3: MemoryL3ConfigModel = Field(default_factory=MemoryL3ConfigModel)
    l4: MemoryL4ConfigModel = Field(default_factory=MemoryL4ConfigModel)


class UserPreferencesModel(BaseModel):
    onboarding_completed: bool = Field(default=False)
    first_conversation_completed: bool = Field(
        default=False,
        description=(
            "Legacy onboarding state retained for existing saved preferences. "
            "The chat UI no longer uses it to show starter prompts."
        ),
    )
    product_tour_completed: bool = Field(
        default=False,
        description=(
            "True once the user has completed (or skipped) the one-time main-page "
            "product tour shown on first visit after onboarding."
        ),
    )
    suggestion_dismissals: dict[str, DismissalRecord] = Field(
        default_factory=dict,
        description=(
            "Map of dedupe_key → DismissalRecord. The signal matcher filters "
            "out any candidate whose dedupe_key appears here and whose TTL "
            "(based on kind) has not yet expired."
        ),
    )
    user_mode: Optional[str] = Field(default=None)
    scenario: Optional[str] = Field(default=None)
    language: str = Field(default="zh")
    close_to_tray_enabled: bool = Field(default=True)
    desktop_notifications_enabled: bool = Field(default=True)
    desktop_notification_previews_enabled: bool = Field(default=True)
    auto_start_enabled: bool = Field(default=False)
    start_minimized: bool = Field(default=False)
    skip_quit_confirmation: bool = Field(default=False)
    default_chat_workspace_path: Optional[str] = Field(default="~/.magi/chat-workspace")
    streaming_chat_enabled: bool = Field(default=False)
    conversation_rhythm_enabled: bool = Field(default=True)
    conversation_rhythm_mode: str = Field(default="natural")
    allow_media_grounding_for_conversation: bool = Field(default=True)
    allow_interjection: bool = Field(default=False)
    allow_ask_in_background: bool = Field(default=False)


class LanguagePreferenceUpdateRequest(BaseModel):
    language: Literal["zh", "en"] = Field(description="Preferred application language.")


class OnboardingConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Literal["zh", "en"] = Field(description="Onboarding interface language.")
    llm: LLMConfigModel = Field(description="LLM configuration selected during onboarding.")


class NetworkProxyConfigModel(BaseModel):
    enabled: bool = Field(default=False)
    proxy_type: str = Field(default="http")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7890, ge=1, le=65535)
    username: str = Field(default="")
    password: str = Field(default="")


class PersonalitySettingsModel(BaseModel):
    state_memory_enabled: bool = Field(default=True)
    state_transition_enabled: bool = Field(default=True)
    deep_persona_enabled: bool = Field(default=True)

    def normalized(self) -> "PersonalitySettingsModel":
        """Apply dependency rules so child features never outlive state memory."""
        if not self.state_memory_enabled:
            return PersonalitySettingsModel(
                state_memory_enabled=False,
                state_transition_enabled=False,
                deep_persona_enabled=False,
            )
        return self


class WeatherToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="openmeteo")
    apiKey: Optional[str] = Field(default=None)
    apiUrl: Optional[str] = Field(default=None)


class WebSearchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="duckduckgo")
    apiKey: Optional[str] = Field(default=None)
    apiUrl: Optional[str] = Field(default=None)


class WebFetchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    allowRfc2544BenchmarkRange: bool = Field(default=True)
    allowPrivateNetworkFetch: bool = Field(default=False)
    privateNetworkAllowlist: List[str] = Field(default_factory=list)


class BuiltInToolsConfigModel(BaseModel):
    weather: WeatherToolConfigModel = Field(default_factory=WeatherToolConfigModel)
    webSearch: WebSearchToolConfigModel = Field(default_factory=WebSearchToolConfigModel)
    webFetch: WebFetchToolConfigModel = Field(default_factory=WebFetchToolConfigModel)


class ToolsConfigModel(BaseModel):
    builtIn: BuiltInToolsConfigModel = Field(default_factory=BuiltInToolsConfigModel)
    skills: List[str] = Field(default_factory=list)


class TimelineSourceConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    sync_mode: str = Field(default="interval")
    sync_interval_minutes: int = Field(default=15, ge=1)
    default_retention_mode: str = Field(default="analyze_only")
    storage_mode: str = Field(default="managed")
    source_path: Optional[str] = Field(default=None)
    fetch_page_content: bool = Field(default=False)
    edge_whitelist: List[str] = Field(default_factory=list)


class TimelineSourcesConfigModel(BaseModel):
    photo_library: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            enabled=False,
            sync_mode="manual",
            sync_interval_minutes=60,
            default_retention_mode="analyze_only",
            storage_mode="external_reference",
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )
    calendar: Optional[TimelineSourceConfigModel] = Field(default=None)
    chrome_history: Optional[TimelineSourceConfigModel] = Field(default=None)
    git_activity: Optional[TimelineSourceConfigModel] = Field(default=None)
    screen_time: Optional[TimelineSourceConfigModel] = Field(default=None)
    terminal_history: Optional[TimelineSourceConfigModel] = Field(default=None)
    netease_music: Optional[TimelineSourceConfigModel] = Field(default=None)


class TimelineConfigModel(BaseModel):
    sources: TimelineSourcesConfigModel = Field(default_factory=TimelineSourcesConfigModel)


class SystemConfigModel(BaseModel):
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    preferences: UserPreferencesModel = Field(default_factory=UserPreferencesModel)
    network: NetworkProxyConfigModel = Field(default_factory=NetworkProxyConfigModel)
    personality: FullPersonalityConfigModel = Field(default_factory=FullPersonalityConfigModel)
    personalitySettings: PersonalitySettingsModel = Field(default_factory=PersonalitySettingsModel)
    tools: ToolsConfigModel = Field(default_factory=ToolsConfigModel)
    timeline: TimelineConfigModel = Field(default_factory=TimelineConfigModel)


class ConfigResponse(BaseModel):
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


class OnboardingTemplateDataModel(BaseModel):
    config: SystemConfigModel


class OnboardingTemplateResponse(BaseModel):
    success: bool
    message: str
    data: Optional[OnboardingTemplateDataModel] = None


class OnboardingStatusDataModel(BaseModel):
    completed: bool


class OnboardingStatusResponse(BaseModel):
    success: bool
    message: str
    data: OnboardingStatusDataModel


class TestTelegramConnectionRequest(BaseModel):
    bot_token: str
    proxy: str = ""


class TestTelegramConnectionResponse(BaseModel):
    success: bool
    message: str
    bot_username: str = ""
    bot_id: int = 0
