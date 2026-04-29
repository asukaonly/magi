"""System configuration API router."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, HTTPException

from ...config.loader import get_config, get_config_file_path, reload_config, save_config
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    find_provider_meta,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from ...config.models import (
    LLMCapabilitiesSettings,
    LLMLimitsSettings,
    LLMSelectionLimitsSettings,
)
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshLLMConfigCommand
from ...core.logger import get_logger
from ...bootstrap import refresh_runtime_llm_config
from ...utils.packaged_paths import get_backend_root
from ..services.llm_testing_service import get_llm_provider_registry as _load_llm_provider_registry
from .config_schemas import (
    AgentConfigModel,
    BuiltInToolsConfigModel,
    ConfigResponse,
    CrossEncoderConfigModel,
    EmbeddingConfigModel,
    EmbeddingLocalConfigModel,
    EntitySemanticEdgeConfigModel,
    FullPersonalityConfigModel,
    GraphSpreadingConfigModel,
    LLMConfigModel,
    LLMProviderConfigModel,
    LLMSelectionConfigModel,
    MemoryConfigModel,
    MemoryL0ConfigModel,
    MemoryL1ConfigModel,
    MemoryL2ConfigModel,
    MemoryL3ConfigModel,
    MemoryL4ConfigModel,
    MemoryRerankerConfigModel,
    NetworkProxyConfigModel,
    OnboardingTemplateDataModel,
    OnboardingTemplateResponse,
    PersonalitySettingsModel,
    QueryExpansionConfigModel,
    SystemConfigModel,
    TestTelegramConnectionRequest,
    TestTelegramConnectionResponse,
    TimelineConfigModel,
    ToolsConfigModel,
    UserPreferencesModel,
    WeatherToolConfigModel,
    WebFetchToolConfigModel,
    WebSearchToolConfigModel,
)

logger = get_logger(__name__)
config_router = APIRouter()


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
        retention_days=memory_cfg.retention_days,
        history_behavior=getattr(memory_cfg.history_behavior, "value", str(memory_cfg.history_behavior)),
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
            top_k=memory_cfg.reranker.top_k,
            cross_encoder=CrossEncoderConfigModel(
                enabled=memory_cfg.reranker.cross_encoder.enabled,
                managed_model_id=memory_cfg.reranker.cross_encoder.managed_model_id,
            ),
        ),
        query_expansion=QueryExpansionConfigModel(
            enabled=memory_cfg.query_expansion.enabled,
        ),
        graph_spreading=GraphSpreadingConfigModel(
            enabled=memory_cfg.graph_spreading.enabled,
        ),
        entity_semantic_edges=EntitySemanticEdgeConfigModel(
            enabled=memory_cfg.entity_semantic_edges.enabled,
        ),
        l0=MemoryL0ConfigModel(
            enabled=memory_cfg.l0.enabled,
            checkpoint_interval_seconds=memory_cfg.l0.checkpoint_interval_seconds,
        ),
        l1=MemoryL1ConfigModel(
            enabled=memory_cfg.l1.enabled,
            vectors_enabled=memory_cfg.l1.vectors_enabled,
        ),
        l2=MemoryL2ConfigModel(
            enabled=memory_cfg.l2.enabled,
            batch_flush_interval_seconds=memory_cfg.l2.batch_flush_interval_seconds,
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
    """Load full personality config from the in-memory cache."""
    from ...personality.active_persona import get_current_personality_config

    try:
        cached = get_current_personality_config()
        if cached is not None:
            return FullPersonalityConfigModel(**cached.to_dict())

        logger.warning("No personality config in cache, using default")
        return FullPersonalityConfigModel()
    except Exception as exc:
        logger.warning("Failed to load personality config, using default: %s", exc)
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
    network_data = raw.get("network", {})

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
        network=NetworkProxyConfigModel(**network_data),
        personality=_load_full_personality(),
        personalitySettings=PersonalitySettingsModel(
            state_memory_enabled=bool(getattr(runtime_config.agent.personality, "enable_state_memory", True)),
            state_transition_enabled=bool(getattr(runtime_config.agent.personality, "enable_state_transition", True)),
            deep_persona_enabled=bool(getattr(runtime_config.agent.personality, "enable_deep_persona", True)),
        ).normalized(),
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
    personality_settings = config.personalitySettings.normalized()

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
            if str(selection.provider_id or "").strip() and str(selection.model or "").strip()
        },
        "llm.model_runtime_overrides": model_runtime_overrides,
        "agent.memory.db_path": config.memory.db_path,
        "agent.memory.embedding.mode": config.memory.embedding.mode,
        "agent.memory.embedding.local.model_source": config.memory.embedding.local.model_source,
        "agent.memory.embedding.local.managed_model_id": config.memory.embedding.local.managed_model_id,
        "agent.memory.embedding.local.model_dir_path": config.memory.embedding.local.model_dir_path,
        "agent.memory.embedding.local.idle_timeout_seconds": config.memory.embedding.local.idle_timeout_seconds,
        "agent.memory.retention_days": config.memory.retention_days,
        "agent.memory.history_behavior": config.memory.history_behavior,
        "agent.memory.reranker.top_k": config.memory.reranker.top_k,
        "agent.memory.reranker.cross_encoder.enabled": config.memory.reranker.cross_encoder.enabled,
        "agent.memory.reranker.cross_encoder.managed_model_id": config.memory.reranker.cross_encoder.managed_model_id,
        "agent.memory.query_expansion.enabled": config.memory.query_expansion.enabled,
        "agent.memory.graph_spreading.enabled": config.memory.graph_spreading.enabled,
        "agent.memory.entity_semantic_edges.enabled": config.memory.entity_semantic_edges.enabled,
        "agent.memory.l0.enabled": config.memory.l0.enabled,
        "agent.memory.l0.checkpoint_interval_seconds": config.memory.l0.checkpoint_interval_seconds,
        "agent.memory.l1.enabled": config.memory.l1.enabled,
        "agent.memory.l1.vectors_enabled": config.memory.l1.vectors_enabled,
        "agent.memory.l2.enabled": config.memory.l2.enabled,
        "agent.memory.l2.batch_flush_interval_seconds": config.memory.l2.batch_flush_interval_seconds,
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
        "preferences": _prune_sparse_value(config.preferences.model_dump(exclude_none=True)),
        "network": config.network.model_dump(),
        "agent.personality.name": config.personality.persona_entity.basic_profile.name if config.personality.persona_entity.basic_profile.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": personality_settings.state_memory_enabled,
        "agent.personality.enable_state_memory": personality_settings.state_memory_enabled,
        "agent.personality.enable_state_transition": personality_settings.state_transition_enabled,
        "agent.personality.enable_deep_persona": personality_settings.deep_persona_enabled,
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


async def _enqueue_runtime_channels_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to restart channel adapters."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info("Runtime command queue unavailable during channels refresh notification", reason=reason)
        return

    from ...events.contracts import RefreshChannelsCommand

    await queue.enqueue_refresh_channels(
        RefreshChannelsCommand(
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


def _quick_mode_personality_locale_candidates(language: str) -> List[str]:
    preferred = _resolve_personality_language_code(language)
    candidates = [preferred]
    for fallback in ("en", "zh"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _quick_mode_personality_sort_key(preset_file: Path, payload: Dict[str, Any]) -> tuple[int, int, str, str]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    profile = payload.get("persona_entity", {}).get("basic_profile", {})
    is_default = bool(
        meta.get("default")
        or meta.get("recommended")
        or meta.get("is_default")
        or meta.get("is_recommended")
    )
    try:
        order = int(meta.get("order", 0))
    except (TypeError, ValueError):
        order = 0
    name = str(profile.get("name") or preset_file.stem)
    return (0 if is_default else 1, order, name, preset_file.stem)


def _load_quick_mode_default_personality(language: str) -> Optional[FullPersonalityConfigModel]:
    """Load the locale-appropriate quick-mode personality seed."""
    root = get_backend_root() / "personalities"
    for lang in _quick_mode_personality_locale_candidates(language):
        seed_dir = root / lang
        if not seed_dir.is_dir():
            continue

        candidates: list[tuple[tuple[int, int, str, str], Path, Dict[str, Any]]] = []
        for preset_file in sorted(seed_dir.glob("*.json")):
            try:
                payload = json.loads(preset_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to read quick-mode personality preset from %s: %s", preset_file, exc)
                continue
            candidates.append((_quick_mode_personality_sort_key(preset_file, payload), preset_file, payload))

        for _, preset_file, payload in sorted(candidates, key=lambda item: item[0]):
            try:
                logger.info("Using quick-mode personality preset %s for language %s", preset_file.stem, lang)
                return FullPersonalityConfigModel.model_validate(payload)
            except Exception as exc:
                logger.warning("Failed to load quick-mode personality preset from %s: %s", preset_file, exc)

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
        await _enqueue_runtime_channels_refresh_command(reason="config_updated")
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


async def _save_personality_to_user(personality: FullPersonalityConfigModel) -> bool:
    """Save personality config to the persona registry and set as current."""
    import json
    from ...personality.active_persona import set_current_personality
    from ...personality.loader import PersonalityConfig
    from ...personality.persona_repository import PersonaRepository
    from ...utils.runtime import get_runtime_paths

    try:
        # Get personality name from basic_profile
        name = personality.persona_entity.basic_profile.name
        if not name:
            name = "user_personality"

        # Sanitize name for slug
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name).replace(" ", "_")
        safe_name = (safe_name[:50] or "user_personality").strip("_") or "user_personality"

        # Save to persona registry
        config_json = json.dumps(personality.model_dump(), ensure_ascii=False)
        repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
        await repo.init()
        try:
            record = await repo.get_by_slug(safe_name)
            await repo.update(record.persona_id, config_json=config_json)
            await repo.set_active(record.persona_id)
        except (KeyError, Exception):
            persona_id = await repo.create(config_json=config_json, slug=safe_name)
            await repo.set_active(persona_id)

        # Set in-memory cache
        config = PersonalityConfig.from_dict(personality.model_dump())
        set_current_personality(safe_name, config=config)

        logger.info("Saved personality '%s' to registry and set as current", safe_name)
        return True
    except Exception as exc:
        logger.error("Failed to save personality to registry: %s", exc)
        return False


@config_router.post("/channels/telegram/test", response_model=TestTelegramConnectionResponse)
async def test_telegram_connection(payload: TestTelegramConnectionRequest):
    """Test Telegram bot token + proxy by calling getMe."""
    if not payload.bot_token or payload.bot_token.endswith("****"):
        raise HTTPException(status_code=400, detail="A valid bot token is required")

    try:
        import httpx  # noqa: F401
        from telegram import Bot
        from telegram.request import HTTPXRequest
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="python-telegram-bot is not installed",
        )

    proxy_url = payload.proxy.strip() or None
    if not proxy_url:
        try:
            cfg = get_config()
            proxy_url = cfg.network.proxy_url()
        except Exception:
            pass

    try:
        request = HTTPXRequest(proxy=proxy_url, connect_timeout=10, read_timeout=10)
        bot = Bot(token=payload.bot_token, request=request)
        async with bot:
            me = await bot.get_me()
        return TestTelegramConnectionResponse(
            success=True,
            message=f"Connected to @{me.username}",
            bot_username=me.username or "",
            bot_id=me.id,
        )
    except Exception as exc:
        return TestTelegramConnectionResponse(
            success=False,
            message=str(exc),
        )


@config_router.post("/onboarding-complete", response_model=ConfigResponse)
async def complete_onboarding(config: SystemConfigModel):
    try:
        if config.preferences.user_mode == "quick":
            quick_mode_personality = _load_quick_mode_default_personality(config.preferences.language)
            if quick_mode_personality is not None:
                config.personality = quick_mode_personality
            else:
                logger.warning(
                    "No quick mode personality preset was found for language '%s'; using submitted personality payload",
                    config.preferences.language,
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

        # NOTE: persona registry entries are created by the frontend via
        # ``POST /api/personas/seed`` after this call returns.  We no longer
        # call ``_save_personality_to_user`` here to avoid creating duplicate
        # non-builtin entries that conflict with the seeded builtins.

        return ConfigResponse(success=True, message="Onboarding configuration saved", data=_build_system_config())
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to complete onboarding")
        raise HTTPException(status_code=500, detail=str(exc))
