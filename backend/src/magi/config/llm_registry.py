"""LLM provider registry models and capability resolution helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from .models import LLMCapabilitiesSettings, LLMLimitsSettings, LLMSelectionSettings
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


def resolve_llm_profile(
    llm: LLMSelectionSettings,
    registry: LLMProviderRegistryModel,
) -> ResolvedLLMProfile:
    """Resolve effective capabilities for the active selection."""
    provider_name = str(getattr(llm.provider_id, "value", llm.provider_id) or "").strip()
    model_name = str(llm.model or "").strip()
    model_meta = find_chat_model_meta(registry, provider_name, model_name)

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
        limits = llm.limits.model_copy(deep=True)
        provider_options = dict(llm.provider_options or {})

    if llm.capability_override_enabled:
        capabilities = llm.capabilities.model_copy(deep=True)
        limits = llm.limits.model_copy(deep=True)
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
        "temperature": 0.7,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "timeout": 60,
    }
