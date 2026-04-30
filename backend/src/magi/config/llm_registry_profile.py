"""Runtime LLM profile resolution."""

from __future__ import annotations

from typing import Optional

from .models import LLMCapabilitiesSettings, LLMLimitsSettings, LLMProviderSettings, LLMSelectionSettings
from .llm_registry_model_resolution import find_chat_model_meta, resolve_provider_model_catalog
from .llm_registry_models import LLMProviderRegistryModel, ResolvedLLMProfile


def resolve_llm_profile(
    llm: LLMSelectionSettings,
    registry: LLMProviderRegistryModel,
    provider_settings: Optional[LLMProviderSettings] = None,
) -> ResolvedLLMProfile:
    """Resolve effective capabilities for the active selection."""
    provider_name = str(getattr(llm.provider_id, "value", llm.provider_id) or "").strip()
    model_name = str(llm.model or "").strip()
    resolved_model_meta = None
    if provider_settings is not None:
        resolved_catalog = resolve_provider_model_catalog(registry, provider_name, provider_settings)
        lowered_model = model_name.lower()
        resolved_model_meta = next(
            (model for model in resolved_catalog.chat_models if model.id.lower() == lowered_model),
            None,
        )
    model_meta = resolved_model_meta or find_chat_model_meta(registry, provider_name, model_name)

    if model_meta is not None:
        capabilities = LLMCapabilitiesSettings(
            vision=model_meta.capabilities.vision,
            image_output=model_meta.capabilities.image_output,
            tool_calling=model_meta.capabilities.tool_calling,
            reasoning=model_meta.capabilities.reasoning,
            embedding=False,
        )
        limits = model_meta.limits.model_copy(deep=True)
        provider_options = dict(model_meta.provider_options_example)
    else:
        capabilities = llm.capabilities.model_copy(deep=True)
        limits = LLMLimitsSettings.model_validate(llm.limits.model_dump())
        provider_options = dict(llm.provider_options or {})

    if llm.capability_override_enabled:
        capabilities = llm.capabilities.model_copy(deep=True)
        limits = LLMLimitsSettings.model_validate(llm.limits.model_dump())
        provider_options = dict(llm.provider_options or {})

    return ResolvedLLMProfile(
        provider=provider_name,
        model=model_name,
        capabilities=capabilities,
        limits=limits,
        provider_options=provider_options,
        capability_override_enabled=bool(llm.capability_override_enabled),
    )


__all__ = ["resolve_llm_profile"]
