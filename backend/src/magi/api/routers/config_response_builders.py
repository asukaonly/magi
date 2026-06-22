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
from ..services.config_secrets import mask_api_key
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
        embedding=EmbeddingConfigModel(
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
            vectors_enabled=memory_cfg.l2.vectors_enabled,
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
    mask_api_key: bool,
) -> LLMConfigModel:
    providers: Dict[str, LLMProviderConfigModel] = {}
    for provider_id, provider in getattr(runtime_config.llm, "providers", {}).items():
        services = getattr(provider, "services", None)
        chat = getattr(services, "chat", None)
        embedding = getattr(services, "embedding", None)
        image_generation = getattr(services, "image_generation", None)
        tts = getattr(services, "tts", None)
        provider_api_key = getattr(provider, "api_key", None)
        chat_api_key = getattr(chat, "api_key", None)
        embedding_api_key = getattr(embedding, "api_key", None)
        image_api_key = getattr(image_generation, "api_key", None)
        tts_api_key = getattr(tts, "api_key", None)
        providers[provider_id] = LLMProviderConfigModel(
            enabled=provider.enabled,
            provider_type=str(getattr(provider.provider_type, "value", provider.provider_type)),
            display_name=provider.display_name,
            provider_plan=getattr(provider, "provider_plan", None),
            api_key=(
                mask_api_key_value(provider_api_key)
                if (mask_api_key and provider_api_key)
                else provider_api_key
            ),
            base_url=getattr(provider, "base_url", None),
            services=LLMProviderServicesConfigModel(
                chat=LLMProviderConnectionConfigModel(
                    enabled=getattr(chat, "enabled", True),
                    api_key=(
                        mask_api_key_value(chat_api_key)
                        if (mask_api_key and chat_api_key)
                        else chat_api_key
                    ),
                    base_url=getattr(chat, "base_url", None),
                ),
                embedding=LLMProviderConnectionConfigModel(
                    enabled=getattr(embedding, "enabled", True),
                    api_key=(
                        mask_api_key_value(embedding_api_key)
                        if (mask_api_key and embedding_api_key)
                        else embedding_api_key
                    ),
                    base_url=getattr(embedding, "base_url", None),
                ),
                image_generation=LLMProviderImageGenerationConfigModel(
                    enabled=getattr(image_generation, "enabled", False),
                    api_key=(
                        mask_api_key_value(image_api_key)
                        if (mask_api_key and image_api_key)
                        else image_api_key
                    ),
                    base_url=getattr(image_generation, "base_url", None),
                    timeout=getattr(image_generation, "timeout", 180),
                    native_protocol=getattr(image_generation, "native_protocol", None),
                ),
                tts=LLMProviderTTSConfigModel(
                    enabled=getattr(tts, "enabled", False),
                    api_key=(
                        mask_api_key_value(tts_api_key)
                        if (mask_api_key and tts_api_key)
                        else tts_api_key
                    ),
                    base_url=getattr(tts, "base_url", None),
                    model=getattr(tts, "model", None),
                    voice=getattr(tts, "voice", None),
                    response_format=getattr(tts, "response_format", None),
                ),
            ),
            api_format=provider.api_format,
            custom_models=list(getattr(provider, "custom_models", []) or []),
            custom_default_model=getattr(provider, "custom_default_model", None),
            model_metadata_overrides=dict(getattr(provider, "model_metadata_overrides", {}) or {}),
        )

    selections: Dict[str, LLMSelectionConfigModel] = {}
    for selection_id, selection in getattr(runtime_config.llm, "selections", {}).items():
        provider_settings = runtime_config.llm.providers.get(selection.provider_id)
        provider_lookup_id = selection.provider_id
        if provider_settings is not None:
            provider_lookup_id = str(
                getattr(
                    getattr(provider_settings, "provider_type", ""),
                    "value",
                    getattr(provider_settings, "provider_type", ""),
                )
                or selection.provider_id
            )
        if selection_id == "embedding":
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
                    selection_limits_from_registry_limits(embedding_meta.limits)
                    if embedding_meta is not None
                    and not bool(selection.capability_override_enabled)
                    else selection.limits
                ),
                provider_options=provider_options,
            )
            continue

        resolved = resolve_llm_profile(
            selection,
            registry,
            provider_settings=provider_settings,
        )
        selections[selection_id] = LLMSelectionConfigModel(
            provider_id=selection.provider_id,
            model=selection.model,
            embedding_dimension=getattr(selection, "embedding_dimension", None),
            capability_override_enabled=bool(selection.capability_override_enabled),
            capabilities=resolved.capabilities,
            limits=selection_limits_from_registry_limits(resolved.limits),
            provider_options=resolved.provider_options,
        )

    return LLMConfigModel(
        providers=providers,
        selections=selections,
        model_runtime_overrides=dict(
            getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}
        ),
    )


def mask_api_key_value(api_key: str) -> str:
    return mask_api_key(api_key)


__all__ = [
    "build_llm_config_model",
    "build_memory_config",
    "build_tools",
    "load_full_personality",
    "mask_api_key_value",
]
