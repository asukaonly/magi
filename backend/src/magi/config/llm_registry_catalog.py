"""Provider catalog assembly for the LLM provider registry."""

from __future__ import annotations

from typing import Dict, Optional

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
    catalog_entries: list[LLMProviderCatalogEntryModel] = []

    for provider_meta in registry.providers:
        provider_settings = provider_settings_by_id.get(provider_meta.id)
        catalog_entries.append(
            _build_builtin_template_entry(registry, provider_meta, provider_settings)
        )

    for provider_id, provider_settings in provider_settings_by_id.items():
        provider_type = _provider_type_value(provider_settings)
        if provider_id == provider_type:
            continue

        resolved_catalog = resolve_provider_model_catalog(
            registry,
            provider_id,
            provider_settings,
        )
        provider_meta = next(
            (item for item in registry.providers if item.id == provider_type), None
        )
        effective_meta = (
            resolve_provider_plan_meta(provider_meta, _provider_plan_value(provider_settings))
            if provider_meta is not None
            else None
        )
        is_custom = provider_type == LLMProvider.CUSTOM.value
        default_model = getattr(provider_settings, "custom_default_model", None)
        if not default_model and provider_settings.custom_models:
            default_model = provider_settings.custom_models[0]
        if not default_model and effective_meta is not None:
            default_model = effective_meta.default_model
        catalog_entries.append(
            LLMProviderCatalogEntryModel(
                id=provider_id,
                provider_type=provider_type or "custom",
                source="custom" if is_custom else "builtin",
                display_name=(
                    provider_settings.display_name
                    or (registry.custom_provider.display_name if is_custom else None)
                    or (provider_meta.display_name if provider_meta is not None else None)
                    or provider_id
                ),
                description=(
                    registry.custom_provider.description
                    if is_custom
                    else (effective_meta.description if effective_meta is not None else None)
                ),
                icon=(
                    registry.custom_provider.icon
                    if is_custom
                    else (effective_meta.icon if effective_meta is not None else None)
                ),
                default_model=default_model,
                default_classify_model=(
                    effective_meta.default_classify_model
                    if effective_meta is not None
                    else default_model
                ),
                provider_plan=_provider_plan_value(provider_settings),
                plans=(
                    [plan.model_copy(deep=True) for plan in provider_meta.plans]
                    if provider_meta is not None
                    else []
                ),
                default_base_url=_chat_base_url(provider_settings)
                or (effective_meta.default_base_url if effective_meta is not None else None),
                api_format=provider_settings.api_format,
                fields=dict(
                    registry.custom_provider.fields
                    if is_custom
                    else (effective_meta.fields if effective_meta is not None else {})
                ),
                resolved_chat_models=resolved_catalog.chat_models,
                resolved_embedding_models=resolved_catalog.embedding_models,
                resolved_image_generation_models=resolved_catalog.image_generation_models,
            )
        )

    return catalog_entries


__all__ = ["build_provider_catalog"]
