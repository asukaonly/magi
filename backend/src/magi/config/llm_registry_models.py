"""Pydantic models for the LLM provider registry."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .models import (
    LLMCapabilitiesSettings,
    LLMLimitsSettings,
    LLMModelCostModel,
    LLMScenario,
    ModelVendor,
)


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
    vendor: Optional[ModelVendor] = Field(
        default=None,
        description=(
            "Behavioral vendor (decides reasoning payload, tool-calling "
            "format, etc.). Defaults via provider-level inference if not set."
        ),
    )
    capabilities: "LLMChatCapabilitiesModel" = Field(default_factory=_default_chat_capabilities)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    cost: Optional[LLMModelCostModel] = Field(default=None)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMProviderPlanEndpointModel(BaseModel):
    """Selectable endpoint for a provider plan."""

    id: str
    label: str
    country: Optional[str] = Field(default=None)
    base_url: str
    api_format: Optional[str] = Field(default=None)


class LLMProviderPlanModel(BaseModel):
    """Optional commercial/runtime plan layered onto a provider."""

    id: str
    display_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    default_model: Optional[str] = Field(default=None)
    default_classify_model: Optional[str] = Field(default=None)
    default_base_url: Optional[str] = Field(default=None)
    allowed_scenarios: Optional[list[LLMScenario]] = Field(default=None)
    endpoints: list[LLMProviderPlanEndpointModel] = Field(default_factory=list)
    chat_models: Optional[list[LLMModelMetaModel]] = Field(default=None)
    embedding_models: Optional[list["LLMEmbeddingModelMetaModel"]] = Field(default=None)
    image_generation_models: Optional[list["LLMImageGenerationModelMetaModel"]] = Field(
        default=None
    )
    audio_generation_models: Optional[list["LLMAudioGenerationModelMetaModel"]] = Field(
        default=None
    )
    fields: Optional[Dict[str, LLMProviderFieldModel]] = Field(default=None)


class LLMResolvedModelMetaModel(BaseModel):
    """Resolved metadata for a chat-capable model."""

    id: str
    label: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    source: str = Field(default="builtin")
    hidden: bool = Field(default=False)
    preferred: bool = Field(default=False)
    vendor: ModelVendor = Field(default=ModelVendor.GENERIC)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMLimitsSettings = Field(default_factory=LLMLimitsSettings)
    cost: Optional[LLMModelCostModel] = Field(default=None)
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
    cost: Optional[LLMModelCostModel] = Field(default=None)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMResolvedEmbeddingModelMetaModel":
        if not self.label:
            self.label = self.id
        return self


class LLMResolvedImageGenerationModelMetaModel(LLMResolvedModelMetaModel):
    """Resolved metadata for an image-generation-capable model."""

    supported_sizes: list[str] = Field(default_factory=list)
    supported_qualities: list[str] = Field(default_factory=list)
    supports_seed: bool = Field(default=False)
    supports_negative_prompt: bool = Field(default=False)
    supports_reference: bool = Field(default=False)
    max_n: int = Field(default=1, ge=1)
    native_protocol: str = Field(default="custom")


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
    plans: list[LLMProviderPlanModel] = Field(default_factory=list)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    resolved_chat_models: list[LLMResolvedModelMetaModel] = Field(default_factory=list)
    resolved_embedding_models: list[LLMResolvedEmbeddingModelMetaModel] = Field(
        default_factory=list
    )
    resolved_image_generation_models: list[LLMResolvedImageGenerationModelMetaModel] = Field(
        default_factory=list
    )

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
    image_generation_models: list[LLMResolvedImageGenerationModelMetaModel] = Field(
        default_factory=list
    )


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
    provider_plan: Optional[str] = Field(default=None)
    plans: list[LLMProviderPlanModel] = Field(default_factory=list)
    api_format: Optional[str] = Field(default=None)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    resolved_chat_models: list[LLMResolvedModelMetaModel] = Field(default_factory=list)
    resolved_embedding_models: list[LLMResolvedEmbeddingModelMetaModel] = Field(
        default_factory=list
    )
    resolved_image_generation_models: list[LLMResolvedImageGenerationModelMetaModel] = Field(
        default_factory=list
    )
    image_generation_models: list[LLMImageGenerationModelMetaModel] = Field(default_factory=list)


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
    cost: Optional[LLMModelCostModel] = Field(default=None)
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
    supported_sizes: list[str] = Field(default_factory=list)
    supported_qualities: list[str] = Field(default_factory=list)
    supports_seed: bool = Field(default=False)
    supports_negative_prompt: bool = Field(default=False)
    supports_reference: bool = Field(default=False)
    max_n: int = Field(default=1, ge=1)
    native_protocol: Literal[
        "dashscope_multimodal_image",
        "openai_images",
        "gemini_predict",
        "minimax_image",
        "zai_images",
        "doubao_seedream",
        "replicate",
        "custom",
    ] = Field(default="custom")
    cost: Optional[LLMModelCostModel] = Field(default=None)
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
    cost: Optional[LLMModelCostModel] = Field(default=None)
    provider_options_example: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_label(self) -> "LLMAudioGenerationModelMetaModel":
        if not self.label:
            self.label = self.id
        return self
