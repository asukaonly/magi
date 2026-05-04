"""Tests for OpenAI-compatible image generation adapter."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from magi.llm.image_generation import (
    ImageGenInvalidParameterError,
    ImageGenRateLimitError,
    ImageGenerationCapability,
    ImageGenerationRequest,
)
from magi.llm.image_generation.factory import create_image_generation_adapter
from magi.llm.image_generation.providers.openai_images import OpenAIImagesAdapter
from magi.config.llm_registry_models import (
    LLMImageGenerationModelMetaModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
)
from magi.config.models import LLMProvider, LLMProviderSettings


class _FakeImagesClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.payload: dict[str, object] | None = None

    async def generate(self, **payload):
        self.payload = dict(payload)
        if self.error is not None:
            raise self.error
        return self.response


class _ProviderError(Exception):
    def __init__(self, message: str, *, status_code: int, code: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _adapter(model: str = "gpt-image-1") -> OpenAIImagesAdapter:
    return OpenAIImagesAdapter(
        provider_id="openai",
        api_key="test-key",
        model=model,
        capability=ImageGenerationCapability(
            supported_sizes=["1024x1024", "1536x1024", "1024x1536"],
            supported_qualities=["auto", "high", "medium", "low"],
            max_n=1,
        ),
    )


def test_create_image_adapter_uses_provider_image_generation_overrides() -> None:
    registry = LLMProviderRegistryModel(
        providers=[
            LLMProviderMetaModel(
                id="openai",
                image_generation_models=[
                    LLMImageGenerationModelMetaModel(
                        id="gpt-image-1",
                        native_protocol="openai_images",
                    )
                ],
            )
        ]
    )
    provider = LLMProviderSettings(
        provider_type=LLMProvider.OPENAI,
        api_key="chat-key",
        base_url="https://chat.example.com/v1",
    )
    provider.image_generation.api_key = "image-key"
    provider.image_generation.base_url = "https://images.example.com/v1"
    provider.image_generation.timeout = 222

    adapter = create_image_generation_adapter(
        provider_id="openai",
        provider_settings=provider,
        model="gpt-image-1",
        registry=registry,
        timeout=180,
    )

    assert isinstance(adapter, OpenAIImagesAdapter)
    assert adapter._timeout == 222
    assert str(adapter._client.base_url).rstrip("/") == "https://images.example.com/v1"
    assert adapter._client.api_key == "image-key"


@pytest.mark.asyncio
async def test_openai_images_adapter_sends_unified_payload() -> None:
    image_data = base64.b64encode(b"fake-image").decode("ascii")
    fake_images = _FakeImagesClient(
        response=SimpleNamespace(
            data=[
                SimpleNamespace(b64_json=image_data, url=None, revised_prompt="a brighter prompt")
            ]
        )
    )
    adapter = _adapter()
    adapter._client = SimpleNamespace(images=fake_images)

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a quiet city",
            model="gpt-image-1",
            size="1536x1024",
            quality="high",
        )
    )

    assert fake_images.payload == {
        "model": "gpt-image-1",
        "prompt": "draw a quiet city",
        "n": 1,
        "size": "1536x1024",
        "quality": "high",
    }
    assert response.images[0].b64 == image_data
    assert response.images[0].revised_prompt == "a brighter prompt"


@pytest.mark.asyncio
async def test_openai_images_adapter_maps_dalle_quality() -> None:
    fake_images = _FakeImagesClient(response=SimpleNamespace(data=[]))
    adapter = _adapter(model="dall-e-3")
    adapter._client = SimpleNamespace(images=fake_images)

    await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a poster",
            model="dall-e-3",
            size="1024x1024",
            quality="high",
        )
    )

    assert fake_images.payload is not None
    assert fake_images.payload["quality"] == "hd"


def test_openai_images_adapter_rejects_unsupported_size() -> None:
    adapter = _adapter()

    with pytest.raises(ImageGenInvalidParameterError) as exc_info:
        adapter._build_request_kwargs(
            ImageGenerationRequest(
                prompt="draw a room",
                model="gpt-image-1",
                size="512x512",
            )
        )

    assert exc_info.value.field == "size"
    assert "1024x1024" in exc_info.value.allowed_values


@pytest.mark.asyncio
async def test_openai_images_adapter_translates_rate_limit() -> None:
    fake_images = _FakeImagesClient(
        error=_ProviderError("rate limit", status_code=429, code="rate_limit_exceeded")
    )
    adapter = _adapter()
    adapter._client = SimpleNamespace(images=fake_images)

    with pytest.raises(ImageGenRateLimitError):
        await adapter.generate(
            ImageGenerationRequest(
                prompt="draw a room",
                model="gpt-image-1",
                size="1024x1024",
            )
        )
