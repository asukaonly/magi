"""Provider catalog assembly for the LLM provider registry."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import LLMProvider, LLMProviderSettings
from .llm_registry_model_resolution import (
    resolve_provider_model_catalog,
    resolve_provider_plan_meta,
)
from .llm_registry_models import (
    LLMProviderCatalogEntryModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
)


def _provider_type_value(provider_settings: LLMProviderSettings) -> str:
    return (
        str(
            getattr(
                getattr(provider_settings, "provider_type", ""),
                "value",
                getattr(provider_settings, "provider_type", ""),
            )
            or ""
        )
        .strip()
        .lower()
    )


def _provider_plan_value(provider_settings: LLMProviderSettings | None) -> str | None:
    return (
        str(getattr(provider_settings, "provider_plan", "") or "").strip().lower()
        if provider_settings is not None
        else None
    ) or None


def _chat_base_url(provider_settings: LLMProviderSettings) -> str | None:
    return (
        getattr(getattr(provider_settings.services, "chat", None), "base_url", None)
        or provider_settings.base_url
    )


def _build_builtin_template_entry(
    registry: LLMProviderRegistryModel,
    provider_meta: LLMProviderMetaModel,
    provider_settings: LLMProviderSettings | None = None,
) -> LLMProviderCatalogEntryModel:
    effective_meta = resolve_provider_plan_meta(
        provider_meta,
        _provider_plan_value(provider_settings),
    )
    resolved_catalog = resolve_provider_model_catalog(
        registry,
        provider_meta.id,
        provider_settings,
    )
    return LLMProviderCatalogEntryModel(
        id=provider_meta.id,
        provider_type=provider_meta.id,
        source="builtin",
        display_name=provider_meta.display_name,
        description=provider_meta.description,
        icon=provider_meta.icon,
        default_model=(
            getattr(provider_settings, "custom_default_model", None) or effective_meta.default_model
        ),
        default_classify_model=effective_meta.default_classify_model,
        default_base_url=effective_meta.default_base_url,
        provider_plan=_provider_plan_value(provider_settings),
        plans=[plan.model_copy(deep=True) for plan in provider_meta.plans],
        api_format=getattr(provider_settings, "api_format", None),
        fields=dict(effective_meta.fields),
        resolved_chat_models=resolved_catalog.chat_models,
        resolved_embedding_models=resolved_catalog.embedding_models,
        resolved_image_generation_models=resolved_catalog.image_generation_models,
        image_generation_models=list(effective_meta.image_generation_models),
    )


def build_provider_catalog(
    registry: LLMProviderRegistryModel,
    provider_settings_by_id: Optional[Dict[str, LLMProviderSettings]] = None,
) -> list[LLMProviderCatalogEntryModel]:
    """Build a full provider catalog for builtin and saved custom providers."""

    provider_settings_by_id = provider_settings_by_id or {}
    return [
        *_build_builtin_catalog_entries(registry, provider_settings_by_id),
        *_build_saved_provider_catalog_entries(registry, provider_settings_by_id),
    ]


def _build_builtin_catalog_entries(
    registry: LLMProviderRegistryModel,
    provider_settings_by_id: Dict[str, LLMProviderSettings],
) -> list[LLMProviderCatalogEntryModel]:
    return [
        _build_builtin_template_entry(
            registry,
            provider_meta,
            provider_settings_by_id.get(provider_meta.id),
        )
        for provider_meta in registry.providers
    ]


def _build_saved_provider_catalog_entries(
    registry: LLMProviderRegistryModel,
    provider_settings_by_id: Dict[str, LLMProviderSettings],
) -> list[LLMProviderCatalogEntryModel]:
    entries: list[LLMProviderCatalogEntryModel] = []
    for provider_id, provider_settings in provider_settings_by_id.items():
        provider_type = _provider_type_value(provider_settings)
        if provider_id != provider_type:
            entries.append(_build_saved_provider_entry(registry, provider_id, provider_settings))
    return entries


def _build_saved_provider_entry(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    provider_settings: LLMProviderSettings,
) -> LLMProviderCatalogEntryModel:
    provider_type = _provider_type_value(provider_settings)
    provider_meta = _find_provider_meta(registry, provider_type)
    effective_meta = _resolve_effective_meta(provider_meta, provider_settings)
    resolved_catalog = resolve_provider_model_catalog(registry, provider_id, provider_settings)
    is_custom = provider_type == LLMProvider.CUSTOM.value
    default_model = _saved_provider_default_model(provider_settings, effective_meta)
    return LLMProviderCatalogEntryModel(
        id=provider_id,
        provider_type=provider_type or "custom",
        source="custom" if is_custom else "builtin",
        display_name=_saved_provider_display_name(
            registry,
            provider_id=provider_id,
            provider_settings=provider_settings,
            provider_meta=provider_meta,
            is_custom=is_custom,
        ),
        description=_saved_provider_description(registry, effective_meta, is_custom),
        icon=_saved_provider_icon(registry, effective_meta, is_custom),
        default_model=default_model,
        default_classify_model=(
            effective_meta.default_classify_model if effective_meta is not None else default_model
        ),
        provider_plan=_provider_plan_value(provider_settings),
        plans=_saved_provider_plans(provider_meta),
        default_base_url=_saved_provider_base_url(provider_settings, effective_meta),
        api_format=provider_settings.api_format,
        fields=_saved_provider_fields(registry, effective_meta, is_custom),
        resolved_chat_models=resolved_catalog.chat_models,
        resolved_embedding_models=resolved_catalog.embedding_models,
        resolved_image_generation_models=resolved_catalog.image_generation_models,
    )


def _find_provider_meta(
    registry: LLMProviderRegistryModel,
    provider_type: str,
) -> LLMProviderMetaModel | None:
    return next((item for item in registry.providers if item.id == provider_type), None)


def _resolve_effective_meta(
    provider_meta: LLMProviderMetaModel | None,
    provider_settings: LLMProviderSettings,
) -> LLMProviderMetaModel | None:
    if provider_meta is None:
        return None
    return resolve_provider_plan_meta(provider_meta, _provider_plan_value(provider_settings))


def _saved_provider_default_model(
    provider_settings: LLMProviderSettings,
    effective_meta: LLMProviderMetaModel | None,
) -> str | None:
    default_model = getattr(provider_settings, "custom_default_model", None)
    if not default_model and provider_settings.custom_models:
        default_model = provider_settings.custom_models[0]
    if not default_model and effective_meta is not None:
        default_model = effective_meta.default_model
    return default_model


def _saved_provider_display_name(
    registry: LLMProviderRegistryModel,
    *,
    provider_id: str,
    provider_settings: LLMProviderSettings,
    provider_meta: LLMProviderMetaModel | None,
    is_custom: bool,
) -> str:
    return (
        provider_settings.display_name
        or (registry.custom_provider.display_name if is_custom else None)
        or (provider_meta.display_name if provider_meta is not None else None)
        or provider_id
    )


def _saved_provider_description(
    registry: LLMProviderRegistryModel,
    effective_meta: LLMProviderMetaModel | None,
    is_custom: bool,
) -> str | None:
    if is_custom:
        return registry.custom_provider.description
    return effective_meta.description if effective_meta is not None else None


def _saved_provider_icon(
    registry: LLMProviderRegistryModel,
    effective_meta: LLMProviderMetaModel | None,
    is_custom: bool,
) -> str | None:
    if is_custom:
        return registry.custom_provider.icon
    return effective_meta.icon if effective_meta is not None else None


def _saved_provider_plans(
    provider_meta: LLMProviderMetaModel | None,
) -> list[Any]:
    if provider_meta is None:
        return []
    return [plan.model_copy(deep=True) for plan in provider_meta.plans]


def _saved_provider_base_url(
    provider_settings: LLMProviderSettings,
    effective_meta: LLMProviderMetaModel | None,
) -> str | None:
    return _chat_base_url(provider_settings) or (
        effective_meta.default_base_url if effective_meta is not None else None
    )


def _saved_provider_fields(
    registry: LLMProviderRegistryModel,
    effective_meta: LLMProviderMetaModel | None,
    is_custom: bool,
) -> dict[str, Any]:
    if is_custom:
        return dict(registry.custom_provider.fields)
    return dict(effective_meta.fields if effective_meta is not None else {})


__all__ = ["build_provider_catalog"]
