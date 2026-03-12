"""LLM provider registry models and capability resolution helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from .models import LLMCapabilitiesSettings, LLMLimitsSettings, LLMSelectionSettings


def _default_legacy_capabilities() -> LLMCapabilitiesSettings:
    """Fallback capabilities when older registry entries only list model names."""
    return LLMCapabilitiesSettings(
        vision=False,
        image_output=False,
        tool_calling=True,
        reasoning=True,
        embedding=False,
    )


class LLMProviderFieldModel(BaseModel):
    visible: bool = Field(default=True)
    required: bool = Field(default=False)
    placeholder: Optional[str] = Field(default=None)
    options: Optional[list[str]] = Field(default=None)


class LLMModelMetaModel(BaseModel):
    id: str
    label: Optional[str] = Field(default=None)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=_default_legacy_capabilities)
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
    default_base_url: Optional[str] = Field(default=None)
    model_options: list[str] = Field(default_factory=list)
    models: list[LLMModelMetaModel] = Field(default_factory=list)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_models(self) -> "LLMProviderMetaModel":
        if not self.models and self.model_options:
            self.models = [
                LLMModelMetaModel(id=model_id, label=model_id)
                for model_id in self.model_options
            ]
        if not self.default_model and self.models:
            self.default_model = self.models[0].id
        return self


class LLMCustomProviderMetaModel(BaseModel):
    enabled: bool = Field(default=True)
    display_name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    fields: Dict[str, LLMProviderFieldModel] = Field(default_factory=dict)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=_default_legacy_capabilities)
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


def find_model_meta(
    registry: LLMProviderRegistryModel,
    provider_id: str,
    model_id: str,
) -> Optional[LLMModelMetaModel]:
    provider = find_provider_meta(registry, provider_id)
    if provider is None:
        return None

    lowered_model = str(model_id or "").strip().lower()
    for model in provider.models:
        if model.id.lower() == lowered_model:
            return model
    return None


def resolve_llm_profile(
    llm: LLMSelectionSettings,
    registry: LLMProviderRegistryModel,
) -> ResolvedLLMProfile:
    """Resolve effective capabilities for the active selection."""
    provider_name = str(getattr(llm.provider_id, "value", llm.provider_id) or "").strip()
    model_name = str(llm.model or "").strip()
    model_meta = find_model_meta(registry, provider_name, model_name)

    if model_meta is not None:
        capabilities = model_meta.capabilities.model_copy(deep=True)
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
