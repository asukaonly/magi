"""Shared LLM provider testing, discovery, and registry loading."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field

from ...config.llm_registry import (
    LLMAudioGenerationModelMetaModel,
    LLMChatCapabilitiesModel,
    LLMCustomProviderMetaModel,
    LLMEmbeddingModelMetaModel,
    LLMImageGenerationModelMetaModel,
    LLMLimitsSettings,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
    find_provider_meta,
    load_llm_provider_registry,
)
from ...config.models import (
    LLMCapabilitiesSettings,
    LLMProviderSettings,
)
from ...config import get_config
from ...core.logger import get_logger
from ...llm import LLMProviderBridge, create_llm_adapter
from ...llm.draft import build_adapter_from_provider

logger = get_logger(__name__)


# ── Shared request/response models ──────────────────────────────────────


class DiscoverLLMModelsRequestModel(BaseModel):
    provider_type: str = Field(default="custom")
    base_url: str
    api_key: Optional[str] = Field(default=None)
    api_format: Optional[str] = Field(default="openai")


class DiscoverLLMModelsResponseModel(BaseModel):
    models: List[str] = Field(default_factory=list)
    default_model: Optional[str] = Field(default=None)


class DiscoverLLMModelsApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[DiscoverLLMModelsResponseModel] = None


class TestLLMProviderRequestModel(BaseModel):
    provider_id: str = Field(default="openai")
    provider: Any  # LLMProviderConfigModel (defined in config router)
    model: str = Field(default="")


class TestLLMProviderResponseModel(BaseModel):
    model: str
    latency_ms: int
    preview: str = Field(default="")


class TestLLMProviderApiResponseModel(BaseModel):
    success: bool
    message: str
    data: Optional[TestLLMProviderResponseModel] = None


# ── Registry loading ────────────────────────────────────────────────────


def _llm_provider_registry_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs" / "llm_providers.yaml"


def _default_llm_provider_registry() -> LLMProviderRegistryModel:
    try:
        with open(_llm_provider_registry_path(), "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return LLMProviderRegistryModel(**data)
    except Exception:
        return LLMProviderRegistryModel(
            providers=[
                LLMProviderMetaModel(
                    id="openai",
                    display_name="OpenAI",
                    description="General purpose, strongest ecosystem",
                    icon="openai",
                    default_model="gpt-5.2",
                    default_classify_model="gpt-5.2",
                    default_base_url="https://api.openai.com/v1",
                    chat_models=[
                        LLMModelMetaModel(
                            id="gpt-5.2",
                            label="GPT-5.2",
                            capabilities=LLMChatCapabilitiesModel(
                                vision=True,
                                image_output=False,
                                tool_calling=True,
                                reasoning=True,
                            ),
                            limits=LLMLimitsSettings(
                                context_window=400000,
                                max_output_tokens=128000,
                                max_concurrency=2,
                            ),
                        )
                    ],
                    embedding_models=[
                        LLMEmbeddingModelMetaModel(
                            id="text-embedding-3-small",
                            label="Text Embedding 3 Small",
                            dimensions=[1536, 512],
                            limits=LLMLimitsSettings(max_concurrency=6),
                        )
                    ],
                    image_generation_models=[LLMImageGenerationModelMetaModel(id="gpt-image-1", label="GPT Image 1")],
                    audio_generation_models=[LLMAudioGenerationModelMetaModel(id="gpt-4o-mini-tts", label="GPT-4o Mini TTS")],
                    fields={
                        "model": LLMProviderFieldModel(visible=True, required=True),
                        "api_key": LLMProviderFieldModel(visible=True, required=True),
                        "base_url": LLMProviderFieldModel(visible=True, required=False),
                    },
                )
            ],
            custom_provider=LLMCustomProviderMetaModel(
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
                fields={
                    "custom_name": LLMProviderFieldModel(visible=True, required=True, placeholder="My Provider"),
                    "api_format": LLMProviderFieldModel(visible=True, required=True, options=["openai", "anthropic"]),
                    "model": LLMProviderFieldModel(visible=True, required=True),
                    "api_key": LLMProviderFieldModel(visible=True, required=True),
                    "base_url": LLMProviderFieldModel(visible=True, required=False),
                },
            ),
        )


def get_llm_provider_registry() -> LLMProviderRegistryModel:
    """Load the LLM provider registry from disk with built-in fallback."""
    return load_llm_provider_registry(
        _llm_provider_registry_path(),
        fallback=_default_llm_provider_registry(),
    )


# ── Model discovery ─────────────────────────────────────────────────────


async def discover_openai_compatible_models(
    base_url: str,
    api_key: Optional[str],
    api_format: Optional[str],
) -> List[str]:
    """Discover models from an OpenAI-compatible /models endpoint."""
    if api_format not in (None, "", "openai"):
        raise HTTPException(status_code=400, detail="Unsupported model discovery format")

    endpoint = base_url.rstrip("/") + "/models"
    headers: Dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    proxy_url = get_config().network.proxy_url()
    # aiohttp only supports HTTP proxies natively; skip SOCKS proxy URLs.
    if proxy_url and proxy_url.startswith("socks"):
        proxy_url = None
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(endpoint, headers=headers, proxy=proxy_url) as response:
                if response.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Model discovery request failed with status {response.status}")
                payload = await response.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to discover models: {exc}") from exc

    data = payload.get("data", [])
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Model discovery response payload is invalid")

    models: List[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
            if isinstance(model_id, str) and model_id:
                models.append(model_id)
    return models


# ── Provider connection testing ──────────────────────────────────────────


async def test_llm_provider_connection(
    provider_id: str,
    provider: Any,
    model: str,
) -> Dict[str, Any]:
    """Test an LLM provider connection with a simple chat call."""
    runtime_provider = LLMProviderSettings.model_validate(provider.model_dump())
    registry_meta = find_provider_meta(get_llm_provider_registry(), provider_id)
    adapter = build_adapter_from_provider(
        runtime_provider,
        model=model,
        default_base_url=registry_meta.default_base_url if registry_meta else None,
        adapter_factory=create_llm_adapter,
    )
    bridge = LLMProviderBridge(adapter)
    started_at = time.perf_counter()
    preview = await bridge.chat(
        system_prompt="You are a connection test assistant. Reply briefly.",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=32,
        temperature=0.1,
        disable_thinking=True,
        event_context={
            "surface": "config_provider_test",
            "provider_id": provider_id,
        },
    )
    return {
        "model": model,
        "latency_ms": int((time.perf_counter() - started_at) * 1000),
        "preview": preview[:120].strip(),
    }
