"""DashScope image generation adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from ..base import ImageGenerationAdapter
from ..errors import ImageGenInvalidParameterError
from ..types import (
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from .http_common import join_url, parse_json_response, translate_httpx_error

DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
DASHSCOPE_SUPPORTED_SIZES = [
    "1024x1024",
    "2048x2048",
    "1536x864",
    "864x1536",
    "1152x864",
    "864x1152",
    "1344x768",
    "768x1344",
]
DASHSCOPE_SUPPORTED_QUALITIES = ["auto", "high", "medium", "low"]


class DashScopeImageAdapter(ImageGenerationAdapter):
    """Adapter for DashScope multimodal image generation."""

    def __init__(
        self,
        *,
        provider_id: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout: int = 180,
        proxy_url: str | None = None,
        capability: ImageGenerationCapability | None = None,
    ) -> None:
        self.provider_id = provider_id
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._base_url = _normalize_dashscope_base_url(base_url)
        self.capability = capability or ImageGenerationCapability(
            supported_sizes=list(DASHSCOPE_SUPPORTED_SIZES),
            supported_qualities=list(DASHSCOPE_SUPPORTED_QUALITIES),
            supports_negative_prompt=True,
            max_n=1,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy_url,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _build_request_payload(self, req: ImageGenerationRequest) -> dict[str, Any]:
        self.validate_request(req)
        self.normalize_quality(req.quality)
        parameters: dict[str, Any] = {
            "size": self.normalize_size(req.size).replace("x", "*"),
            "n": req.n,
        }
        if req.negative_prompt:
            parameters["negative_prompt"] = req.negative_prompt
        return {
            "model": req.model or self._model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": req.prompt}],
                    }
                ]
            },
            "parameters": parameters,
        }

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        payload = self._build_request_payload(req)
        endpoint = join_url(self._base_url, "services/aigc/multimodal-generation/generation")
        try:
            response = await self._client.post(
                endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            body = await parse_json_response(response, provider_id=self.provider_id)
        except Exception as exc:  # noqa: BLE001 - mapped into provider taxonomy
            if hasattr(exc, "provider_id"):
                raise
            raise translate_httpx_error(exc, provider_id=self.provider_id) from exc

        images = _extract_dashscope_images(body)
        if not images:
            raise ImageGenInvalidParameterError(
                "DashScope did not return generated image URLs.",
                field="output.choices.message.content.image",
                provider_id=self.provider_id,
                raw=body,
            )
        return ImageGenerationResponse(
            images=images,
            model=str(payload.get("model") or self._model),
            raw_metadata={"provider_id": self.provider_id, "request": payload, "response": body},
        )


def _normalize_dashscope_base_url(base_url: str | None) -> str:
    raw_base_url = str(base_url or DASHSCOPE_DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(raw_base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/compatible-mode/v1"):
        path = f"{path.removesuffix('/compatible-mode/v1')}/api/v1"
    elif not path or path == "/":
        path = "/api/v1"
    return urlunparse(parsed._replace(path=path)).rstrip("/")


def _extract_dashscope_images(body: dict[str, Any]) -> list[ImageArtifact]:
    images: list[ImageArtifact] = []
    output = body.get("output")
    if not isinstance(output, dict):
        return images

    choices = output.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            content_items = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content_items, list):
                continue
            for item in content_items:
                if isinstance(item, dict) and item.get("image"):
                    images.append(ImageArtifact(url=str(item["image"]), mime="image/png", raw_metadata=dict(item)))

    results = output.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and item.get("url"):
                images.append(ImageArtifact(url=str(item["url"]), mime="image/png", raw_metadata=dict(item)))
    return images


__all__ = ["DashScopeImageAdapter"]