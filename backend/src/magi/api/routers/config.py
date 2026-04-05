"""System configuration API router."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...config.models import LLMProviderSettings
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    find_provider_meta,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from ...config.models import (
    LLMCapabilitiesSettings,
    LLMModelMetadataOverrideSettings,
    LLMConcurrencyOverrideSettings,
    LLMLimitsSettings,
    LLMSelectionLimitsSettings,
)
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshLLMConfigCommand
from ...core.logger import get_logger
from ...bootstrap import refresh_runtime_llm_config
from ..services.llm_testing_service import get_llm_provider_registry as _load_llm_provider_registry

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
    model_metadata_overrides: Dict[str, LLMModelMetadataOverrideSettings] = Field(default_factory=dict)


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


class MemoryRerankerLocalConfigModel(BaseModel):
    model_source: str = Field(default="managed")
    managed_model_id: Optional[str] = Field(default=None)
    model_file_path: Optional[str] = Field(default=None)
    max_context_tokens: int = Field(default=2048, ge=1)


class MemoryRerankerRemoteConfigModel(BaseModel):
    provider_id: str = Field(default="")
    model: str = Field(default="")


class MemoryRerankerConfigModel(BaseModel):
    enabled: bool = Field(default=False)
    backend: str = Field(default="heuristic")
    mode: str = Field(default="local")
    layers: List[str] = Field(default_factory=lambda: ["L1", "L3"])
    top_k: int = Field(default=8, ge=1)
    timeout_seconds: float = Field(default=0.8, ge=0.1)
    candidate_max_chars: int = Field(default=500, ge=50)
    local: MemoryRerankerLocalConfigModel = Field(default_factory=MemoryRerankerLocalConfigModel)
    remote: MemoryRerankerRemoteConfigModel = Field(default_factory=MemoryRerankerRemoteConfigModel)


class EmbeddingLocalConfigModel(BaseModel):
    model_source: str = Field(default="managed")
    managed_model_id: Optional[str] = Field(default=None)
    model_dir_path: Optional[str] = Field(default=None)
    idle_timeout_seconds: int = Field(default=1800, ge=60)


class EmbeddingConfigModel(BaseModel):
    mode: str = Field(default="remote")
    local: EmbeddingLocalConfigModel = Field(default_factory=EmbeddingLocalConfigModel)


class MemoryConfigModel(BaseModel):
    db_path: Optional[str] = Field(default="~/.magi/data/memory")
    embedding: EmbeddingConfigModel = Field(default_factory=EmbeddingConfigModel)
    reranker: MemoryRerankerConfigModel = Field(default_factory=MemoryRerankerConfigModel)
    l0: MemoryL0ConfigModel = Field(default_factory=MemoryL0ConfigModel)
    l1: MemoryL1ConfigModel = Field(default_factory=MemoryL1ConfigModel)
    l2: MemoryL2ConfigModel = Field(default_factory=MemoryL2ConfigModel)
    l3: MemoryL3ConfigModel = Field(default_factory=MemoryL3ConfigModel)
    l4: MemoryL4ConfigModel = Field(default_factory=MemoryL4ConfigModel)


class UserPreferencesModel(BaseModel):
    onboarding_completed: bool = Field(default=False)
    user_mode: Optional[str] = Field(default=None)
    language: str = Field(default="zh")
    close_to_tray_enabled: bool = Field(default=True)
    default_chat_workspace_path: Optional[str] = Field(default="~/.magi/chat-workspace")


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
    sources: TimelineSourcesConfigModel = Field(default_factory=TimelineSourcesConfigModel)


class SystemConfigModel(BaseModel):
    agent: AgentConfigModel = Field(default_factory=AgentConfigModel)
    llm: LLMConfigModel = Field(default_factory=LLMConfigModel)
    memory: MemoryConfigModel = Field(default_factory=MemoryConfigModel)
    preferences: UserPreferencesModel = Field(default_factory=UserPreferencesModel)
    personality: FullPersonalityConfigModel = Field(default_factory=FullPersonalityConfigModel)
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
        embedding=EmbeddingConfigModel(
            mode=getattr(memory_cfg.embedding.mode, "value", str(memory_cfg.embedding.mode)),
            local=EmbeddingLocalConfigModel(
                model_source=getattr(memory_cfg.embedding.local.model_source, "value", str(memory_cfg.embedding.local.model_source)),
                managed_model_id=memory_cfg.embedding.local.managed_model_id,
                model_dir_path=memory_cfg.embedding.local.model_dir_path,
                idle_timeout_seconds=memory_cfg.embedding.local.idle_timeout_seconds,
            ),
        ),
        reranker=MemoryRerankerConfigModel(
            enabled=memory_cfg.reranker.enabled,
            backend=memory_cfg.reranker.backend,
            mode=memory_cfg.reranker.mode,
            layers=[layer.value if hasattr(layer, "value") else str(layer) for layer in memory_cfg.reranker.layers],
            top_k=memory_cfg.reranker.top_k,
            timeout_seconds=memory_cfg.reranker.timeout_seconds,
            candidate_max_chars=memory_cfg.reranker.candidate_max_chars,
            local=MemoryRerankerLocalConfigModel(
                model_source=memory_cfg.reranker.local.model_source,
                managed_model_id=memory_cfg.reranker.local.managed_model_id,
                model_file_path=memory_cfg.reranker.local.model_file_path,
                max_context_tokens=memory_cfg.reranker.local.max_context_tokens,
            ),
            remote=MemoryRerankerRemoteConfigModel(
                provider_id=memory_cfg.reranker.remote.provider_id,
                model=memory_cfg.reranker.remote.model,
            ),
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
            model_metadata_overrides=dict(getattr(provider, "model_metadata_overrides", {}) or {}),
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

        resolved = resolve_llm_profile(
            selection,
            registry,
            provider_settings=runtime_config.llm.providers.get(selection.provider_id),
        )
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
        memory=_build_memory_config(raw, runtime_config),
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
            resolved = resolve_llm_profile(
                selection,
                registry,
                provider_settings=config.llm.providers.get(selection.provider_id),
            )
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


def _prune_sparse_value(value: Any) -> Any:
    """Remove None leaves and empty dict nodes from persisted config payloads."""
    if isinstance(value, dict):
        pruned: Dict[str, Any] = {}
        for key, item in value.items():
            next_value = _prune_sparse_value(item)
            if next_value is None:
                continue
            if isinstance(next_value, dict) and not next_value:
                continue
            pruned[key] = next_value
        return pruned
    if isinstance(value, list):
        return [_prune_sparse_value(item) for item in value]
    return value


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
        llm_providers[provider_id] = _prune_sparse_value(provider.model_dump(exclude_none=True))

    model_runtime_overrides = {
        runtime_key: _prune_sparse_value(limits.model_dump(exclude_none=True))
        for runtime_key, limits in config.llm.model_runtime_overrides.items()
    }

    updates: Dict[str, Any] = {
        "agent.name": config.agent.name,
        "agent.description": config.agent.description,
        "llm.providers": llm_providers,
        "llm.selections": {
            selection_id: _prune_sparse_value(selection.model_dump(exclude_none=True))
            for selection_id, selection in config.llm.selections.items()
        },
        "llm.model_runtime_overrides": model_runtime_overrides,
        "agent.memory.db_path": config.memory.db_path,
        "agent.memory.embedding.mode": config.memory.embedding.mode,
        "agent.memory.embedding.local.model_source": config.memory.embedding.local.model_source,
        "agent.memory.embedding.local.managed_model_id": config.memory.embedding.local.managed_model_id,
        "agent.memory.embedding.local.model_dir_path": config.memory.embedding.local.model_dir_path,
        "agent.memory.embedding.local.idle_timeout_seconds": config.memory.embedding.local.idle_timeout_seconds,
        "agent.memory.reranker.enabled": config.memory.reranker.enabled,
        "agent.memory.reranker.backend": config.memory.reranker.backend,
        "agent.memory.reranker.mode": config.memory.reranker.mode,
        "agent.memory.reranker.layers": config.memory.reranker.layers,
        "agent.memory.reranker.top_k": config.memory.reranker.top_k,
        "agent.memory.reranker.timeout_seconds": config.memory.reranker.timeout_seconds,
        "agent.memory.reranker.candidate_max_chars": config.memory.reranker.candidate_max_chars,
        "agent.memory.reranker.local.model_source": config.memory.reranker.local.model_source,
        "agent.memory.reranker.local.managed_model_id": config.memory.reranker.local.managed_model_id,
        "agent.memory.reranker.local.model_file_path": config.memory.reranker.local.model_file_path,
        "agent.memory.reranker.local.max_context_tokens": config.memory.reranker.local.max_context_tokens,
        "agent.memory.reranker.remote.provider_id": config.memory.reranker.remote.provider_id,
        "agent.memory.reranker.remote.model": config.memory.reranker.remote.model,
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
        "preferences": _prune_sparse_value(config.preferences.model_dump(exclude_none=True)),
        "agent.personality.name": config.personality.persona_entity.basic_profile.name if config.personality.persona_entity.basic_profile.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": True,
        "timeline": _prune_sparse_value(config.timeline.model_dump(exclude_none=True)),
        "tools.builtIn": _prune_sparse_value(config.tools.builtIn.model_dump(exclude_none=True)),
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


async def _enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to reload and refresh its LLM config."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info("Runtime command queue unavailable during LLM refresh notification", reason=reason)
        return

    await queue.enqueue_refresh_llm_config(
        RefreshLLMConfigCommand(
            source="config_api",
            reason=reason,
        )
    )


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
                model_metadata_overrides={},
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
        await _enqueue_runtime_llm_refresh_command(reason="config_updated")
        return ConfigResponse(success=True, message="Configuration updated", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update config")
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


@config_router.get("/onboarding-template", response_model=OnboardingTemplateResponse)
async def get_onboarding_template():
    return OnboardingTemplateResponse(
        success=True,
        message="Onboarding template loaded",
        data=OnboardingTemplateDataModel(
            config=_build_onboarding_template(),
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
        await _enqueue_runtime_llm_refresh_command(reason="onboarding_completed")

        # Save the full personality config to user storage and set as current
        if config.personality:
            _save_personality_to_user(config.personality)

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
