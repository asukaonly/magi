"""Tests for native image generation provider adapters."""

from __future__ import annotations

import pytest
import httpx

from magi.config.llm_registry_models import (
    LLMImageGenerationModelMetaModel,
    LLMProviderMetaModel,
    LLMProviderRegistryModel,
)
from magi.config.models import LLMProvider, LLMProviderSettings
from magi.llm.image_generation import ImageGenerationCapability, ImageGenerationRequest
from magi.llm.image_generation.factory import create_image_generation_adapter
from magi.llm.image_generation.providers.dashscope_image import DashScopeImageAdapter
from magi.llm.image_generation.providers.gemini_predict import GeminiPredictImageAdapter
from magi.llm.image_generation.providers.http_common import parse_json_response
from magi.llm.image_generation.providers.minimax_image import MiniMaxImageAdapter
from magi.llm.image_generation.providers.zai_images import ZAIImagesAdapter


class _FakeHttpClient:
    def __init__(self, body: dict[str, object], status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.url: str | None = None
        self.headers: dict[str, str] | None = None
        self.payload: dict[str, object] | None = None
        self.closed = False

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        self.url = url
        self.headers = dict(headers or {})
        self.payload = dict(json or {})
        return httpx.Response(
            self.status_code,
            json=self.body,
            request=httpx.Request("POST", url),
        )

    async def aclose(self) -> None:
        self.closed = True


def _capability(
    *,
    sizes: list[str],
    qualities: list[str] | None = None,
    max_n: int = 1,
    supports_negative_prompt: bool = False,
) -> ImageGenerationCapability:
    return ImageGenerationCapability(
        supported_sizes=sizes,
        supported_qualities=qualities or ["auto", "high", "medium", "low"],
        supports_negative_prompt=supports_negative_prompt,
        max_n=max_n,
    )


@pytest.mark.asyncio
async def test_minimax_image_adapter_sends_aspect_ratio_and_parses_base64() -> None:
    adapter = MiniMaxImageAdapter(
        provider_id="minimax",
        api_key="test-key",
        model="image-01",
        capability=_capability(sizes=["1024x1024", "1792x1024"]),
    )
    fake_client = _FakeHttpClient({"data": {"image_base64": "ZmFrZS1pbWFnZQ=="}})
    adapter._client = fake_client

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a city at night",
            model="image-01",
            size="1792x1024",
        )
    )

    assert fake_client.url == "https://api.minimaxi.com/v1/image_generation"
    assert fake_client.headers == {"Authorization": "Bearer test-key"}
    assert fake_client.payload == {
        "model": "image-01",
        "prompt": "draw a city at night",
        "aspect_ratio": "16:9",
        "response_format": "base64",
    }
    assert response.images[0].b64 == "ZmFrZS1pbWFnZQ=="


@pytest.mark.asyncio
async def test_zai_images_adapter_sends_images_endpoint_and_parses_url() -> None:
    adapter = ZAIImagesAdapter(
        provider_id="glm",
        api_key="test-key",
        model="cogview-4",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        capability=_capability(sizes=["1024x1024"]),
    )
    fake_client = _FakeHttpClient({"data": [{"url": "https://example.com/generated.png"}]})
    adapter._client = fake_client

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a small studio",
            model="cogview-4",
            size="1024x1024",
            quality="high",
        )
    )

    assert fake_client.url == "https://open.bigmodel.cn/api/paas/v4/images/generations"
    assert fake_client.payload == {
        "model": "cogview-4",
        "prompt": "draw a small studio",
        "size": "1024x1024",
        "quality": "hd",
    }
    assert response.images[0].url == "https://example.com/generated.png"


@pytest.mark.asyncio
async def test_dashscope_image_adapter_normalizes_chat_base_url_and_parses_url() -> None:
    adapter = DashScopeImageAdapter(
        provider_id="dashscope",
        api_key="test-key",
        model="qwen-image-2.0-pro",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        capability=_capability(
            sizes=["1024x1024"],
            max_n=2,
            supports_negative_prompt=True,
        ),
    )
    fake_client = _FakeHttpClient(
        {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [{"image": "https://dashscope.example/image.png"}]
                        }
                    }
                ]
            }
        }
    )
    adapter._client = fake_client

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a product render",
            model="qwen-image-2.0-pro",
            size="1024x1024",
            n=2,
            negative_prompt="blur",
        )
    )

    assert fake_client.url == (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )
    assert fake_client.payload == {
        "model": "qwen-image-2.0-pro",
        "input": {
            "messages": [
                {"role": "user", "content": [{"text": "draw a product render"}]}
            ]
        },
        "parameters": {"size": "1024*1024", "n": 2, "negative_prompt": "blur"},
    }
    assert response.images[0].url == "https://dashscope.example/image.png"


@pytest.mark.asyncio
async def test_gemini_predict_adapter_uses_predict_endpoint_and_parses_base64() -> None:
    adapter = GeminiPredictImageAdapter(
        provider_id="gemini",
        api_key="test-key",
        model="imagen-4.0-generate-001",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        capability=_capability(sizes=["1024x1024", "1792x1024"], max_n=4),
    )
    fake_client = _FakeHttpClient(
        {"predictions": [{"bytesBase64Encoded": "ZmFrZQ==", "mimeType": "image/png"}]}
    )
    adapter._client = fake_client

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a mountain",
            model="imagen-4.0-generate-001",
            size="1792x1024",
            quality="high",
            n=3,
        )
    )

    assert fake_client.url == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/imagen-4.0-generate-001:predict"
    )
    assert fake_client.headers == {"x-goog-api-key": "test-key"}
    assert fake_client.payload == {
        "instances": [{"prompt": "draw a mountain"}],
        "parameters": {
            "sampleCount": 3,
            "aspectRatio": "16:9",
            "personGeneration": "allow_adult",
            "imageSize": "2K",
        },
    }
    assert response.images[0].b64 == "ZmFrZQ=="


@pytest.mark.asyncio
async def test_parse_json_response_accepts_numeric_success_code() -> None:
    response = httpx.Response(
        200,
        json={"code": 200, "data": {"ok": True}},
        request=httpx.Request("POST", "https://example.com"),
    )

    body = await parse_json_response(response, provider_id="example")

    assert body["data"] == {"ok": True}


def test_factory_creates_minimax_adapter_for_registered_protocol() -> None:
    registry = LLMProviderRegistryModel(
        providers=[
            LLMProviderMetaModel(
                id="minimax",
                image_generation_models=[
                    LLMImageGenerationModelMetaModel(
                        id="image-01",
                        native_protocol="minimax_image",
                        supported_sizes=["1024x1024"],
                        supported_qualities=["auto"],
                    )
                ],
            )
        ]
    )
    provider = LLMProviderSettings(provider_type=LLMProvider.MINIMAX, api_key="provider-key")
    provider.services.image_generation.enabled = True

    adapter = create_image_generation_adapter(
        provider_id="minimax",
        provider_settings=provider,
        model="image-01",
        registry=registry,
        timeout=180,
    )

    assert isinstance(adapter, MiniMaxImageAdapter)
    assert adapter.capability.supported_sizes == ["1024x1024"]