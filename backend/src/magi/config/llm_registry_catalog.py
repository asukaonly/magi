"""Provider catalog assembly for the LLM provider registry."""

from __future__ import annotations

from typing import Dict, Optional

from .models import LLMProviderSettings
from .llm_registry_model_resolution import resolve_provider_model_catalog
from .llm_registry_models import LLMProviderCatalogEntryModel, LLMProviderRegistryModel


def build_provider_catalog(
    registry: LLMProviderRegistryModel,
    provider_settings_by_id: Optional[Dict[str, LLMProviderSettings]] = None,
) -> list[LLMProviderCatalogEntryModel]:
    """Build a full provider catalog for builtin and saved custom providers."""

    provider_settings_by_id = provider_settings_by_id or {}
    catalog_entries: list[LLMProviderCatalogEntryModel] = []

    for provider_meta in registry.providers:
        provider_settings = provider_settings_by_id.get(provider_meta.id)
        resolved_catalog = resolve_provider_model_catalog(
            registry,
            provider_meta.id,
            provider_settings,
        )
        catalog_entries.append(
            LLMProviderCatalogEntryModel(
                id=provider_meta.id,
                provider_type=provider_meta.id,
                source="builtin",
                display_name=provider_meta.display_name,
                description=provider_meta.description,
                icon=provider_meta.icon,
                default_model=(
                    getattr(provider_settings, "custom_default_model", None)
                    or provider_meta.default_model
                ),
                default_classify_model=provider_meta.default_classify_model,
                default_base_url=provider_meta.default_base_url,
                api_format=getattr(provider_settings, "api_format", None),
                fields=dict(provider_meta.fields),
                resolved_chat_models=resolved_catalog.chat_models,
                resolved_embedding_models=resolved_catalog.embedding_models,
                resolved_image_generation_models=resolved_catalog.image_generation_models,
                image_generation_models=list(provider_meta.image_generation_models),
            )
        )

    for provider_id, provider_settings in provider_settings_by_id.items():
        provider_type = str(
            getattr(getattr(provider_settings, "provider_type", ""), "value", getattr(provider_settings, "provider_type", ""))
            or ""
        ).strip().lower()
        if provider_type != "custom":
            continue

        resolved_catalog = resolve_provider_model_catalog(
            registry,
            provider_id,
            provider_settings,
        )
        default_model = (
            getattr(provider_settings, "custom_default_model", None)
            or (provider_settings.custom_models[0] if provider_settings.custom_models else None)
        )
        catalog_entries.append(
            LLMProviderCatalogEntryModel(
                id=provider_id,
                provider_type="custom",
                source="custom",
                display_name=provider_settings.display_name or registry.custom_provider.display_name or provider_id,
                description=registry.custom_provider.description,
                icon=registry.custom_provider.icon,
                default_model=default_model,
                default_classify_model=default_model,
                default_base_url=provider_settings.base_url,
                api_format=provider_settings.api_format,
                fields=dict(registry.custom_provider.fields),
                resolved_chat_models=resolved_catalog.chat_models,
                resolved_embedding_models=resolved_catalog.embedding_models,
                resolved_image_generation_models=resolved_catalog.image_generation_models,
            )
        )

    return catalog_entries


__all__ = ["build_provider_catalog"]
