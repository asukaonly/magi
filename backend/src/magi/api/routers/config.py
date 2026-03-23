"""System configuration API router."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..llm_draft import build_adapter_from_provider
from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...config.models import LLMProviderSettings
from ...config.llm_registry import (
    LLMAudioGenerationModelMetaModel,
    LLMChatCapabilitiesModel,
    LLMCustomProviderMetaModel,
    LLMEmbeddingModelMetaModel,
    LLMImageGenerationModelMetaModel,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    find_provider_meta,
    load_llm_provider_registry,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from ...config.models import (
    LLMCapabilitiesSettings,
    LLMConcurrencyOverrideSettings,
    LLMLimitsSettings,
    LLMSelectionLimitsSettings,
)
from ...core.logger import get_logger
from ...llm import LLMProviderBridge, create_llm_adapter
from ...bootstrap import refresh_runtime_llm_config

logger = get_logger(__name__)
config_router = APIRouter()
QUICK_MODE_DEFAULT_PERSONALITY_PRESET_ID = "echo_ai_ssistant"


class AgentConfigModel(BaseModel):
    name: str = Field(default="magi-agent")
    description: Optional[str] = Field(default="Magi AI Agent Framework")


class LLMProviderConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider_type: str = Field(default="openai")
    display_name: str = Field(default="OpenAI")
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)


class LLMSelectionConfigModel(BaseModel):
    provider_id: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMSelectionLimitsSettings = Field(default_factory=LLMSelectionLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMConfigModel(BaseModel):
    providers: Dict[str, LLMProviderConfigModel] = Field(
        default_factory=lambda: {
            "openai": LLMProviderConfigModel()
        }
    )
    selections: Dict[str, LLMSelectionConfigModel] = Field(
        default_factory=lambda: {
            "context_decider": LLMSelectionConfigModel(),
            "core": LLMSelectionConfigModel(),
            "embedding": LLMSelectionConfigModel(
                capabilities=LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=False,
                    reasoning=False,
                    embedding=True,
                ),
            ),
        }
    )
    model_runtime_overrides: Dict[str, LLMConcurrencyOverrideSettings] = Field(default_factory=dict)


class LoopConfigModel(BaseModel):
    strategy: str = Field(default="continuous")
    interval: float = Field(default=1.0)


class MessageBusConfigModel(BaseModel):
    max_size: Optional[int] = Field(default=1000)


class MemoryEmbeddingConfigModel(BaseModel):
    backend: str = Field(default="sqlite_vec")


class MemoryL0ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    checkpoint_interval_seconds: int = Field(default=30, ge=1)
    runtime_replay_include_l0_only: bool = Field(default=False)


class MemoryL1ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    retention_days: int = Field(default=7, ge=1)
    t1_importance_enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)


class MemoryL2ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    batch_flush_interval_seconds: int = Field(default=60, ge=30)
    llm_extraction_enabled: bool = Field(default=True)
    auto_extract_relations: bool = Field(default=True)
    conflict_arbitration_enabled: bool = Field(default=True)
    conflict_arbitration_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class MemoryL3ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    llm_summary_enabled: bool = Field(default=True)
    temporal_llm_timeout_seconds: float = Field(default=3.0, ge=0.1)
    temporal_llm_min_event_count: int = Field(default=2, ge=1)
    summary_interval_minutes: int = Field(default=60, ge=1)


class MemoryL4ConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    vectors_enabled: bool = Field(default=True)
    skill_extraction_enabled: bool = Field(default=True)


class MemoryConfigModel(BaseModel):
    db_path: Optional[str] = Field(default="~/.magi/data/memories")
    async_embeddings: bool = Field(default=True)
    embedding: MemoryEmbeddingConfigModel = Field(default_factory=MemoryEmbeddingConfigModel)
    l0: MemoryL0ConfigModel = Field(default_factory=MemoryL0ConfigModel)
    l1: MemoryL1ConfigModel = Field(default_factory=MemoryL1ConfigModel)
    l2: MemoryL2ConfigModel = Field(default_factory=MemoryL2ConfigModel)
    l3: MemoryL3ConfigModel = Field(default_factory=MemoryL3ConfigModel)
    l4: MemoryL4ConfigModel = Field(default_factory=MemoryL4ConfigModel)


class WebSocketConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    port: Optional[int] = Field(default=8000)


class LogConfigModel(BaseModel):
    level: str = Field(default="INFO")
    path: Optional[str] = Field(default=None)


class UserPreferencesModel(BaseModel):
    onboarding_completed: bool = Field(default=False)
    user_mode: Optional[str] = Field(default=None)
    language: str = Field(default="zh")


# Import full PersonalityConfigModel from personality config module
from .personality_config import PersonalityConfigModel as FullPersonalityConfigModel


class WeatherToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="qweather")
    apiKey: Optional[str] = Field(default=None)
    apiUrl: Optional[str] = Field(default=None)


class WebSearchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    provider: str = Field(default="duckduckgo")
    apiKey: Optional[str] = Field(default=None)


class WebFetchToolConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    usePlaywright: bool = Field(default=False)


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
    chat: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="watch",
            sync_interval_minutes=1,
            default_retention_mode="analyze_only",
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH"],
        )
    )
    manual_journal: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="manual",
            sync_interval_minutes=1,
            default_retention_mode="retain_raw",
            edge_whitelist=["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO"],
        )
    )
    browser_history: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="interval",
            sync_interval_minutes=30,
            default_retention_mode="analyze_only",
            edge_whitelist=["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
        )
    )
    photo_library: TimelineSourceConfigModel = Field(
        default_factory=lambda: TimelineSourceConfigModel(
            sync_mode="interval",
            sync_interval_minutes=60,
            default_retention_mode="retain_raw",
            storage_mode="external_reference",
            edge_whitelist=["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
        )
    )


class TimelineConfigModel(BaseModel):
    enabled: bool = Field(default=True)
    expert_mode_edge_override: bool = Field(default=True)
    sources: TimelineSourcesConfigModel = Field(default_factory=TimelineSourcesConfigModel)


class SystemConfigModel(BaseModel):
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    loop: LoopConfigModel = Field(default_factory=LoopConfigModel)
    message_bus: MessageBusConfigModel = Field(default_factory=MessageBusConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    websocket: WebSocketConfigModel = Field(default_factory=WebSocketConfigModel)
    log: LogConfigModel = Field(default_factory=LogConfigModel)
    preferences: UserPreferencesModel = Field(default_factory=UserPreferencesModel)
    personality: FullPersonalityConfigModel = Field(default_factory=FullPersonalityConfigModel)
    tools: ToolsConfigModel = Field(default_factory=ToolsConfigModel)
    timeline: TimelineConfigModel = Field(default_factory=TimelineConfigModel)


class ConfigResponse(BaseModel):
    success: bool
    message: str
    data: Optional[SystemConfigModel] = None


class LLMProviderRegistryResponse(BaseModel):
    success: bool
    message: str
    data: Optional[LLMProviderRegistryModel] = None


class DiscoverLLMModelsRequestModel(BaseModel):
    provider_type: str = Field(default="custom")
    base_url: str
    api_key: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default="openai")


class DiscoverLLMModelsResponseModel(BaseModel):
    models: List[str] = Field(default_factory=list)
    default_model: Optional[str] = Field(default=None)


class DiscoverLLMModelsApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[DiscoverLLMModelsResponseModel] = None


class TestLLMProviderRequestModel(BaseModel):
    provider_id: str = Field(default="openai")
    provider: LLMProviderConfigModel
    model: str = Field(default="")


class TestLLMProviderResponseModel(BaseModel):
    model: str
    latency_ms: int
    preview: str = Field(default="")


class TestLLMProviderApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[TestLLMProviderResponseModel] = None


class OnboardingTemplateDataModel(BaseModel):
    config: SystemConfigModel
    llm_providers: LLMProviderRegistryModel


class OnboardingTemplateResponse(BaseModel):
    success: bool
    message: str
    data: Optional[OnboardingTemplateDataModel] = None


def _read_raw_yaml() -> Dict[str, Any]:
    config_path: Path = get_config_file_path()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        logger.exception("Failed to read raw config file")
        return {}


def _llm_provider_registry_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs" / "llm_providers.yaml"


def _default_llm_provider_registry() -> LLMProviderRegistryModel:
    try:
        with open(_llm_provider_registry_path(), "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return LLMProviderRegistryModel(**data)
    except Exception:
        return LLMProviderRegistryModel(
            providers=[
                LLMProviderMetaModel(
                    id="openai",
                    display_name="OpenAI",
                    description="General purpose, strongest ecosystem",
                    icon="openai",
                    default_model="gpt-5.2",
                    default_classify_model="gpt-5.2",
                    default_base_url="https://api.openai.com/v1",
                    chat_models=[
                        LLMModelMetaModel(
                            id="gpt-5.2",
                            label="GPT-5.2",
                            capabilities=LLMChatCapabilitiesModel(
                                vision=True,
                                image_output=False,
                                tool_calling=True,
                                reasoning=True,
                            ),
                            limits=LLMLimitsSettings(
                                context_window=400000,
                                max_output_tokens=128000,
                                max_concurrency=2,
                            ),
                        )
                    ],
                    embedding_models=[
                        LLMEmbeddingModelMetaModel(
                            id="text-embedding-3-small",
                            label="Text Embedding 3 Small",
                            dimensions=[1536, 512],
                            limits=LLMLimitsSettings(max_concurrency=6),
                        )
                    ],
                    image_generation_models=[LLMImageGenerationModelMetaModel(id="gpt-image-1", label="GPT Image 1")],
                    audio_generation_models=[LLMAudioGenerationModelMetaModel(id="gpt-4o-mini-tts", label="GPT-4o Mini TTS")],
                    fields={
                        "model": LLMProviderFieldModel(visible=True, required=True),
                        "api_key": LLMProviderFieldModel(visible=True, required=True),
                        "base_url": LLMProviderFieldModel(visible=True, required=False),
                    },
                )
            ],
            custom_provider=LLMCustomProviderMetaModel(
                enabled=True,
                display_name="Custom Provider",
                description="Connect OpenAI-compatible or Anthropic-compatible endpoints",
                icon="custom",
                capabilities=LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=True,
                    reasoning=True,
                    embedding=False,
                ),
                fields={
                    "custom_name": LLMProviderFieldModel(visible=True, required=True, placeholder="My Provider"),
                    "api_format": LLMProviderFieldModel(visible=True, required=True, options=["openai", "anthropic"]),
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
        )


def _load_llm_provider_registry() -> LLMProviderRegistryModel:
    return load_llm_provider_registry(
        _llm_provider_registry_path(),
        fallback=_default_llm_provider_registry(),
    )


def _selection_limits_from_registry_limits(limits: LLMLimitsSettings | None) -> LLMSelectionLimitsSettings:
    if limits is None:
        return LLMSelectionLimitsSettings()
    return LLMSelectionLimitsSettings(
        context_window=limits.context_window,
        max_output_tokens=limits.max_output_tokens,
    )


def _build_memory_config(raw: Dict[str, Any], runtime_config: Any) -> MemoryConfigModel:
    memory_cfg = runtime_config.agent.memory
    return MemoryConfigModel(
        db_path=memory_cfg.db_path,
        async_embeddings=memory_cfg.async_embeddings,
        embedding=MemoryEmbeddingConfigModel(
            backend=str(memory_cfg.embedding.backend),
        ),
        l0=MemoryL0ConfigModel(
            enabled=memory_cfg.l0.enabled,
            checkpoint_interval_seconds=memory_cfg.l0.checkpoint_interval_seconds,
            runtime_replay_include_l0_only=memory_cfg.l0.runtime_replay_include_l0_only,
        ),
        l1=MemoryL1ConfigModel(
            enabled=memory_cfg.l1.enabled,
            retention_days=memory_cfg.l1.retention_days,
            t1_importance_enabled=memory_cfg.l1.t1_importance_enabled,
            vectors_enabled=memory_cfg.l1.vectors_enabled,
        ),
        l2=MemoryL2ConfigModel(
            enabled=memory_cfg.l2.enabled,
            batch_flush_interval_seconds=memory_cfg.l2.batch_flush_interval_seconds,
            llm_extraction_enabled=memory_cfg.l2.llm_extraction_enabled,
            auto_extract_relations=memory_cfg.l2.auto_extract_relations,
            conflict_arbitration_enabled=memory_cfg.l2.conflict_arbitration_enabled,
            conflict_arbitration_min_confidence=memory_cfg.l2.conflict_arbitration_min_confidence,
        ),
        l3=MemoryL3ConfigModel(
            enabled=memory_cfg.l3.enabled,
            vectors_enabled=memory_cfg.l3.vectors_enabled,
            llm_summary_enabled=memory_cfg.l3.llm_summary_enabled,
            temporal_llm_timeout_seconds=memory_cfg.l3.temporal_llm_timeout_seconds,
            temporal_llm_min_event_count=memory_cfg.l3.temporal_llm_min_event_count,
            summary_interval_minutes=memory_cfg.l3.summary_interval_minutes,
        ),
        l4=MemoryL4ConfigModel(
            enabled=memory_cfg.l4.enabled,
            vectors_enabled=memory_cfg.l4.vectors_enabled,
            skill_extraction_enabled=memory_cfg.l4.skill_extraction_enabled,
        ),
    )


def _build_tools(raw: Dict[str, Any], runtime_config: Any) -> ToolsConfigModel:
    tools_raw = raw.get("tools", {}) if isinstance(raw.get("tools"), dict) else {}
    built_in = tools_raw.get("builtIn", {}) if isinstance(tools_raw.get("builtIn"), dict) else {}

    weather_runtime = runtime_config.tools.weather
    web_search_runtime = runtime_config.tools.web_search
    web_fetch_runtime = runtime_config.tools.web_fetch

    weather_provider = built_in.get("weather", {}).get("provider", weather_runtime.default_provider)
    weather_provider_cfg = weather_runtime.providers.get(weather_provider)

    web_search_provider = built_in.get("webSearch", {}).get("provider", web_search_runtime.default_provider)
    web_search_provider_cfg = web_search_runtime.providers.get(web_search_provider)

    use_playwright = built_in.get("webFetch", {}).get(
        "usePlaywright", web_fetch_runtime.default_provider == "browser"
    )

    return ToolsConfigModel(
        builtIn=BuiltInToolsConfigModel(
            weather=WeatherToolConfigModel(
                enabled=weather_runtime.enabled,
                provider=weather_provider,
                apiKey=(weather_provider_cfg.api_key if weather_provider_cfg else None),
                apiUrl=(weather_provider_cfg.base_url if weather_provider_cfg else None),
            ),
            webSearch=WebSearchToolConfigModel(
                enabled=web_search_runtime.enabled,
                provider=web_search_provider,
                apiKey=(web_search_provider_cfg.api_key if web_search_provider_cfg else None),
            ),
            webFetch=WebFetchToolConfigModel(
                enabled=web_fetch_runtime.enabled,
                usePlaywright=bool(use_playwright),
            ),
        ),
        skills=tools_raw.get("skills", []),
    )


def _load_full_personality() -> FullPersonalityConfigModel:
    """Load full personality config from personality file, not from agent.yaml."""
    from ...personality.loader import PersonalityLoader
    from ...utils.runtime import get_runtime_paths

    try:
        runtime_paths = get_runtime_paths()
        loader = PersonalityLoader(str(runtime_paths.personalities_dir))

        # Get current personality name from 'current' file or use default
        current_file = runtime_paths.personalities_dir / "current"
        if current_file.exists():
            personality_name = current_file.read_text().strip()
        else:
            personality_name = "default"

        # Load full personality from file
        personality_obj = loader.load(personality_name)
        return FullPersonalityConfigModel(**personality_obj.to_dict())
    except Exception as exc:
        logger.warning("Failed to load personality from file, using default: %s", exc)
        return FullPersonalityConfigModel()


def _build_llm_config_model(
    *,
    runtime_config: Any,
    raw_llm: Dict[str, Any],
    registry: LLMProviderRegistryModel,
    mask_api_key: bool,
) -> LLMConfigModel:
    providers: Dict[str, LLMProviderConfigModel] = {}
    for provider_id, provider in getattr(runtime_config.llm, "providers", {}).items():
        api_key = provider.api_key
        providers[provider_id] = LLMProviderConfigModel(
            enabled=provider.enabled,
            provider_type=str(getattr(provider.provider_type, "value", provider.provider_type)),
            display_name=provider.display_name,
            api_key=(_mask_api_key(api_key) if (mask_api_key and api_key) else api_key),
            base_url=provider.base_url,
            api_format=provider.api_format,
            custom_models=list(getattr(provider, "custom_models", []) or []),
            custom_default_model=getattr(provider, "custom_default_model", None),
        )

    selections: Dict[str, LLMSelectionConfigModel] = {}
    for selection_id, selection in getattr(runtime_config.llm, "selections", {}).items():
        if selection_id == "embedding":
            embedding_meta = find_embedding_model_meta(
                registry,
                selection.provider_id,
                selection.model,
            )
            resolved_dimension = resolve_embedding_dimension(
                embedding_meta,
                getattr(selection, "embedding_dimension", None),
            )
            if not bool(selection.capability_override_enabled):
                capabilities = LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=False,
                    reasoning=False,
                    embedding=True,
                )
                provider_options = (
                    dict(embedding_meta.provider_options_example)
                    if embedding_meta is not None
                    else dict(selection.provider_options or {})
                )
            else:
                capabilities = selection.capabilities
                provider_options = dict(selection.provider_options or {})

            selections[selection_id] = LLMSelectionConfigModel(
                provider_id=selection.provider_id,
                model=selection.model,
                embedding_dimension=resolved_dimension,
                capability_override_enabled=bool(selection.capability_override_enabled),
                capabilities=capabilities,
                limits=(
                    _selection_limits_from_registry_limits(embedding_meta.limits)
                    if embedding_meta is not None and not bool(selection.capability_override_enabled)
                    else selection.limits
                ),
                provider_options=provider_options,
            )
            continue

        resolved = resolve_llm_profile(selection, registry)
        selections[selection_id] = LLMSelectionConfigModel(
            provider_id=selection.provider_id,
            model=selection.model,
            embedding_dimension=getattr(selection, "embedding_dimension", None),
            capability_override_enabled=bool(selection.capability_override_enabled),
            capabilities=resolved.capabilities,
            limits=_selection_limits_from_registry_limits(resolved.limits),
            provider_options=resolved.provider_options,
        )

    return LLMConfigModel(
        providers=providers,
        selections=selections,
        model_runtime_overrides=dict(getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}),
    )


def _build_system_config(mask_api_key: bool = False) -> SystemConfigModel:
    runtime_config = get_config()
    raw = _read_raw_yaml()
    registry = _load_llm_provider_registry()

    preferences_data = raw.get("preferences", {})

    return SystemConfigModel(
        agent=AgentConfigModel(
            name=runtime_config.agent.name,
            description=raw.get("agent", {}).get("description", "Magi AI Agent Framework"),
        ),
        llm=_build_llm_config_model(
            runtime_config=runtime_config,
            raw_llm=raw.get("llm", {}) if isinstance(raw.get("llm"), dict) else {},
            registry=registry,
            mask_api_key=mask_api_key,
        ),
        loop=LoopConfigModel(
            strategy=raw.get("loop", {}).get("strategy", "continuous"),
            interval=float(raw.get("loop", {}).get("interval", runtime_config.agent.loop_interval)),
        ),
        message_bus=MessageBusConfigModel(
            max_size=runtime_config.agent.message_bus.max_queue_size,
        ),
        memory=_build_memory_config(raw, runtime_config),
        websocket=WebSocketConfigModel(
            enabled=runtime_config.features.enable_websocket,
            port=runtime_config.server.port,
        ),
        log=LogConfigModel(
            level=runtime_config.log_level,
            path=raw.get("log", {}).get("path"),
        ),
        preferences=UserPreferencesModel(**preferences_data),
        personality=_load_full_personality(),
        tools=_build_tools(raw, runtime_config),
        timeline=TimelineConfigModel(
            **(raw.get("timeline", {}) if isinstance(raw.get("timeline"), dict) else {})
        ),
    )


def _apply_llm_registry_defaults(config: SystemConfigModel, registry: LLMProviderRegistryModel) -> None:
    for provider_id, provider in config.llm.providers.items():
        provider_meta = find_provider_meta(registry, provider_id)
        if provider_meta is None:
            continue

        provider.provider_type = provider_id
        if not provider.display_name:
            provider.display_name = provider_meta.display_name or provider_id.upper()
        if not (provider.base_url or "").strip():
            provider.base_url = provider_meta.default_base_url

    for selection_id, selection in config.llm.selections.items():
        if not selection.provider_id:
            continue

        provider_meta = find_provider_meta(registry, selection.provider_id)
        if provider_meta is None:
            continue

        if selection_id == "embedding":
            embedding_model_meta = find_embedding_model_meta(
                registry,
                selection.provider_id,
                selection.model,
            )
            if embedding_model_meta is None and provider_meta.embedding_models:
                selection.model = provider_meta.embedding_models[0].id
                embedding_model_meta = provider_meta.embedding_models[0]

            selection.embedding_dimension = resolve_embedding_dimension(
                embedding_model_meta,
                selection.embedding_dimension,
            )

            if not selection.capability_override_enabled:
                config.llm.selections[selection_id] = LLMSelectionConfigModel(
                    provider_id=selection.provider_id,
                    model=selection.model,
                    embedding_dimension=selection.embedding_dimension,
                    capability_override_enabled=False,
                    capabilities=LLMCapabilitiesSettings(
                        vision=False,
                        image_output=False,
                        tool_calling=False,
                        reasoning=False,
                        embedding=True,
                    ),
                    limits=(
                        _selection_limits_from_registry_limits(embedding_model_meta.limits)
                        if embedding_model_meta is not None
                        else selection.limits
                    ),
                    provider_options=(
                        dict(embedding_model_meta.provider_options_example)
                        if embedding_model_meta is not None
                        else {}
                    ),
                )
            continue

        if not selection.model:
            if selection_id == "context_decider":
                selection.model = (
                    provider_meta.default_classify_model
                    or provider_meta.default_model
                    or (provider_meta.chat_models[0].id if provider_meta.chat_models else "")
                )
            else:
                selection.model = provider_meta.default_model or (
                    provider_meta.chat_models[0].id if provider_meta.chat_models else ""
                )

        if not selection.capability_override_enabled and selection.model:
            resolved = resolve_llm_profile(selection, registry)
            config.llm.selections[selection_id] = LLMSelectionConfigModel(
                provider_id=selection.provider_id,
                model=selection.model,
                embedding_dimension=selection.embedding_dimension,
                capability_override_enabled=False,
                capabilities=resolved.capabilities,
                limits=_selection_limits_from_registry_limits(resolved.limits),
                provider_options=resolved.provider_options,
            )


def _build_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    normalized = _normalize_masked_secrets(config)
    target_updates = _build_full_update_paths(normalized)
    current_updates = _build_full_update_paths(_build_system_config(mask_api_key=False))

    return {
        path: value
        for path, value in target_updates.items()
        if current_updates.get(path) != value
    }


def _normalize_masked_secrets(config: SystemConfigModel) -> SystemConfigModel:
    normalized = SystemConfigModel.model_validate(config.model_dump())
    runtime_config = get_config()

    for provider_id, provider in normalized.llm.providers.items():
        if not _is_masked_api_key(provider.api_key):
            continue
        runtime_provider = runtime_config.llm.providers.get(provider_id)
        provider.api_key = runtime_provider.api_key if runtime_provider is not None else None

    weather_api_key = normalized.tools.builtIn.weather.apiKey
    if _is_masked_api_key(weather_api_key):
        weather_provider = normalized.tools.builtIn.weather.provider
        runtime_weather = runtime_config.tools.weather.providers.get(weather_provider)
        normalized.tools.builtIn.weather.apiKey = runtime_weather.api_key if runtime_weather is not None else None

    web_search_api_key = normalized.tools.builtIn.webSearch.apiKey
    if _is_masked_api_key(web_search_api_key):
        web_search_provider = normalized.tools.builtIn.webSearch.provider
        runtime_web_search = runtime_config.tools.web_search.providers.get(web_search_provider)
        normalized.tools.builtIn.webSearch.apiKey = runtime_web_search.api_key if runtime_web_search is not None else None

    return normalized


def _build_full_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    _apply_llm_registry_defaults(config, _load_llm_provider_registry())

    for selection_id, selection in config.llm.selections.items():
        if not str(selection.provider_id or "").strip():
            continue
        provider = config.llm.providers.get(selection.provider_id)
        if provider is None:
            raise ValueError(
                f"LLM selection '{selection_id}' references unknown provider '{selection.provider_id}'"
            )
        if not provider.enabled:
            raise ValueError(
                f"LLM selection '{selection_id}' references disabled provider '{selection.provider_id}'"
            )

    llm_providers: Dict[str, Any] = {}
    for provider_id, provider in config.llm.providers.items():
        llm_providers[provider_id] = provider.model_dump()

    model_runtime_overrides = {
        runtime_key: limits.model_dump()
        for runtime_key, limits in config.llm.model_runtime_overrides.items()
    }

    updates: Dict[str, Any] = {
        "agent.name": config.agent.name,
        "agent.description": config.agent.description,
        "llm.providers": llm_providers,
        "llm.selections": {
            selection_id: selection.model_dump()
            for selection_id, selection in config.llm.selections.items()
        },
        "llm.model_runtime_overrides": model_runtime_overrides,
        "loop.strategy": config.loop.strategy,
        "loop.interval": config.loop.interval,
        "agent.loop_interval": config.loop.interval,
        "agent.message_bus.max_queue_size": config.message_bus.max_size,
        "agent.memory.db_path": config.memory.db_path,
        "agent.memory.async_embeddings": config.memory.async_embeddings,
        "agent.memory.embedding.backend": config.memory.embedding.backend,
        "agent.memory.l0.enabled": config.memory.l0.enabled,
        "agent.memory.l0.checkpoint_interval_seconds": config.memory.l0.checkpoint_interval_seconds,
        "agent.memory.l0.runtime_replay_include_l0_only": config.memory.l0.runtime_replay_include_l0_only,
        "agent.memory.l1.enabled": config.memory.l1.enabled,
        "agent.memory.l1.retention_days": config.memory.l1.retention_days,
        "agent.memory.l1.t1_importance_enabled": config.memory.l1.t1_importance_enabled,
        "agent.memory.l1.vectors_enabled": config.memory.l1.vectors_enabled,
        "agent.memory.l2.enabled": config.memory.l2.enabled,
        "agent.memory.l2.batch_flush_interval_seconds": config.memory.l2.batch_flush_interval_seconds,
        "agent.memory.l2.llm_extraction_enabled": config.memory.l2.llm_extraction_enabled,
        "agent.memory.l2.auto_extract_relations": config.memory.l2.auto_extract_relations,
        "agent.memory.l2.conflict_arbitration_enabled": config.memory.l2.conflict_arbitration_enabled,
        "agent.memory.l2.conflict_arbitration_min_confidence": config.memory.l2.conflict_arbitration_min_confidence,
        "agent.memory.l3.enabled": config.memory.l3.enabled,
        "agent.memory.l3.vectors_enabled": config.memory.l3.vectors_enabled,
        "agent.memory.l3.llm_summary_enabled": config.memory.l3.llm_summary_enabled,
        "agent.memory.l3.temporal_llm_timeout_seconds": config.memory.l3.temporal_llm_timeout_seconds,
        "agent.memory.l3.temporal_llm_min_event_count": config.memory.l3.temporal_llm_min_event_count,
        "agent.memory.l3.summary_interval_minutes": config.memory.l3.summary_interval_minutes,
        "agent.memory.l4.enabled": config.memory.l4.enabled,
        "agent.memory.l4.vectors_enabled": config.memory.l4.vectors_enabled,
        "agent.memory.l4.skill_extraction_enabled": config.memory.l4.skill_extraction_enabled,
        "features.enable_websocket": config.websocket.enabled,
        "server.port": config.websocket.port,
        "log_level": config.log.level,
        "log.path": config.log.path,
        "preferences": config.preferences.model_dump(),
        "agent.personality.name": config.personality.persona_entity.basic_profile.name if config.personality.persona_entity.basic_profile.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": True,
        "timeline": config.timeline.model_dump(),
        "tools.builtIn": config.tools.builtIn.model_dump(),
        "tools.skills": config.tools.skills,
        "tools.weather.enabled": config.tools.builtIn.weather.enabled,
        "tools.weather.default_provider": config.tools.builtIn.weather.provider,
        "tools.web_search.enabled": config.tools.builtIn.webSearch.enabled,
        "tools.web_search.default_provider": config.tools.builtIn.webSearch.provider,
        "tools.web_fetch.enabled": config.tools.builtIn.webFetch.enabled,
        "tools.web_fetch.default_provider": "browser" if config.tools.builtIn.webFetch.usePlaywright else "http",
    }
    if config.tools.builtIn.weather.apiKey is not None:
        updates[f"tools.weather.providers.{config.tools.builtIn.weather.provider}.api_key"] = config.tools.builtIn.weather.apiKey
    if config.tools.builtIn.weather.apiUrl is not None:
        updates[f"tools.weather.providers.{config.tools.builtIn.weather.provider}.base_url"] = config.tools.builtIn.weather.apiUrl
    if config.tools.builtIn.webSearch.apiKey is not None:
        updates[f"tools.web_search.providers.{config.tools.builtIn.webSearch.provider}.api_key"] = config.tools.builtIn.webSearch.apiKey
    return updates


def _mask_api_key(api_key: str) -> str:
    """Mask API key, showing only first few characters."""
    if not api_key:
        return ""
    # Show first 6 characters (e.g., "sk-abc") followed by "****"
    visible_chars = 6
    if len(api_key) <= visible_chars:
        return api_key[:3] + "***" if len(api_key) > 3 else "***"
    return api_key[:visible_chars] + "****"


def _is_masked_api_key(api_key: Optional[str]) -> bool:
    """Check if API key is a masked/placeholder value."""
    if not api_key:
        return True
    # Check for common masked patterns
    masked_patterns = ["***", "****", "*****"]
    if api_key in masked_patterns:
        return True
    # Check for partial mask pattern like "sk-abc****"
    if api_key.endswith("****") or api_key.endswith("***"):
        return True
    return False


def _build_onboarding_template() -> SystemConfigModel:
    template = SystemConfigModel()
    registry = _load_llm_provider_registry()

    if registry.providers:
        template.llm.providers = {
            provider.id: LLMProviderConfigModel(
                enabled=False,
                provider_type=provider.id,
                display_name=provider.display_name or provider.id.title(),
                base_url="",
                custom_models=[],
                custom_default_model=None,
            )
            for provider in registry.providers
        }
        for selection_id in ("context_decider", "core", "embedding"):
            selection = template.llm.selections[selection_id]
            selection.provider_id = ""
            selection.model = ""
            selection.embedding_dimension = None
            selection.provider_options = {}

    template.preferences.onboarding_completed = False
    template.preferences.user_mode = None
    return template


def _resolve_personality_language_code(language: str) -> str:
    normalized = (language or "zh").lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return normalized


def _load_quick_mode_default_personality(language: str) -> Optional[FullPersonalityConfigModel]:
    """Load quick-mode default personality preset with language fallback."""
    root = Path(__file__).resolve().parents[4] / "personalities"
    language_candidates = [_resolve_personality_language_code(language)]
    if "zh" not in language_candidates:
        language_candidates.append("zh")

    for lang in language_candidates:
        preset_file = root / lang / f"{QUICK_MODE_DEFAULT_PERSONALITY_PRESET_ID}.json"
        if not preset_file.exists():
            continue
        try:
            payload = json.loads(preset_file.read_text(encoding="utf-8"))
            return FullPersonalityConfigModel.model_validate(payload)
        except Exception as exc:
            logger.warning("Failed to load quick-mode default personality preset from %s: %s", preset_file, exc)
    return None


async def _discover_openai_compatible_models(
    base_url: str,
    api_key: Optional[str],
    api_format: Optional[str],
) -> List[str]:
    if api_format not in (None, "", "openai"):
        raise HTTPException(status_code=400, detail="Unsupported model discovery format")

    endpoint = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint, headers=headers) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Model discovery request failed with status {response.status}")
                payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to discover models: {exc}") from exc

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Model discovery response payload is invalid")

    models: List[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                models.append(model_id)
    return models


@config_router.get("/", response_model=ConfigResponse)
async def get_config_endpoint():
    return ConfigResponse(success=True, message="Configuration loaded", data=_build_system_config())


@config_router.put("/", response_model=ConfigResponse)
async def update_config(config: SystemConfigModel):
    try:
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save config")
        refreshed_config = reload_config()
        refresh_runtime_llm_config(refreshed_config)
        return ConfigResponse(success=True, message="Configuration updated", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update config")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.post("/reset", response_model=ConfigResponse)
async def reset_config():
    try:
        config_path = get_config_file_path()
        if config_path.exists():
            config_path.unlink()
        # Trigger default config regeneration.
        _ = get_config()
        return ConfigResponse(success=True, message="Configuration reset", data=_build_system_config())
    except Exception as exc:
        logger.exception("Failed to reset config")
        raise HTTPException(status_code=500, detail=str(exc))


@config_router.get("/template", response_model=ConfigResponse)
async def get_config_template():
    return ConfigResponse(success=True, message="Configuration template", data=SystemConfigModel())


@config_router.post("/test", response_model=ConfigResponse)
async def test_config(config: SystemConfigModel):
    core_selection = config.llm.selections.get("core")
    context_selection = config.llm.selections.get("context_decider")
    if not core_selection or not context_selection:
        return ConfigResponse(success=False, message="LLM selections are required", data=None)
    if not core_selection.provider_id or not core_selection.model:
        return ConfigResponse(success=False, message="LLM provider is required", data=None)
    return ConfigResponse(success=True, message="Configuration valid", data=config)


@config_router.get("/llm-providers", response_model=LLMProviderRegistryResponse)
async def get_llm_provider_registry():
    return LLMProviderRegistryResponse(
        success=True,
        message="LLM provider registry loaded",
        data=_load_llm_provider_registry(),
    )


@config_router.post("/llm/providers/discover-models", response_model=DiscoverLLMModelsApiResponseModel)
async def discover_llm_provider_models(payload: DiscoverLLMModelsRequestModel):
    models = await _discover_openai_compatible_models(
        payload.base_url,
        payload.api_key,
        payload.api_format,
    )
    return DiscoverLLMModelsApiResponseModel(
        success=True,
        message="LLM provider models discovered",
        data=DiscoverLLMModelsResponseModel(
            models=models,
            default_model=models[0] if models else None,
        ),
    )


async def _test_llm_provider_connection(
    provider_id: str,
    provider: LLMProviderConfigModel,
    model: str,
) -> Dict[str, Any]:
    runtime_provider = LLMProviderSettings.model_validate(provider.model_dump())
    registry_meta = find_provider_meta(_load_llm_provider_registry(), provider_id)
    adapter = build_adapter_from_provider(
        runtime_provider,
        model=model,
        default_base_url=registry_meta.default_base_url if registry_meta else None,
        adapter_factory=create_llm_adapter,
    )
    bridge = LLMProviderBridge(adapter)
    started_at = time.perf_counter()
    preview = await bridge.chat(
        system_prompt="You are a connection test assistant. Reply briefly.",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32,
        temperature=0.1,
        disable_thinking=True,
        event_context={
            "surface": "config_provider_test",
            "provider_id": provider_id,
        },
    )
    return {
        "model": model,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "preview": preview[:120].strip(),
    }


@config_router.post("/llm/providers/test", response_model=TestLLMProviderApiResponseModel)
async def test_llm_provider_connection(payload: TestLLMProviderRequestModel):
    registry_meta = find_provider_meta(_load_llm_provider_registry(), payload.provider_id)
    provider_payload = payload.provider.model_copy(deep=True)
    if not (provider_payload.base_url or "").strip() and registry_meta and registry_meta.default_base_url:
        provider_payload.base_url = registry_meta.default_base_url
    try:
        result = await _test_llm_provider_connection(
            payload.provider_id,
            provider_payload,
            payload.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to test LLM provider connection")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return TestLLMProviderApiResponseModel(
        success=True,
        message="LLM provider connection succeeded",
        data=TestLLMProviderResponseModel(**result),
    )


@config_router.get("/onboarding-template", response_model=OnboardingTemplateResponse)
async def get_onboarding_template():
    return OnboardingTemplateResponse(
        success=True,
        message="Onboarding template loaded",
        data=OnboardingTemplateDataModel(
            config=_build_onboarding_template(),
            llm_providers=_load_llm_provider_registry(),
        ),
    )


def _copy_personality_preset_to_user(preset_id: str, lang: str = "zh") -> bool:
    """Copy a personality preset to user storage and set as current."""
    import json
    from ...utils.runtime import get_runtime_paths

    try:
        # Load preset from built-in directory
        builtin_dir = Path(__file__).resolve().parents[3] / "personalities" / lang
        preset_file = builtin_dir / f"{preset_id}.json"

        if not preset_file.exists():
            # Try fallback to zh if lang is not found
            if lang != "zh":
                builtin_dir = Path(__file__).resolve().parents[3] / "personalities" / "zh"
                preset_file = builtin_dir / f"{preset_id}.json"

            if not preset_file.exists():
                logger.warning("Personality preset not found: %s", preset_id)
                return False

        # Read preset config
        content = preset_file.read_text(encoding="utf-8")
        preset_config = json.loads(content)

        # Save to user storage
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)
        user_file = runtime_paths.personality_file(preset_id)
        user_file.write_text(json.dumps(preset_config, ensure_ascii=False, indent=2), encoding="utf-8")

        # Set as current personality
        current_file = runtime_paths.personalities_dir / "current"
        current_file.write_text(preset_id)

        logger.info("Copied personality preset '%s' to user storage and set as current", preset_id)
        return True
    except Exception as exc:
        logger.error("Failed to copy personality preset: %s", exc)
        return False


def _save_personality_to_user(personality: FullPersonalityConfigModel) -> bool:
    """Save personality config to user storage and set as current."""
    import json
    from ...utils.runtime import get_runtime_paths

    try:
        # Get personality name from basic_profile
        name = personality.persona_entity.basic_profile.name
        if not name:
            name = "user_personality"

        # Sanitize name for filename
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
        safe_name = (safe_name[:50] or "user_personality").strip("_") or "user_personality"

        # Save to user storage
        runtime_paths = get_runtime_paths()
        runtime_paths.personalities_dir.mkdir(parents=True, exist_ok=True)
        user_file = runtime_paths.personality_file(safe_name)
        user_file.write_text(
            json.dumps(personality.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Set as current personality
        current_file = runtime_paths.personalities_dir / "current"
        current_file.write_text(safe_name)

        logger.info("Saved personality '%s' to user storage and set as current", safe_name)
        return True
    except Exception as exc:
        logger.error("Failed to save personality to user: %s", exc)
        return False


@config_router.post("/onboarding-complete", response_model=ConfigResponse)
async def complete_onboarding(config: SystemConfigModel):
    try:
        if config.preferences.user_mode == "quick":
            quick_mode_personality = _load_quick_mode_default_personality(config.preferences.language)
            if quick_mode_personality is not None:
                config.personality = quick_mode_personality
            else:
                logger.warning(
                    "Quick mode default personality preset '%s' was not found; using submitted personality payload",
                    QUICK_MODE_DEFAULT_PERSONALITY_PRESET_ID,
                )

        config.preferences.onboarding_completed = True
        updates = _build_update_paths(config)
        if not save_config(updates):
            raise HTTPException(status_code=500, detail="Failed to save onboarding configuration")
        refreshed_config = reload_config()

        # Try to initialize agent runtime if not already initialized
        from ...bootstrap import initialize_agent_runtime
        from ...core.runtime_bindings import require_agent_runtime
        try:
            require_agent_runtime()
            # Already initialized, just refresh LLM config
            refresh_runtime_llm_config(refreshed_config)
        except RuntimeError:
            # Not initialized, try to initialize now
            logger.info("Attempting to initialize agent runtime after onboarding")
            await initialize_agent_runtime()

        # Save the full personality config to user storage and set as current
        if config.personality:
            _save_personality_to_user(config.personality)

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
