"""Model metadata resolution for the LLM provider registry."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import (
    LLMCapabilitiesSettings,
    LLMCapabilityOverridesSettings,
    LLMLimitsOverrideSettings,
    LLMLimitsSettings,
    LLMModelMetadataOverrideSettings,
    LLMProviderSettings,
)
from .llm_registry_models import (
    LLMEmbeddingModelMetaModel,
    LLMImageGenerationModelMetaModel,
    LLMModelMetaModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
    LLMResolvedEmbeddingModelMetaModel,
    LLMResolvedImageGenerationModelMetaModel,
    LLMResolvedModelMetaModel,
    LLMResolvedProviderCatalogModel,
)


def _apply_capability_overrides(
    base: LLMCapabilitiesSettings,
    overrides: Optional[LLMCapabilityOverridesSettings],
) -> LLMCapabilitiesSettings:
    if overrides is None:
        return base.model_copy(deep=True)

    payload = base.model_dump()
    for key, value in overrides.model_dump(exclude_none=True).items():
        payload[key] = value
    return LLMCapabilitiesSettings.model_validate(payload)


def _apply_limit_overrides(
    base: LLMLimitsSettings,
    overrides: Optional[LLMLimitsOverrideSettings],
) -> LLMLimitsSettings:
    if overrides is None:
        return base.model_copy(deep=True)

    payload = base.model_dump()
    for key, value in overrides.model_dump(exclude_none=True).items():
        payload[key] = value
    return LLMLimitsSettings.model_validate(payload)


def _default_chat_modalities(
    capabilities: LLMCapabilitiesSettings,
) -> tuple[list[str], list[str]]:
    input_modalities = ["text"]
    if capabilities.vision:
        input_modalities.append("image")

    output_modalities = ["text"]
    if capabilities.image_output:
        output_modalities.append("image")
    if capabilities.embedding:
        output_modalities.append("embedding")
    return input_modalities, output_modalities


def _default_embedding_modalities(
    capabilities: LLMCapabilitiesSettings,
) -> tuple[list[str], list[str]]:
    input_modalities = ["text"]
    if capabilities.vision:
        input_modalities.append("image")

    output_modalities = ["embedding"]
    if capabilities.image_output:
        output_modalities.append("image")
    return input_modalities, output_modalities


def _default_image_generation_modalities(
    capabilities: LLMCapabilitiesSettings,
) -> tuple[list[str], list[str]]:
    input_modalities = ["text"]
    if capabilities.vision:
        input_modalities.append("image")
    return input_modalities, ["image"]


def _resolve_chat_model(
    *,
    model_id: str,
    source: str,
    label: Optional[str],
    capabilities: LLMCapabilitiesSettings,
    limits: LLMLimitsSettings,
    provider_options_example: Dict[str, Any],
    override: Optional[LLMModelMetadataOverrideSettings],
) -> LLMResolvedModelMetaModel:
    resolved_capabilities = _apply_capability_overrides(
        capabilities,
        override.capabilities if override is not None else None,
    )
    resolved_limits = _apply_limit_overrides(
        limits,
        override.limits if override is not None else None,
    )
    input_modalities, output_modalities = _default_chat_modalities(
        resolved_capabilities
    )
    return LLMResolvedModelMetaModel(
        id=model_id,
        label=(
            override.label
            if override is not None and override.label
            else label or model_id
        ),
        description=override.description if override is not None else None,
        icon=override.icon if override is not None else None,
        source=source,
        hidden=(
            bool(override.hidden)
            if override is not None and override.hidden is not None
            else False
        ),
        preferred=(
            bool(override.preferred)
            if override is not None and override.preferred is not None
            else False
        ),
        capabilities=resolved_capabilities,
        limits=resolved_limits,
        input_modalities=(
            list(override.input_modalities)
            if override is not None and override.input_modalities is not None
            else input_modalities
        ),
        output_modalities=(
            list(override.output_modalities)
            if override is not None and override.output_modalities is not None
            else output_modalities
        ),
        provider_options_example=(
            dict(override.provider_options_example)
            if override is not None and override.provider_options_example is not None
            else dict(provider_options_example)
        ),
    )


def _resolve_embedding_model(
    *,
    model_id: str,
    source: str,
    label: Optional[str],
    dimensions: list[int],
    capabilities: LLMCapabilitiesSettings,
    limits: LLMLimitsSettings,
    provider_options_example: Dict[str, Any],
    override: Optional[LLMModelMetadataOverrideSettings],
) -> LLMResolvedEmbeddingModelMetaModel:
    resolved_capabilities = _apply_capability_overrides(
        capabilities,
        override.capabilities if override is not None else None,
    )
    resolved_limits = _apply_limit_overrides(
        limits,
        override.limits if override is not None else None,
    )
    input_modalities, output_modalities = _default_embedding_modalities(
        resolved_capabilities
    )
    resolved_dimensions = (
        list(override.dimensions)
        if override is not None and override.dimensions is not None
        else list(dimensions)
    )
    return LLMResolvedEmbeddingModelMetaModel(
        id=model_id,
        label=(
            override.label
            if override is not None and override.label
            else label or model_id
        ),
        description=override.description if override is not None else None,
        icon=override.icon if override is not None else None,
        source=source,
        hidden=(
            bool(override.hidden)
            if override is not None and override.hidden is not None
            else False
        ),
        preferred=(
            bool(override.preferred)
            if override is not None and override.preferred is not None
            else False
        ),
        capabilities=resolved_capabilities,
        dimensions=resolved_dimensions,
        limits=resolved_limits,
        input_modalities=(
            list(override.input_modalities)
            if override is not None and override.input_modalities is not None
            else input_modalities
        ),
        output_modalities=(
            list(override.output_modalities)
            if override is not None and override.output_modalities is not None
            else output_modalities
        ),
        provider_options_example=(
            dict(override.provider_options_example)
            if override is not None and override.provider_options_example is not None
            else dict(provider_options_example)
        ),
    )


def _resolve_image_generation_model(
    *,
    model_id: str,
    source: str,
    label: Optional[str],
    capabilities: LLMCapabilitiesSettings,
    limits: LLMLimitsSettings,
    provider_options_example: Dict[str, Any],
    override: Optional[LLMModelMetadataOverrideSettings],
    supported_sizes: Optional[list[str]] = None,
    supported_qualities: Optional[list[str]] = None,
    supports_seed: bool = False,
    supports_negative_prompt: bool = False,
    supports_reference: bool = False,
    max_n: int = 1,
    native_protocol: str = "custom",
) -> LLMResolvedImageGenerationModelMetaModel:
    resolved_capabilities = _apply_capability_overrides(
        capabilities,
        override.capabilities if override is not None else None,
    )
    resolved_capabilities.image_output = True
    resolved_capabilities.embedding = False
    resolved_limits = _apply_limit_overrides(
        limits,
        override.limits if override is not None else None,
    )
    input_modalities, output_modalities = _default_image_generation_modalities(
        resolved_capabilities
    )
    return LLMResolvedImageGenerationModelMetaModel(
        id=model_id,
        label=(
            override.label
            if override is not None and override.label
            else label or model_id
        ),
        description=override.description if override is not None else None,
        icon=override.icon if override is not None else None,
        source=source,
        hidden=(
            bool(override.hidden)
            if override is not None and override.hidden is not None
            else False
        ),
        preferred=(
            bool(override.preferred)
            if override is not None and override.preferred is not None
            else False
        ),
        capabilities=resolved_capabilities,
        limits=resolved_limits,
        input_modalities=(
            list(override.input_modalities)
            if override is not None and override.input_modalities is not None
            else input_modalities
        ),
        output_modalities=(
            list(override.output_modalities)
            if override is not None and override.output_modalities is not None
            else output_modalities
        ),
        provider_options_example=(
            dict(override.provider_options_example)
            if override is not None and override.provider_options_example is not None
            else dict(provider_options_example)
        ),
        supported_sizes=list(supported_sizes or []),
        supported_qualities=list(supported_qualities or []),
        supports_seed=bool(supports_seed),
        supports_negative_prompt=bool(supports_negative_prompt),
        supports_reference=bool(supports_reference),
        max_n=max(1, int(max_n or 1)),
        native_protocol=str(native_protocol or "custom"),
    )


def find_provider_meta(
    registry: LLMProviderRegistryModel,
    provider_id: str,
) -> Optional[LLMProviderMetaModel]:
    lowered = str(provider_id or "").strip().lower()
    for provider in registry.providers:
        if provider.id.lower() == lowered:
            return provider
    return None


def find_chat_model_meta(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    model_id: str,
) -> Optional[LLMModelMetaModel]:
    provider = find_provider_meta(registry, provider_id)
    if provider is None:
        return None

    lowered_model = str(model_id or "").strip().lower()
    for model in provider.chat_models:
        if model.id.lower() == lowered_model:
            return model
    return None


def find_embedding_model_meta(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    model_id: str,
) -> Optional[LLMEmbeddingModelMetaModel]:
    provider = find_provider_meta(registry, provider_id)
    if provider is None:
        return None

    lowered_model = str(model_id or "").strip().lower()
    for model in provider.embedding_models:
        if model.id.lower() == lowered_model:
            return model
    return None


def find_image_generation_model_meta(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    model_id: str,
) -> Optional[LLMImageGenerationModelMetaModel]:
    provider = find_provider_meta(registry, provider_id)
    if provider is None:
        return None

    lowered_model = str(model_id or "").strip().lower()
    for model in provider.image_generation_models:
        if model.id.lower() == lowered_model:
            return model
    return None


def resolve_embedding_dimension(
    model_meta: Optional[LLMEmbeddingModelMetaModel],
    preferred_dimension: Optional[int],
) -> Optional[int]:
    """Resolve embedding dimension against model-supported dimensions."""
    if model_meta is None:
        return preferred_dimension

    if preferred_dimension is not None and preferred_dimension in model_meta.dimensions:
        return preferred_dimension

    if model_meta.dimensions:
        return model_meta.dimensions[0]
    return preferred_dimension


def resolve_provider_model_catalog(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    provider_settings: Optional[LLMProviderSettings] = None,
) -> LLMResolvedProviderCatalogModel:
    """Resolve provider model metadata by merging registry models with user overrides."""

    provider_type = (
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
    provider_meta = find_provider_meta(registry, provider_type or provider_id)
    overrides = dict(getattr(provider_settings, "model_metadata_overrides", {}) or {})
    custom_models = list(getattr(provider_settings, "custom_models", []) or [])
    manual_base_capabilities = (
        registry.custom_provider.capabilities.model_copy(deep=True)
        if provider_type == "custom"
        else LLMCapabilitiesSettings()
    )
    manual_base_limits = (
        registry.custom_provider.limits.model_copy(deep=True)
        if provider_type == "custom"
        else LLMLimitsSettings()
    )
    manual_provider_options = (
        dict(registry.custom_provider.provider_options_example)
        if provider_type == "custom"
        else {}
    )

    chat_models: dict[str, LLMResolvedModelMetaModel] = {}
    embedding_models: dict[str, LLMResolvedEmbeddingModelMetaModel] = {}
    image_generation_models: dict[str, LLMResolvedImageGenerationModelMetaModel] = {}

    if provider_meta is not None:
        for model in provider_meta.chat_models:
            base_capabilities = LLMCapabilitiesSettings(
                vision=model.capabilities.vision,
                image_output=model.capabilities.image_output,
                tool_calling=model.capabilities.tool_calling,
                reasoning=model.capabilities.reasoning,
                embedding=False,
            )
            chat_models[model.id] = _resolve_chat_model(
                model_id=model.id,
                source="builtin",
                label=model.label,
                capabilities=base_capabilities,
                limits=model.limits,
                provider_options_example=model.provider_options_example,
                override=overrides.get(model.id),
            )

        for model in provider_meta.embedding_models:
            base_capabilities = LLMCapabilitiesSettings(
                vision=False,
                image_output=False,
                tool_calling=False,
                reasoning=False,
                embedding=True,
            )
            embedding_models[model.id] = _resolve_embedding_model(
                model_id=model.id,
                source="builtin",
                label=model.label,
                dimensions=model.dimensions,
                capabilities=base_capabilities,
                limits=model.limits,
                provider_options_example=model.provider_options_example,
                override=overrides.get(model.id),
            )

        for model in provider_meta.image_generation_models:
            base_capabilities = LLMCapabilitiesSettings(
                vision=False,
                image_output=True,
                tool_calling=False,
                reasoning=False,
                embedding=False,
            )
            image_generation_models[model.id] = _resolve_image_generation_model(
                model_id=model.id,
                source="builtin",
                label=model.label,
                capabilities=base_capabilities,
                limits=LLMLimitsSettings(),
                provider_options_example=model.provider_options_example,
                override=overrides.get(model.id),
                supported_sizes=model.supported_sizes,
                supported_qualities=model.supported_qualities,
                supports_seed=model.supports_seed,
                supports_negative_prompt=model.supports_negative_prompt,
                supports_reference=model.supports_reference,
                max_n=model.max_n,
                native_protocol=model.native_protocol,
            )

    for model_id in custom_models:
        if model_id not in chat_models:
            chat_models[model_id] = _resolve_chat_model(
                model_id=model_id,
                source="manual",
                label=model_id,
                capabilities=manual_base_capabilities,
                limits=manual_base_limits,
                provider_options_example=manual_provider_options,
                override=overrides.get(model_id),
            )

    for model_id, override in overrides.items():
        if (
            model_id not in chat_models
            and override.capabilities.embedding is not True
            and override.capabilities.image_output is not True
        ):
            chat_models[model_id] = _resolve_chat_model(
                model_id=model_id,
                source="manual",
                label=model_id,
                capabilities=manual_base_capabilities,
                limits=manual_base_limits,
                provider_options_example=manual_provider_options,
                override=override,
            )

        if override.capabilities.embedding is True and model_id not in embedding_models:
            base_chat_model = chat_models.get(model_id)
            embedding_capabilities = (
                base_chat_model.capabilities.model_copy(deep=True)
                if base_chat_model is not None
                else LLMCapabilitiesSettings(
                    vision=False,
                    image_output=False,
                    tool_calling=False,
                    reasoning=False,
                    embedding=True,
                )
            )
            embedding_capabilities.embedding = True
            embedding_models[model_id] = _resolve_embedding_model(
                model_id=model_id,
                source=(
                    base_chat_model.source if base_chat_model is not None else "manual"
                ),
                label=(
                    base_chat_model.label if base_chat_model is not None else model_id
                ),
                dimensions=[],
                capabilities=embedding_capabilities,
                limits=(
                    base_chat_model.limits
                    if base_chat_model is not None
                    else LLMLimitsSettings()
                ),
                provider_options_example=(
                    base_chat_model.provider_options_example
                    if base_chat_model is not None
                    else manual_provider_options
                ),
                override=override,
            )

    return LLMResolvedProviderCatalogModel(
        chat_models=list(chat_models.values()),
        embedding_models=list(embedding_models.values()),
        image_generation_models=list(image_generation_models.values()),
    )


__all__ = [
    "_apply_capability_overrides",
    "_apply_limit_overrides",
    "_default_chat_modalities",
    "_default_embedding_modalities",
    "_default_image_generation_modalities",
    "_resolve_chat_model",
    "_resolve_embedding_model",
    "_resolve_image_generation_model",
    "find_provider_meta",
    "find_chat_model_meta",
    "find_embedding_model_meta",
    "find_image_generation_model_meta",
    "resolve_embedding_dimension",
    "resolve_provider_model_catalog",
]
