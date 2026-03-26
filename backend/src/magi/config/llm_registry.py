"""LLM provider registry models and capability resolution helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from .models import (
    LLMCapabilitiesSettings,
    LLMCapabilityOverridesSettings,
    LLMLimitsOverrideSettings,
    LLMLimitsSettings,
    LLMModelMetadataOverrideSettings,
    LLMProviderSettings,
    LLMSelectionSettings,
)
from .constants import DEFAULT_MAX_TOKENS


def _default_chat_capabilities() -> "LLMChatCapabilitiesModel":
    return LLMChatCapabilitiesModel(
        vision=False,
        image_output=False,
        tool_calling=True,
        reasoning=True,
    )


class LLMProviderFieldModel(BaseModel):
    visible: bool = Field(default=True)
    required: bool = Field(default=False)
    placeholder: Optional[str] = Field(default=None)
    options: Optional[list[str]] = Field(default=None)


class LLMModelMetaModel(BaseModel):
    """Metadata for chat/inference models."""

    id: str
    label: Optional[str] = Field(default=None)
    capabilities: "LLMChatCapabilitiesModel" = Field(default_factory=_default_chat_capabilities)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMResolvedModelMetaModel(BaseModel):
    """Resolved metadata for a chat-capable model."""

    id: str
    label: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    source: str = Field(default="builtin")
    hidden: bool = Field(default=False)
    preferred: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMResolvedModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMResolvedEmbeddingModelMetaModel(BaseModel):
    """Resolved metadata for an embedding-capable model."""

    id: str
    label: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    source: str = Field(default="builtin")
    hidden: bool = Field(default=False)
    preferred: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(
        default_factory=lambda: LLMCapabilitiesSettings(
            vision=False,
            image_output=False,
            tool_calling=False,
            reasoning=False,
            embedding=True,
        )
    )
    dimensions: list[int] = Field(default_factory=list)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMResolvedEmbeddingModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMProviderMetaModel(BaseModel):
    id: str
    display_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    default_model: Optional[str] = Field(default=None)
    default_classify_model: Optional[str] = Field(default=None)
    default_base_url: Optional[str] = Field(default=None)
    chat_models: list[LLMModelMetaModel] = Field(default_factory=list)
    embedding_models: list["LLMEmbeddingModelMetaModel"] = Field(default_factory=list)
    image_generation_models: list["LLMImageGenerationModelMetaModel"] = Field(default_factory=list)
    audio_generation_models: list["LLMAudioGenerationModelMetaModel"] = Field(default_factory=list)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    resolved_chat_models: list[LLMResolvedModelMetaModel] = Field(default_factory=list)
    resolved_embedding_models: list[LLMResolvedEmbeddingModelMetaModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_models(self) -> "LLMProviderMetaModel":
        if not self.default_model and self.chat_models:
            self.default_model = self.chat_models[0].id
        if not self.default_classify_model:
            self.default_classify_model = self.default_model
        return self


class LLMCustomProviderMetaModel(BaseModel):
    enabled: bool = Field(default=True)
    display_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    capabilities: LLMCapabilitiesSettings = Field(
        default_factory=lambda: LLMCapabilitiesSettings(
            vision=False,
            image_output=False,
            tool_calling=True,
            reasoning=True,
            embedding=False,
        )
    )
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)


class LLMProviderRegistryModel(BaseModel):
    providers: list[LLMProviderMetaModel] = Field(default_factory=list)
    custom_provider: LLMCustomProviderMetaModel = Field(default_factory=LLMCustomProviderMetaModel)


class LLMResolvedProviderCatalogModel(BaseModel):
    """Resolved model catalog for a single provider."""

    chat_models: list[LLMResolvedModelMetaModel] = Field(default_factory=list)
    embedding_models: list[LLMResolvedEmbeddingModelMetaModel] = Field(default_factory=list)


class LLMProviderCatalogEntryModel(BaseModel):
    """Resolved catalog entry for a provider instance."""

    id: str
    provider_type: str
    source: str = Field(default="builtin")
    display_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    default_model: Optional[str] = Field(default=None)
    default_classify_model: Optional[str] = Field(default=None)
    default_base_url: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    resolved_chat_models: list[LLMResolvedModelMetaModel] = Field(default_factory=list)
    resolved_embedding_models: list[LLMResolvedEmbeddingModelMetaModel] = Field(default_factory=list)


class ResolvedLLMProfile(BaseModel):
    """Effective model profile after registry defaults and user overrides are applied."""

    provider: str
    model: str
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)
    capability_override_enabled: bool = Field(default=False)


class LLMChatCapabilitiesModel(BaseModel):
    """Chat model capabilities in provider registry."""

    vision: bool = Field(default=False)
    image_output: bool = Field(default=False)
    tool_calling: bool = Field(default=True)
    reasoning: bool = Field(default=True)


class LLMEmbeddingModelMetaModel(BaseModel):
    """Metadata for embedding/vector models."""

    id: str
    label: Optional[str] = Field(default=None)
    dimensions: list[int] = Field(default_factory=list)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_embedding_meta(self) -> "LLMEmbeddingModelMetaModel":
        if not self.label:
            self.label = self.id
        if not self.dimensions:
            self.dimensions = [1536]
        return self


class LLMImageGenerationModelMetaModel(BaseModel):
    """Metadata for image generation models."""

    id: str
    label: Optional[str] = Field(default=None)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMImageGenerationModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMAudioGenerationModelMetaModel(BaseModel):
    """Metadata for audio generation models."""

    id: str
    label: Optional[str] = Field(default=None)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMAudioGenerationModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


def load_llm_provider_registry(path: Path, *, fallback: LLMProviderRegistryModel) -> LLMProviderRegistryModel:
    """Load provider registry from YAML, falling back to a default registry on failure."""
    if not path.exists():
        return fallback

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return LLMProviderRegistryModel(**data)
    except Exception:
        return fallback


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


def _default_chat_modalities(capabilities: LLMCapabilitiesSettings) -> tuple[list[str], list[str]]:
    input_modalities = ["text"]
    if capabilities.vision:
        input_modalities.append("image")

    output_modalities = ["text"]
    if capabilities.image_output:
        output_modalities.append("image")
    if capabilities.embedding:
        output_modalities.append("embedding")
    return input_modalities, output_modalities


def _default_embedding_modalities(capabilities: LLMCapabilitiesSettings) -> tuple[list[str], list[str]]:
    input_modalities = ["text"]
    if capabilities.vision:
        input_modalities.append("image")

    output_modalities = ["embedding"]
    if capabilities.image_output:
        output_modalities.append("image")
    return input_modalities, output_modalities


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
    input_modalities, output_modalities = _default_chat_modalities(resolved_capabilities)
    return LLMResolvedModelMetaModel(
        id=model_id,
        label=override.label if override is not None and override.label else label or model_id,
        description=override.description if override is not None else None,
        icon=override.icon if override is not None else None,
        source=source,
        hidden=bool(override.hidden) if override is not None and override.hidden is not None else False,
        preferred=bool(override.preferred) if override is not None and override.preferred is not None else False,
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
    input_modalities, output_modalities = _default_embedding_modalities(resolved_capabilities)
    return LLMResolvedEmbeddingModelMetaModel(
        id=model_id,
        label=override.label if override is not None and override.label else label or model_id,
        description=override.description if override is not None else None,
        icon=override.icon if override is not None else None,
        source=source,
        hidden=bool(override.hidden) if override is not None and override.hidden is not None else False,
        preferred=bool(override.preferred) if override is not None and override.preferred is not None else False,
        capabilities=resolved_capabilities,
        dimensions=list(dimensions),
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

    provider_meta = find_provider_meta(registry, provider_id)
    provider_type = str(
        getattr(getattr(provider_settings, "provider_type", ""), "value", getattr(provider_settings, "provider_type", ""))
        or ""
    ).strip().lower()
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
        if model_id not in chat_models and override.capabilities.embedding is not True:
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
                source=base_chat_model.source if base_chat_model is not None else "manual",
                label=base_chat_model.label if base_chat_model is not None else model_id,
                dimensions=[],
                capabilities=embedding_capabilities,
                limits=base_chat_model.limits if base_chat_model is not None else LLMLimitsSettings(),
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
            )
        )

    return catalog_entries


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


def build_runtime_llm_defaults(registry: LLMProviderRegistryModel) -> Dict[str, Any]:
    """Build runtime LLM defaults from provider registry metadata."""
    providers: Dict[str, Any] = {}
    for provider in registry.providers:
        provider_id = provider.id
        providers[provider_id] = {
            "enabled": False,
            "provider_type": provider_id,
            "display_name": provider.display_name or provider_id.title(),
            "api_key": "",
            "base_url": provider.default_base_url or "",
            "api_format": None,
            "custom_models": [],
            "custom_default_model": "",
            "model_metadata_overrides": {},
        }

    if not providers:
        providers["openai"] = {
            "enabled": False,
            "provider_type": "openai",
            "display_name": "OpenAI",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "api_format": None,
            "custom_models": [],
            "custom_default_model": "",
            "model_metadata_overrides": {},
        }

    empty_selection = {
        "provider_id": "",
        "model": "",
        "capability_override_enabled": False,
        "capabilities": {
            "vision": False,
            "image_output": False,
            "tool_calling": True,
            "reasoning": True,
            "embedding": False,
        },
        "limits": {
            "context_window": None,
            "max_output_tokens": None,
        },
        "provider_options": {},
        "embedding_dimension": None,
    }

    embedding_selection = {
        **empty_selection,
        "capabilities": {
            "vision": False,
            "image_output": False,
            "tool_calling": False,
            "reasoning": False,
            "embedding": True,
        },
    }

    return {
        "providers": providers,
        "selections": {
            "context_decider": dict(empty_selection),
            "core": dict(empty_selection),
            "embedding": embedding_selection,
        },
        "model_runtime_overrides": {},
        "temperature": 0.7,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "timeout": 60,
    }
