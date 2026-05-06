"""Factory for provider-native image generation adapters."""

from __future__ import annotations

from typing import Optional

from ...config.llm_registry_model_resolution import (
    find_image_generation_model_meta,
    resolve_provider_model_catalog,
)
from ...config.llm_registry_models import (
    LLMImageGenerationModelMetaModel,
    LLMProviderRegistryModel,
)
from ...config.models import LLMProviderSettings
from .errors import ImageGenInvalidParameterError
from .registry import (
    get_image_generation_adapter_class,
    is_registered_image_generation_protocol,
    registered_image_generation_protocols,
)
from .types import ImageGenerationCapability


def _coerce_provider_type(provider_settings: LLMProviderSettings) -> str:
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


def _image_meta_from_settings(
    *,
    provider_id: str,
    provider_settings: LLMProviderSettings,
    model: str,
    registry: LLMProviderRegistryModel,
) -> Optional[LLMImageGenerationModelMetaModel]:
    registry_provider_id = _coerce_provider_type(provider_settings) or provider_id
    builtin_meta = find_image_generation_model_meta(registry, registry_provider_id, model)
    if builtin_meta is not None:
        return builtin_meta

    resolved_catalog = resolve_provider_model_catalog(registry, provider_id, provider_settings)
    lowered_model = str(model or "").strip().lower()
    resolved_meta = next(
        (
            item
            for item in resolved_catalog.image_generation_models
            if item.id.lower() == lowered_model
        ),
        None,
    )
    if resolved_meta is None:
        return None
    return LLMImageGenerationModelMetaModel(
        id=resolved_meta.id,
        label=resolved_meta.label,
        provider_options_example=dict(resolved_meta.provider_options_example or {}),
        supported_sizes=list(resolved_meta.supported_sizes or []),
        supported_qualities=list(resolved_meta.supported_qualities or []),
        supports_seed=bool(resolved_meta.supports_seed),
        supports_negative_prompt=bool(resolved_meta.supports_negative_prompt),
        supports_reference=bool(resolved_meta.supports_reference),
        max_n=resolved_meta.max_n,
        native_protocol=resolved_meta.native_protocol,
    )


def _capability_from_meta(
    meta: Optional[LLMImageGenerationModelMetaModel],
) -> ImageGenerationCapability | None:
    if meta is None:
        return None
    return ImageGenerationCapability(
        supported_sizes=list(meta.supported_sizes),
        supported_qualities=list(meta.supported_qualities),
        supports_seed=bool(meta.supports_seed),
        supports_negative_prompt=bool(meta.supports_negative_prompt),
        supports_reference=bool(meta.supports_reference),
        max_n=int(meta.max_n or 1),
    )


def image_generation_protocol_of(
    *,
    provider_id: str,
    provider_settings: LLMProviderSettings,
    model: str,
    registry: LLMProviderRegistryModel,
) -> str | None:
    """Resolve the native image generation protocol for a provider/model."""
    meta = _image_meta_from_settings(
        provider_id=provider_id,
        provider_settings=provider_settings,
        model=model,
        registry=registry,
    )
    image_generation = provider_settings.services.image_generation
    if image_generation.native_protocol:
        return str(image_generation.native_protocol).strip().lower()
    if meta is not None and meta.native_protocol and meta.native_protocol != "custom":
        return str(meta.native_protocol).strip().lower()
    return None


def is_image_generation_supported(
    *,
    provider_id: str,
    provider_settings: LLMProviderSettings,
    model: str,
    registry: LLMProviderRegistryModel,
) -> bool:
    """Return whether a provider/model can be routed to an implemented image adapter."""
    if not provider_settings.enabled or not provider_settings.services.image_generation.enabled:
        return False
    meta = _image_meta_from_settings(
        provider_id=provider_id,
        provider_settings=provider_settings,
        model=model,
        registry=registry,
    )
    if meta is None:
        return False
    protocol = image_generation_protocol_of(
        provider_id=provider_id,
        provider_settings=provider_settings,
        model=model,
        registry=registry,
    )
    return bool(protocol and is_registered_image_generation_protocol(protocol))


def create_image_generation_adapter(
    *,
    provider_id: str,
    provider_settings: LLMProviderSettings,
    model: str,
    registry: LLMProviderRegistryModel,
    timeout: int,
    proxy_url: str | None = None,
):
    """Create an image generation adapter from provider settings and registry metadata."""
    image_generation = provider_settings.services.image_generation
    if not provider_settings.enabled or not image_generation.enabled:
        raise ImageGenInvalidParameterError(
            f"Provider '{provider_id}' does not have image generation enabled.",
            field="image_generation.enabled",
            provider_id=provider_id,
        )
    api_key = image_generation.api_key or provider_settings.api_key
    if not api_key:
        raise ImageGenInvalidParameterError(
            f"Provider '{provider_id}' is missing an API key.",
            field="api_key",
            provider_id=provider_id,
        )

    meta = _image_meta_from_settings(
        provider_id=provider_id,
        provider_settings=provider_settings,
        model=model,
        registry=registry,
    )
    if meta is None:
        raise ImageGenInvalidParameterError(
            f"Model '{model}' is not configured as an image generation model for provider '{provider_id}'.",
            field="model",
            provider_id=provider_id,
        )

    protocol = image_generation_protocol_of(
        provider_id=provider_id,
        provider_settings=provider_settings,
        model=model,
        registry=registry,
    )
    adapter_class = get_image_generation_adapter_class(protocol or "")
    if adapter_class is None:
        raise ImageGenInvalidParameterError(
            f"Image generation protocol '{protocol or 'unknown'}' is not supported yet.",
            field="native_protocol",
            allowed_values=registered_image_generation_protocols(),
            provider_id=provider_id,
        )

    base_url = image_generation.base_url or provider_settings.base_url
    effective_timeout = int(image_generation.timeout or timeout)
    return adapter_class(
        provider_id=provider_id,
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout=effective_timeout,
        proxy_url=proxy_url,
        capability=_capability_from_meta(meta),
    )


__all__ = [
    "create_image_generation_adapter",
    "image_generation_protocol_of",
    "is_image_generation_supported",
]
