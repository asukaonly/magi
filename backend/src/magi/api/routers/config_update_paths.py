"""Helpers that translate config API models into persisted config paths."""

from __future__ import annotations

from typing import Any, Dict

from ... import i18n as core_i18n
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    find_provider_meta,
    resolve_embedding_dimension,
    resolve_llm_profile,
    resolve_provider_plan_meta,
)
from ...config.models import (
    LLMCapabilitiesSettings,
    LLMLimitsSettings,
    LLMSelectionLimitsSettings,
)
from ..services.config_secrets import normalize_masked_secrets
from ..services.llm_testing_service import get_llm_provider_registry
from .config_schemas import LLMSelectionConfigModel, SystemConfigModel

CHAT_SCENARIOS = {"auxiliary", "core", "memory_summarizer"}


def _provider_type_value(provider: Any) -> str:
    return (
        str(
            getattr(
                getattr(provider, "provider_type", ""),
                "value",
                getattr(provider, "provider_type", ""),
            )
            or ""
        )
        .strip()
        .lower()
    )


def _provider_plan_value(provider: Any) -> str | None:
    return str(getattr(provider, "provider_plan", "") or "").strip().lower() or None


def _provider_meta_for_selection(
    config: SystemConfigModel,
    registry: LLMProviderRegistryModel,
    provider_id: str,
):
    provider = config.llm.providers.get(provider_id)
    if provider is None:
        return None
    provider_meta = find_provider_meta(registry, _provider_type_value(provider) or provider_id)
    if provider_meta is None:
        return None
    return resolve_provider_plan_meta(provider_meta, _provider_plan_value(provider))


def selection_limits_from_registry_limits(
    limits: LLMLimitsSettings | None,
) -> LLMSelectionLimitsSettings:
    if limits is None:
        return LLMSelectionLimitsSettings()
    return LLMSelectionLimitsSettings(
        context_window=limits.context_window,
        max_output_tokens=limits.max_output_tokens,
        max_tool_schemas=limits.max_tool_schemas,
        max_schema_tokens=limits.max_schema_tokens,
    )


def normalize_masked_config_secrets(
    config: SystemConfigModel, runtime_config: Any
) -> SystemConfigModel:
    return normalize_masked_secrets(config, runtime_config)


def apply_llm_registry_defaults(
    config: SystemConfigModel, registry: LLMProviderRegistryModel
) -> None:
    _apply_provider_registry_defaults(config, registry)
    _apply_selection_registry_defaults(config, registry)


def _apply_provider_registry_defaults(
    config: SystemConfigModel,
    registry: LLMProviderRegistryModel,
) -> None:
    for provider_id, provider in config.llm.providers.items():
        provider_type = _provider_type_value(provider) or provider_id
        base_provider_meta = find_provider_meta(registry, provider_type)
        if base_provider_meta is None:
            continue
        provider_meta = resolve_provider_plan_meta(
            base_provider_meta,
            _provider_plan_value(provider),
        )

        provider.provider_type = provider_type
        if not provider.display_name:
            provider.display_name = base_provider_meta.display_name or provider_id.upper()
        if not (provider.base_url or "").strip():
            provider.base_url = provider_meta.default_base_url


def _apply_selection_registry_defaults(
    config: SystemConfigModel,
    registry: LLMProviderRegistryModel,
) -> None:
    for selection_id, selection in config.llm.selections.items():
        if not selection.provider_id:
            continue

        provider_meta = _provider_meta_for_selection(config, registry, selection.provider_id)
        if provider_meta is None:
            continue

        if selection_id == "embedding":
            _apply_embedding_selection_defaults(
                config=config,
                registry=registry,
                selection_id=selection_id,
                provider_meta=provider_meta,
            )
            continue

        _apply_chat_selection_defaults(
            config=config,
            registry=registry,
            selection_id=selection_id,
            provider_meta=provider_meta,
        )


def _apply_embedding_selection_defaults(
    *,
    config: SystemConfigModel,
    registry: LLMProviderRegistryModel,
    selection_id: str,
    provider_meta: Any,
) -> None:
    selection = config.llm.selections[selection_id]
    embedding_model_meta = find_embedding_model_meta(
        registry,
        str(provider_meta.id),
        selection.model,
        _provider_plan_value(config.llm.providers.get(selection.provider_id)),
    )
    if embedding_model_meta is None and provider_meta.embedding_models:
        selection.model = provider_meta.embedding_models[0].id
        embedding_model_meta = provider_meta.embedding_models[0]

    selection.embedding_dimension = resolve_embedding_dimension(
        embedding_model_meta,
        selection.embedding_dimension,
    )
    if selection.capability_override_enabled:
        return
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
            selection_limits_from_registry_limits(embedding_model_meta.limits)
            if embedding_model_meta is not None
            else selection.limits
        ),
        provider_options=(
            dict(embedding_model_meta.provider_options_example)
            if embedding_model_meta is not None
            else {}
        ),
    )


def _apply_chat_selection_defaults(
    *,
    config: SystemConfigModel,
    registry: LLMProviderRegistryModel,
    selection_id: str,
    provider_meta: Any,
) -> None:
    selection = config.llm.selections[selection_id]
    if not selection.model:
        selection.model = _default_chat_model_for_selection(selection_id, provider_meta)

    if selection.capability_override_enabled or not selection.model:
        return
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
        limits=selection_limits_from_registry_limits(resolved.limits),
        provider_options=resolved.provider_options,
    )


def _default_chat_model_for_selection(selection_id: str, provider_meta: Any) -> str:
    if selection_id == "auxiliary":
        return (
            provider_meta.default_classify_model
            or provider_meta.default_model
            or (provider_meta.chat_models[0].id if provider_meta.chat_models else "")
        )
    return provider_meta.default_model or (
        provider_meta.chat_models[0].id if provider_meta.chat_models else ""
    )


def prune_sparse_value(value: Any) -> Any:
    """Remove None leaves and empty dict nodes from persisted config payloads."""
    if isinstance(value, dict):
        pruned: Dict[str, Any] = {}
        for key, item in value.items():
            next_value = prune_sparse_value(item)
            if next_value is None:
                continue
            if isinstance(next_value, dict) and not next_value:
                continue
            pruned[key] = next_value
        return pruned
    if isinstance(value, list):
        return [prune_sparse_value(item) for item in value]
    return value


def build_full_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    apply_llm_registry_defaults(config, get_llm_provider_registry())
    personality_settings = config.personalitySettings.normalized()
    _validate_llm_selections(config)

    updates: Dict[str, Any] = {}
    updates.update(_agent_update_paths(config))
    updates.update(_llm_update_paths(config))
    updates.update(_memory_update_paths(config))
    updates.update(_preferences_update_paths(config))
    updates["diagnostics"] = config.diagnostics.model_dump(mode="json")
    updates.update(_personality_update_paths(config, personality_settings))
    updates.update(_timeline_update_paths(config))
    updates["tools.skills"] = config.skills
    return updates


def build_onboarding_update_paths(
    config: SystemConfigModel,
    *,
    complete: bool,
) -> Dict[str, Any]:
    """Build the only configuration paths owned by onboarding."""
    apply_llm_registry_defaults(config, get_llm_provider_registry())
    _validate_llm_selections(config)

    updates = _llm_update_paths(config)
    updates["preferences.language"] = core_i18n.app_language_code(config.preferences.language)
    if complete:
        updates["preferences.onboarding_completed"] = True
        updates["preferences.product_tour_completed"] = True
    return updates


def _validate_llm_selections(config: SystemConfigModel) -> None:
    for selection_id, selection in config.llm.selections.items():
        if not str(selection.provider_id or "").strip():
            continue
        provider = config.llm.providers.get(selection.provider_id)
        if provider is None:
            raise ValueError(
                core_i18n.t(
                    "config.validation.llm_selection_unknown_provider",
                    fallback="LLM selection '{selection_id}' references unknown provider '{provider_id}'",
                    selection_id=selection_id,
                    provider_id=selection.provider_id,
                )
            )
        if not provider.enabled:
            raise ValueError(
                core_i18n.t(
                    "config.validation.llm_selection_disabled_provider",
                    fallback="LLM selection '{selection_id}' references disabled provider '{provider_id}'",
                    selection_id=selection_id,
                    provider_id=selection.provider_id,
                )
            )
        if selection_id in CHAT_SCENARIOS and not provider.services.chat.enabled:
            raise ValueError(
                core_i18n.t(
                    "config.validation.llm_selection_chat_disabled",
                    fallback="LLM selection '{selection_id}' references provider '{provider_id}' with chat disabled",
                    selection_id=selection_id,
                    provider_id=selection.provider_id,
                )
            )
        if selection_id == "embedding" and not provider.services.embedding.enabled:
            raise ValueError(
                core_i18n.t(
                    "config.validation.llm_selection_embedding_disabled",
                    fallback="LLM selection '{selection_id}' references provider '{provider_id}' with embedding disabled",
                    selection_id=selection_id,
                    provider_id=selection.provider_id,
                )
            )
        if selection_id == "image_generation" and not provider.services.image_generation.enabled:
            raise ValueError(
                core_i18n.t(
                    "config.validation.llm_selection_image_generation_disabled",
                    fallback=(
                        "LLM selection '{selection_id}' references provider '{provider_id}' "
                        "with image generation disabled"
                    ),
                    selection_id=selection_id,
                    provider_id=selection.provider_id,
                )
            )


def _agent_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    return {
        "agent.name": config.agent.name,
        "agent.description": config.agent.description,
    }


def _llm_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    llm_providers: Dict[str, Any] = {}
    for provider_id, provider in config.llm.providers.items():
        llm_providers[provider_id] = prune_sparse_value(provider.model_dump(exclude_none=True))

    model_runtime_overrides = {
        runtime_key: prune_sparse_value(limits.model_dump(exclude_none=True))
        for runtime_key, limits in config.llm.model_runtime_overrides.items()
    }

    return {
        "llm.providers": llm_providers,
        "llm.selections": {
            selection_id: prune_sparse_value(selection.model_dump(exclude_none=True))
            for selection_id, selection in config.llm.selections.items()
            if str(selection.provider_id or "").strip() and str(selection.model or "").strip()
        },
        "llm.model_runtime_overrides": model_runtime_overrides,
    }


def _memory_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    return {
        "agent.memory.db_path": config.memory.db_path,
        "agent.memory.embedding.mode": config.memory.embedding.mode,
        "agent.memory.embedding.local.model_source": config.memory.embedding.local.model_source,
        "agent.memory.embedding.local.managed_model_id": config.memory.embedding.local.managed_model_id,
        "agent.memory.embedding.local.model_dir_path": config.memory.embedding.local.model_dir_path,
        "agent.memory.embedding.local.idle_timeout_seconds": config.memory.embedding.local.idle_timeout_seconds,
        "agent.memory.embedding.local.variant": config.memory.embedding.local.variant,
        "agent.memory.retention_days": config.memory.retention_days,
        "agent.memory.history_behavior": config.memory.history_behavior,
        "agent.memory.archive_path": config.memory.archive_path,
        "agent.memory.reranker.top_k": config.memory.reranker.top_k,
        "agent.memory.reranker.cross_encoder.enabled": config.memory.reranker.cross_encoder.enabled,
        "agent.memory.reranker.cross_encoder.managed_model_id": config.memory.reranker.cross_encoder.managed_model_id,
        "agent.memory.query_expansion.enabled": config.memory.query_expansion.enabled,
        "agent.memory.query_expansion.max_expansions": config.memory.query_expansion.max_expansions,
        "agent.memory.graph_spreading.enabled": config.memory.graph_spreading.enabled,
        "agent.memory.entity_semantic_edges.enabled": config.memory.entity_semantic_edges.enabled,
        "agent.memory.l0.enabled": config.memory.l0.enabled,
        "agent.memory.l0.checkpoint_interval_seconds": config.memory.l0.checkpoint_interval_seconds,
        "agent.memory.l0.attention_update_turn_threshold": config.memory.l0.attention_update_turn_threshold,
        "agent.memory.l0.attention_update_idle_seconds": config.memory.l0.attention_update_idle_seconds,
        "agent.memory.l0.attention_update_max_delay_seconds": config.memory.l0.attention_update_max_delay_seconds,
        "agent.memory.l1.enabled": config.memory.l1.enabled,
        "agent.memory.l1.retention_days": config.memory.l1.retention_days,
        "agent.memory.l1.vectors_enabled": config.memory.l1.vectors_enabled,
        "agent.memory.l2.enabled": config.memory.l2.enabled,
        "agent.memory.l2.vectors_enabled": config.memory.l2.vectors_enabled,
        "agent.memory.l2.batch_flush_interval_seconds": config.memory.l2.batch_flush_interval_seconds,
        "agent.memory.l2.auto_extract_relations": config.memory.l2.auto_extract_relations,
        "agent.memory.l2.shadow_conflict_notification_enabled": config.memory.l2.shadow_conflict_notification_enabled,
        "agent.memory.l2.portrait_projection_refresh_delay_seconds": config.memory.l2.portrait_projection_refresh_delay_seconds,
        "agent.memory.l3.enabled": config.memory.l3.enabled,
        "agent.memory.l3.retention_days": config.memory.l3.retention_days,
        "agent.memory.l3.vectors_enabled": config.memory.l3.vectors_enabled,
        "agent.memory.l3.llm_summary_enabled": config.memory.l3.llm_summary_enabled,
        "agent.memory.l3.temporal_llm_timeout_seconds": config.memory.l3.temporal_llm_timeout_seconds,
        "agent.memory.l3.temporal_llm_min_event_count": config.memory.l3.temporal_llm_min_event_count,
        "agent.memory.l3.summary_interval_minutes": config.memory.l3.summary_interval_minutes,
        "agent.memory.l4.enabled": config.memory.l4.enabled,
        "agent.memory.l4.vectors_enabled": config.memory.l4.vectors_enabled,
        "agent.memory.l4.inactive_skill_retention_days": config.memory.l4.inactive_skill_retention_days,
        "agent.memory.l4.inactive_skill_min_attempts": config.memory.l4.inactive_skill_min_attempts,
    }


def _preferences_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    return {
        # mode="json" is required: preferences.suggestion_dismissals holds
        # DismissalRecord values whose ``kind`` is a DismissalKind enum and
        # ``dismissed_at`` a datetime. A plain model_dump() keeps those as native
        # objects, which yaml.safe_dump cannot represent — truncating agent.yaml
        # on save. JSON mode renders them as plain scalars.
        "preferences": prune_sparse_value(
            config.preferences.model_dump(mode="json", exclude_none=True)
        ),
        "network": config.network.model_dump(),
    }


def _personality_update_paths(
    config: SystemConfigModel,
    personality_settings: Any,
) -> Dict[str, Any]:
    return {
        "agent.personality.name": config.personality.name if config.personality.name else "default",
        "agent.personality.path": "~/.magi/personalities",
        "agent.personality.enable_evolution": personality_settings.state_memory_enabled,
        "agent.personality.enable_state_memory": personality_settings.state_memory_enabled,
        "agent.personality.enable_state_transition": personality_settings.state_transition_enabled,
        "agent.personality.enable_deep_persona": personality_settings.deep_persona_enabled,
    }


def _timeline_update_paths(config: SystemConfigModel) -> Dict[str, Any]:
    return {
        "timeline": prune_sparse_value(config.timeline.model_dump(exclude_none=True)),
    }


__all__ = [
    "apply_llm_registry_defaults",
    "build_full_update_paths",
    "build_onboarding_update_paths",
    "normalize_masked_config_secrets",
    "prune_sparse_value",
    "selection_limits_from_registry_limits",
]
