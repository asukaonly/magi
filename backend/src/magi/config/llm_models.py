"""LLM-related application configuration models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from .constants import DEFAULT_MAX_TOKENS, MIN_MAX_TOKENS


class LLMProvider(str, Enum):
    """LLM provider type."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GLM = "glm"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    KIMI = "kimi"
    MINIMAX = "minimax"
    LOCAL = "local"
    CUSTOM = "custom"


class LLMCapabilitiesSettings(BaseModel):
    """Declared capability flags for the active LLM."""

    vision: bool = Field(default=False)
    image_output: bool = Field(default=False)
    tool_calling: bool = Field(default=True)
    reasoning: bool = Field(default=True)
    embedding: bool = Field(default=False)


class LLMLimitsSettings(BaseModel):
    """Capability-adjacent numeric limits for the active LLM."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class LLMCapabilityOverridesSettings(BaseModel):
    """Per-model capability overrides applied on top of registry metadata."""

    vision: Optional[bool] = Field(default=None)
    image_output: Optional[bool] = Field(default=None)
    tool_calling: Optional[bool] = Field(default=None)
    reasoning: Optional[bool] = Field(default=None)
    embedding: Optional[bool] = Field(default=None)


class LLMLimitsOverrideSettings(BaseModel):
    """Per-model numeric limit overrides applied on top of registry metadata."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class LLMModelMetadataOverrideSettings(BaseModel):
    """User-defined metadata override for any provider model."""

    label: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    capabilities: LLMCapabilityOverridesSettings = Field(
        default_factory=LLMCapabilityOverridesSettings
    )
    limits: LLMLimitsOverrideSettings = Field(default_factory=LLMLimitsOverrideSettings)
    input_modalities: Optional[List[str]] = Field(default=None)
    output_modalities: Optional[List[str]] = Field(default=None)
    provider_options_example: Optional[Dict[str, Any]] = Field(default=None)
    hidden: Optional[bool] = Field(default=None)
    preferred: Optional[bool] = Field(default=None)
    source_note: Optional[str] = Field(default=None)
    dimensions: Optional[List[int]] = Field(default=None)


class LLMSelectionLimitsSettings(BaseModel):
    """Per-scenario numeric limits that remain local to scenario selection."""

    context_window: Optional[int] = Field(default=None, ge=1)
    max_output_tokens: Optional[int] = Field(default=None, ge=1)


class LLMConcurrencyOverrideSettings(BaseModel):
    """Shared concurrency override for a concrete provider-model family."""

    max_concurrency: Optional[int] = Field(default=None, ge=1)


class ThinkingDepth(str, Enum):
    """Reasoning effort level requested by a caller for a single LLM call.

    This is orthogonal to LLMScenario: the scenario selects which model to
    use, while ThinkingDepth controls how hard the model should reason on
    this particular invocation.  Provider adapters map these levels to
    vendor-specific APIs (e.g. OpenAI reasoning_effort, Anthropic thinking
    budget, GLM thinking toggle).
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class LLMScenario(str, Enum):
    """Supported runtime LLM scenarios."""

    CONTEXT_COMPACT = "context_compact"
    CONTEXT_DECIDER = "context_decider"
    CORE = "core"
    MEMORY_SUMMARIZER = "memory_summarizer"
    EMBEDDING = "embedding"
    IMAGE_GENERATION = "image_generation"


class LLMProviderSettings(BaseModel):
    """Reusable provider connection settings."""

    enabled: bool = Field(default=True)
    provider_type: LLMProvider = Field(default=LLMProvider.OPENAI)
    display_name: str = Field(default="OpenAI")
    provider_plan: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default=None)
    custom_models: List[str] = Field(default_factory=list)
    custom_default_model: Optional[str] = Field(default=None)
    model_metadata_overrides: Dict[str, LLMModelMetadataOverrideSettings] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_custom_model_defaults(self) -> "LLMProviderSettings":
        if self.provider_type == LLMProvider.CUSTOM:
            if self.custom_default_model and self.custom_default_model not in self.custom_models:
                raise ValueError("Custom default model must exist in custom_models")
        return self


class LLMSelectionSettings(BaseModel):
    """Per-scenario model selection."""

    provider_id: str = Field(default="openai")
    model: str = Field(default="gpt-4o-mini")
    embedding_dimension: Optional[int] = Field(default=None, ge=1)
    capability_override_enabled: bool = Field(default=False)
    capabilities: LLMCapabilitiesSettings = Field(default_factory=LLMCapabilitiesSettings)
    limits: LLMSelectionLimitsSettings = Field(default_factory=LLMSelectionLimitsSettings)
    provider_options: Dict[str, Any] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    """Scenario-based LLM configuration."""

    providers: Dict[str, LLMProviderSettings] = Field(
        default_factory=lambda: {
            "openai": LLMProviderSettings(
                provider_type=LLMProvider.OPENAI,
                display_name="OpenAI",
            )
        }
    )
    selections: Dict[str, LLMSelectionSettings] = Field(
        default_factory=lambda: {
            LLMScenario.CONTEXT_DECIDER.value: LLMSelectionSettings(),
            LLMScenario.CORE.value: LLMSelectionSettings(),
            LLMScenario.EMBEDDING.value: LLMSelectionSettings(
                capabilities=LLMCapabilitiesSettings(embedding=True),
            ),
        }
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=DEFAULT_MAX_TOKENS, ge=MIN_MAX_TOKENS)
    timeout: int = Field(default=60, ge=1)
    model_runtime_overrides: Dict[str, LLMConcurrencyOverrideSettings] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_required_selections(self) -> "LLMSettings":
        required_scenarios = {
            LLMScenario.CONTEXT_DECIDER.value,
            LLMScenario.CORE.value,
        }
        missing_scenarios = required_scenarios.difference(self.selections.keys())
        if missing_scenarios:
            missing_names = ", ".join(sorted(missing_scenarios))
            raise ValueError(f"Missing required LLM selections: {missing_names}")

        return self


__all__ = [
    "LLMCapabilitiesSettings",
    "LLMCapabilityOverridesSettings",
    "LLMConcurrencyOverrideSettings",
    "LLMLimitsOverrideSettings",
    "LLMLimitsSettings",
    "LLMModelMetadataOverrideSettings",
    "LLMProvider",
    "LLMProviderSettings",
    "LLMScenario",
    "LLMSelectionLimitsSettings",
    "LLMSelectionSettings",
    "LLMSettings",
    "ThinkingDepth",
]
