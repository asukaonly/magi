"""Runtime LLM defaults derived from provider registry metadata."""

from __future__ import annotations

from typing import Any, Dict

from .constants import DEFAULT_MAX_TOKENS
from .models import LLMCapabilitiesSettings, LLMLimitsSettings
from .llm_registry_models import (
    LLMAudioGenerationModelMetaModel,
    LLMChatCapabilitiesModel,
    LLMCustomProviderMetaModel,
    LLMEmbeddingModelMetaModel,
    LLMImageGenerationModelMetaModel,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
)


def build_default_llm_provider_registry() -> LLMProviderRegistryModel:
    """Build the minimal provider registry used when packaged YAML is unavailable."""
    return LLMProviderRegistryModel(
        providers=[_default_openai_provider_meta()],
        custom_provider=_default_custom_provider_meta(),
    )


def _default_openai_provider_meta() -> LLMProviderMetaModel:
    return LLMProviderMetaModel(
        id="openai",
        display_name="OpenAI",
        description="General purpose, strongest ecosystem",
        icon="openai",
        default_model="gpt-5.6",
        default_classify_model="gpt-5.6-luna",
        default_base_url="https://api.openai.com/v1",
        chat_models=_default_openai_chat_models(),
        embedding_models=_default_openai_embedding_models(),
        image_generation_models=_default_openai_image_generation_models(),
        audio_generation_models=_default_openai_audio_generation_models(),
        fields=_default_openai_fields(),
    )


def _default_openai_chat_models() -> list[LLMModelMetaModel]:
    return [
        LLMModelMetaModel(
            id="gpt-5.6",
            label="GPT-5.6 Sol",
            capabilities=LLMChatCapabilitiesModel(
                vision=True,
                image_output=False,
                tool_calling=True,
                reasoning=True,
            ),
            limits=LLMLimitsSettings(
                context_window=1050000,
                max_output_tokens=128000,
            ),
        )
    ]


def _default_openai_embedding_models() -> list[LLMEmbeddingModelMetaModel]:
    return [
        LLMEmbeddingModelMetaModel(
            id="text-embedding-3-small",
            label="Text Embedding 3 Small",
            dimensions=[1536, 512],
        )
    ]


def _default_openai_image_generation_models() -> list[LLMImageGenerationModelMetaModel]:
    return [
        LLMImageGenerationModelMetaModel(
            id="gpt-image-2",
            label="GPT Image 2",
            supported_sizes=["1024x1024", "1536x1024", "1024x1536"],
            supported_qualities=["auto", "high", "medium", "low"],
            native_protocol="openai_images",
        )
    ]


def _default_openai_audio_generation_models() -> list[LLMAudioGenerationModelMetaModel]:
    return [
        LLMAudioGenerationModelMetaModel(id="tts-1", label="TTS 1"),
        LLMAudioGenerationModelMetaModel(id="tts-1-hd", label="TTS 1 HD"),
    ]


def _default_openai_fields() -> dict[str, LLMProviderFieldModel]:
    return {
        "model": LLMProviderFieldModel(visible=True, required=True),
        "api_key": LLMProviderFieldModel(visible=True, required=True),
        "base_url": LLMProviderFieldModel(visible=True, required=False),
    }


def _default_custom_provider_meta() -> LLMCustomProviderMetaModel:
    return LLMCustomProviderMetaModel(
        enabled=True,
        display_name="Custom Provider",
        description="Connect OpenAI-compatible or Anthropic-compatible endpoints",
        icon="custom",
        capabilities=LLMCapabilitiesSettings(
            vision=False,
            image_output=False,
            tool_calling=True,
            reasoning=True,
            embedding=False,
        ),
        fields=_default_custom_provider_fields(),
    )


def _default_custom_provider_fields() -> dict[str, LLMProviderFieldModel]:
    return {
        "custom_name": LLMProviderFieldModel(
            visible=True,
            required=True,
            placeholder="My Provider",
        ),
        "api_format": LLMProviderFieldModel(
            visible=True,
            required=True,
            options=["openai", "anthropic"],
        ),
        "model": LLMProviderFieldModel(visible=True, required=True),
        "api_key": LLMProviderFieldModel(visible=True, required=True),
        "base_url": LLMProviderFieldModel(visible=True, required=False),
    }


def build_runtime_llm_defaults(registry: LLMProviderRegistryModel) -> Dict[str, Any]:
    """Build runtime LLM defaults from provider registry metadata."""
    providers: Dict[str, Any] = {}

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

    image_generation_selection = {
        **empty_selection,
        "capabilities": {
            "vision": False,
            "image_output": True,
            "tool_calling": False,
            "reasoning": False,
            "embedding": False,
        },
    }

    return {
        "providers": providers,
        "selections": {
            "context_decider": dict(empty_selection),
            "core": dict(empty_selection),
            "memory_summarizer": dict(empty_selection),
            "embedding": embedding_selection,
            "image_generation": image_generation_selection,
        },
        "model_runtime_overrides": {},
        "temperature": 0.7,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "timeout": 60,
    }


__all__ = ["build_default_llm_provider_registry", "build_runtime_llm_defaults"]
