"""Builders for projecting runtime configuration into config API models."""

from __future__ import annotations

from typing import Any, Dict

from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from ...config.models import LLMCapabilitiesSettings
from ...core.logger import get_logger
from .config_schemas import (
    BuiltInToolsConfigModel,
    CrossEncoderConfigModel,
    EmbeddingConfigModel,
    EmbeddingLocalConfigModel,
    EntitySemanticEdgeConfigModel,
    FullPersonalityConfigModel,
    GraphSpreadingConfigModel,
    LLMConfigModel,
    LLMProviderConnectionConfigModel,
    LLMProviderImageGenerationConfigModel,
    LLMProviderConfigModel,
    LLMProviderServicesConfigModel,
    LLMProviderTTSConfigModel,
    LLMSelectionConfigModel,
    MemoryConfigModel,
    MemoryL0ConfigModel,
    MemoryL1ConfigModel,
    MemoryL2ConfigModel,
    MemoryL3ConfigModel,
    MemoryL4ConfigModel,
    MemoryRerankerConfigModel,
    QueryExpansionConfigModel,
    ToolsConfigModel,
    WeatherToolConfigModel,
    WebFetchToolConfigModel,
    WebSearchToolConfigModel,
)
from .config_update_paths import selection_limits_from_registry_limits

logger = get_logger(__name__)


def build_memory_config(raw: Dict[str, Any], runtime_config: Any) -> MemoryConfigModel:
    memory_cfg = runtime_config.agent.memory
    return MemoryConfigModel(
        db_path=memory_cfg.db_path,
        retention_days=memory_cfg.retention_days,
        history_behavior=getattr(
            memory_cfg.history_behavior, "value", str(memory_cfg.history_behavior)
        ),
        archive_path=memory_cfg.archive_path,
        embedding=_build_memory_embedding_config(memory_cfg),
        reranker=_build_memory_reranker_config(memory_cfg),
        query_expansion=_build_query_expansion_config(memory_cfg),
        graph_spreading=GraphSpreadingConfigModel(enabled=memory_cfg.graph_spreading.enabled),
        entity_semantic_edges=EntitySemanticEdgeConfigModel(
            enabled=memory_cfg.entity_semantic_edges.enabled
        ),
        l0=_build_memory_l0_config(memory_cfg),
        l1=_build_memory_l1_config(memory_cfg),
        l2=_build_memory_l2_config(memory_cfg),
        l3=_build_memory_l3_config(memory_cfg),
        l4=_build_memory_l4_config(memory_cfg),
    )


def _build_memory_embedding_config(memory_cfg: Any) -> EmbeddingConfigModel:
    return EmbeddingConfigModel(
        mode=getattr(memory_cfg.embedding.mode, "value", str(memory_cfg.embedding.mode)),
        local=EmbeddingLocalConfigModel(
            model_source=getattr(
                memory_cfg.embedding.local.model_source,
                "value",
                str(memory_cfg.embedding.local.model_source),
            ),
            managed_model_id=memory_cfg.embedding.local.managed_model_id,
            model_dir_path=memory_cfg.embedding.local.model_dir_path,
            idle_timeout_seconds=memory_cfg.embedding.local.idle_timeout_seconds,
            variant=memory_cfg.embedding.local.variant,
        ),
    )


def _build_memory_reranker_config(memory_cfg: Any) -> MemoryRerankerConfigModel:
    return MemoryRerankerConfigModel(
        top_k=memory_cfg.reranker.top_k,
        cross_encoder=CrossEncoderConfigModel(
            enabled=memory_cfg.reranker.cross_encoder.enabled,
            managed_model_id=memory_cfg.reranker.cross_encoder.managed_model_id,
        ),
    )


def _build_query_expansion_config(memory_cfg: Any) -> QueryExpansionConfigModel:
    return QueryExpansionConfigModel(
        enabled=memory_cfg.query_expansion.enabled,
        max_expansions=memory_cfg.query_expansion.max_expansions,
    )


def _build_memory_l0_config(memory_cfg: Any) -> MemoryL0ConfigModel:
    return MemoryL0ConfigModel(
        enabled=memory_cfg.l0.enabled,
        checkpoint_interval_seconds=memory_cfg.l0.checkpoint_interval_seconds,
        attention_update_turn_threshold=memory_cfg.l0.attention_update_turn_threshold,
        attention_update_idle_seconds=memory_cfg.l0.attention_update_idle_seconds,
        attention_update_max_delay_seconds=memory_cfg.l0.attention_update_max_delay_seconds,
    )


def _build_memory_l1_config(memory_cfg: Any) -> MemoryL1ConfigModel:
    return MemoryL1ConfigModel(
        enabled=memory_cfg.l1.enabled,
        retention_days=memory_cfg.l1.retention_days,
        vectors_enabled=memory_cfg.l1.vectors_enabled,
    )


def _build_memory_l2_config(memory_cfg: Any) -> MemoryL2ConfigModel:
    return MemoryL2ConfigModel(
        enabled=memory_cfg.l2.enabled,
        vectors_enabled=memory_cfg.l2.vectors_enabled,
        batch_flush_interval_seconds=memory_cfg.l2.batch_flush_interval_seconds,
        auto_extract_relations=memory_cfg.l2.auto_extract_relations,
        shadow_conflict_notification_enabled=memory_cfg.l2.shadow_conflict_notification_enabled,
        portrait_projection_refresh_delay_seconds=(
            memory_cfg.l2.portrait_projection_refresh_delay_seconds
        ),
    )


def _build_memory_l3_config(memory_cfg: Any) -> MemoryL3ConfigModel:
    return MemoryL3ConfigModel(
        enabled=memory_cfg.l3.enabled,
        retention_days=memory_cfg.l3.retention_days,
        vectors_enabled=memory_cfg.l3.vectors_enabled,
        llm_summary_enabled=memory_cfg.l3.llm_summary_enabled,
        temporal_llm_timeout_seconds=memory_cfg.l3.temporal_llm_timeout_seconds,
        temporal_llm_min_event_count=memory_cfg.l3.temporal_llm_min_event_count,
    )


def _build_memory_l4_config(memory_cfg: Any) -> MemoryL4ConfigModel:
    return MemoryL4ConfigModel(
        enabled=memory_cfg.l4.enabled,
        vectors_enabled=memory_cfg.l4.vectors_enabled,
        inactive_skill_retention_days=memory_cfg.l4.inactive_skill_retention_days,
        inactive_skill_min_attempts=memory_cfg.l4.inactive_skill_min_attempts,
    )


def build_tools(raw: Dict[str, Any], runtime_config: Any) -> ToolsConfigModel:
    tools_raw = raw.get("tools", {}) if isinstance(raw.get("tools"), dict) else {}
    built_in = tools_raw.get("builtIn", {}) if isinstance(tools_raw.get("builtIn"), dict) else {}

    weather_runtime = runtime_config.tools.weather
    web_search_runtime = runtime_config.tools.web_search
    web_fetch_runtime = runtime_config.tools.web_fetch

    weather_provider = built_in.get("weather", {}).get("provider", weather_runtime.default_provider)
    weather_provider_cfg = weather_runtime.providers.get(weather_provider)

    web_search_provider = built_in.get("webSearch", {}).get(
        "provider", web_search_runtime.default_provider
    )
    web_search_provider_cfg = web_search_runtime.providers.get(web_search_provider)

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
                apiUrl=(web_search_provider_cfg.base_url if web_search_provider_cfg else None),
            ),
            webFetch=WebFetchToolConfigModel(
                enabled=web_fetch_runtime.enabled,
                allowRfc2544BenchmarkRange=(web_fetch_runtime.allow_rfc2544_benchmark_range),
                allowPrivateNetworkFetch=web_fetch_runtime.allow_private_network,
                privateNetworkAllowlist=list(web_fetch_runtime.private_network_allowlist),
            ),
        ),
        skills=tools_raw.get("skills", []),
    )


def load_full_personality() -> FullPersonalityConfigModel:
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


def build_llm_config_model(
    *,
    runtime_config: Any,
    raw_llm: Dict[str, Any],
    registry: LLMProviderRegistryModel,
) -> LLMConfigModel:
    providers: Dict[str, LLMProviderConfigModel] = {}
    for provider_id, provider in getattr(runtime_config.llm, "providers", {}).items():
        providers[provider_id] = _build_llm_provider_config(provider)

    selections: Dict[str, LLMSelectionConfigModel] = {}
    for selection_id, selection in getattr(runtime_config.llm, "selections", {}).items():
        selections[selection_id] = _build_llm_selection_config(
            runtime_config=runtime_config,
            registry=registry,
            selection_id=selection_id,
            selection=selection,
        )

    return LLMConfigModel(
        providers=providers,
        selections=selections,
        model_runtime_overrides=dict(
            getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}
        ),
    )


def _build_llm_provider_config(
    provider: Any,
) -> LLMProviderConfigModel:
    return LLMProviderConfigModel(
        enabled=provider.enabled,
        provider_type=str(getattr(provider.provider_type, "value", provider.provider_type)),
        display_name=provider.display_name,
        provider_plan=getattr(provider, "provider_plan", None),
        api_key=getattr(provider, "api_key", None),
        base_url=getattr(provider, "base_url", None),
        services=_build_llm_provider_services_config(provider),
        api_format=provider.api_format,
        custom_models=list(getattr(provider, "custom_models", []) or []),
        custom_default_model=getattr(provider, "custom_default_model", None),
        model_metadata_overrides=dict(getattr(provider, "model_metadata_overrides", {}) or {}),
    )


def _build_llm_provider_services_config(
    provider: Any,
) -> LLMProviderServicesConfigModel:
    services = getattr(provider, "services", None)
    chat = getattr(services, "chat", None)
    embedding = getattr(services, "embedding", None)
    image_generation = getattr(services, "image_generation", None)
    tts = getattr(services, "tts", None)
    return LLMProviderServicesConfigModel(
        chat=_build_provider_connection_config(chat, default_enabled=True),
        embedding=_build_provider_connection_config(
            embedding,
            default_enabled=True,
        ),
        image_generation=_build_image_generation_connection_config(image_generation),
        tts=_build_tts_connection_config(tts),
    )


def _build_provider_connection_config(
    service: Any,
    *,
    default_enabled: bool,
) -> LLMProviderConnectionConfigModel:
    return LLMProviderConnectionConfigModel(
        enabled=getattr(service, "enabled", default_enabled),
        api_key=getattr(service, "api_key", None),
        base_url=getattr(service, "base_url", None),
    )


def _build_image_generation_connection_config(
    image_generation: Any,
) -> LLMProviderImageGenerationConfigModel:
    return LLMProviderImageGenerationConfigModel(
        enabled=getattr(image_generation, "enabled", False),
        api_key=getattr(image_generation, "api_key", None),
        base_url=getattr(image_generation, "base_url", None),
        timeout=getattr(image_generation, "timeout", 180),
        native_protocol=getattr(image_generation, "native_protocol", None),
    )


def _build_tts_connection_config(
    tts: Any,
) -> LLMProviderTTSConfigModel:
    return LLMProviderTTSConfigModel(
        enabled=getattr(tts, "enabled", False),
        api_key=getattr(tts, "api_key", None),
        base_url=getattr(tts, "base_url", None),
        model=getattr(tts, "model", None),
        voice=getattr(tts, "voice", None),
        response_format=getattr(tts, "response_format", None),
    )


def _build_llm_selection_config(
    *,
    runtime_config: Any,
    registry: LLMProviderRegistryModel,
    selection_id: str,
    selection: Any,
) -> LLMSelectionConfigModel:
    provider_settings = runtime_config.llm.providers.get(selection.provider_id)
    provider_lookup_id = _provider_lookup_id_for_selection(selection, provider_settings)
    if selection_id == "embedding":
        return _build_embedding_selection_config(
            registry=registry,
            selection=selection,
            provider_settings=provider_settings,
            provider_lookup_id=provider_lookup_id,
        )
    return _build_chat_selection_config(
        registry=registry,
        selection=selection,
        provider_settings=provider_settings,
    )


def _provider_lookup_id_for_selection(selection: Any, provider_settings: Any) -> str:
    if provider_settings is None:
        return selection.provider_id
    return str(
        getattr(
            getattr(provider_settings, "provider_type", ""),
            "value",
            getattr(provider_settings, "provider_type", ""),
        )
        or selection.provider_id
    )


def _build_embedding_selection_config(
    *,
    registry: LLMProviderRegistryModel,
    selection: Any,
    provider_settings: Any,
    provider_lookup_id: str,
) -> LLMSelectionConfigModel:
    embedding_meta = find_embedding_model_meta(
        registry,
        provider_lookup_id,
        selection.model,
        (
            getattr(provider_settings, "provider_plan", None)
            if provider_settings is not None
            else None
        ),
    )
    capability_override_enabled = bool(selection.capability_override_enabled)
    capabilities, provider_options = _embedding_selection_capabilities_and_options(
        selection,
        embedding_meta,
        capability_override_enabled=capability_override_enabled,
    )
    return LLMSelectionConfigModel(
        provider_id=selection.provider_id,
        model=selection.model,
        embedding_dimension=resolve_embedding_dimension(
            embedding_meta,
            getattr(selection, "embedding_dimension", None),
        ),
        capability_override_enabled=capability_override_enabled,
        capabilities=capabilities,
        limits=(
            selection_limits_from_registry_limits(embedding_meta.limits)
            if embedding_meta is not None and not capability_override_enabled
            else selection.limits
        ),
        provider_options=provider_options,
    )


def _embedding_selection_capabilities_and_options(
    selection: Any,
    embedding_meta: Any,
    *,
    capability_override_enabled: bool,
) -> tuple[LLMCapabilitiesSettings, Dict[str, Any]]:
    if capability_override_enabled:
        return selection.capabilities, dict(selection.provider_options or {})
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
    return capabilities, provider_options


def _build_chat_selection_config(
    *,
    registry: LLMProviderRegistryModel,
    selection: Any,
    provider_settings: Any,
) -> LLMSelectionConfigModel:
    resolved = resolve_llm_profile(
        selection,
        registry,
        provider_settings=provider_settings,
    )
    return LLMSelectionConfigModel(
        provider_id=selection.provider_id,
        model=selection.model,
        embedding_dimension=getattr(selection, "embedding_dimension", None),
        capability_override_enabled=bool(selection.capability_override_enabled),
        capabilities=resolved.capabilities,
        limits=selection_limits_from_registry_limits(resolved.limits),
        provider_options=resolved.provider_options,
    )


__all__ = [
    "build_llm_config_model",
    "build_memory_config",
    "build_tools",
    "load_full_personality",
]
