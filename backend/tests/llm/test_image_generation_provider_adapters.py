"""Tests for native image generation provider adapters."""

from __future__ import annotations

import pytest
import httpx

from magi.llm.image_generation import ImageGenerationCapability, ImageGenerationRequest
from magi.llm.image_generation.errors import ImageGenInvalidParameterError
from magi.llm.image_generation.providers.dashscope_image import DashScopeImageAdapter
from magi.llm.image_generation.providers.gemini_image import GeminiImageAdapter
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
async def test_gemini_interactions_adapter_uses_native_endpoint_and_parses_base64() -> None:
    adapter = GeminiImageAdapter(
        provider_id="gemini",
        api_key="test-key",
        model="gemini-nano-banana-2.1",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        capability=_capability(sizes=["1024x1024", "1792x1024"], max_n=1),
    )
    fake_client = _FakeHttpClient(
        {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "image", "data": "ZmFrZQ==", "mime_type": "image/png"}]}],
         "usage": {"total_input_tokens": 7, "total_output_tokens": 1000, "total_thought_tokens": 49,
                   "input_tokens_by_modality": [{"modality": "text", "tokens": 7}],
                   "output_tokens_by_modality": [{"modality": "image", "tokens": 1000}]}}
    )
    adapter._client = fake_client

    response = await adapter.generate(
        ImageGenerationRequest(
            prompt="draw a mountain",
            model="gemini-nano-banana-2.1",
            size="1792x1024",
            quality="high",
            n=1,
        )
    )

    assert fake_client.url == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "interactions"
    )
    assert fake_client.headers == {"x-goog-api-key": "test-key", "Api-Revision": "2026-05-20"}
    assert fake_client.payload == {
        "model": "gemini-nano-banana-2.1", "input": "draw a mountain", "store": False,
        "response_format": {"type": "image", "mime_type": "image/png", "aspect_ratio": "16:9", "image_size": "2K"},
    }
    assert response.images[0].b64 == "ZmFrZQ=="
    assert response.raw_metadata["usage"] == {
        "input_tokens": 7, "text_input_tokens": 7, "output_tokens": 1049,
        "image_output_tokens": 1000, "text_output_tokens": 49,
    }


@pytest.mark.asyncio
async def test_parse_json_response_accepts_numeric_success_code() -> None:
    response = httpx.Response(
        200,
        json={"code": 200, "data": {"ok": True}},
        request=httpx.Request("POST", "https://example.com"),
    )

    body = await parse_json_response(response, provider_id="example")

    assert body["data"] == {"ok": True}


@pytest.mark.parametrize("body", [{"status": "failed", "steps": []}, {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "blocked"}]}]}, {"status": "completed", "steps": None}])
@pytest.mark.asyncio
async def test_gemini_rejects_missing_or_failed_image_output(body):
    adapter = GeminiImageAdapter(provider_id="gemini", api_key="test", model="gemini-nano-banana-2.1")
    await adapter._client.aclose()
    adapter._client = _FakeHttpClient(body)
    with pytest.raises(ImageGenInvalidParameterError):
        await adapter.generate(ImageGenerationRequest(prompt="draw", model="gemini-nano-banana-2.1"))
