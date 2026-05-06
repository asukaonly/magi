"""Z.ai image generation adapter."""

from __future__ import annotations

from typing import Any

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

ZAI_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZAI_SUPPORTED_SIZES = [
    "1280x1280",
    "1024x1024",
    "1568x1056",
    "1056x1568",
    "1472x1088",
    "1088x1472",
    "1728x960",
    "960x1728",
]
ZAI_SUPPORTED_QUALITIES = ["auto", "high", "medium", "low"]


class ZAIImagesAdapter(ImageGenerationAdapter):
    """Adapter for Z.ai `/images/generations`."""

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
        self._base_url = str(base_url or ZAI_DEFAULT_BASE_URL).rstrip("/")
        self.capability = capability or ImageGenerationCapability(
            supported_sizes=list(ZAI_SUPPORTED_SIZES),
            supported_qualities=list(ZAI_SUPPORTED_QUALITIES),
            max_n=1,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy_url,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def normalize_quality(self, raw: str) -> str:
        quality = super().normalize_quality(raw)
        if quality == "auto":
            return ""
        if quality == "high":
            return "hd"
        return "standard"

    def _build_request_payload(self, req: ImageGenerationRequest) -> dict[str, Any]:
        self.validate_request(req)
        payload: dict[str, Any] = {
            "model": req.model or self._model,
            "prompt": req.prompt,
            "size": self.normalize_size(req.size),
        }
        quality = self.normalize_quality(req.quality)
        if quality:
            payload["quality"] = quality
        return payload

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        payload = self._build_request_payload(req)
        endpoint = join_url(self._base_url, "images/generations")
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

        image_items = body.get("data")
        if not isinstance(image_items, list) or not image_items:
            raise ImageGenInvalidParameterError(
                "Z.ai did not return generated image URLs.",
                field="data",
                provider_id=self.provider_id,
                raw=body,
            )

        images: list[ImageArtifact] = []
        for item in image_items:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            images.append(
                ImageArtifact(
                    url=str(item["url"]),
                    mime="image/png",
                    raw_metadata=dict(item),
                )
            )
        if not images:
            raise ImageGenInvalidParameterError(
                "Z.ai response did not include usable image URLs.",
                field="data.url",
                provider_id=self.provider_id,
                raw=body,
            )

        return ImageGenerationResponse(
            images=images,
            model=str(payload.get("model") or self._model),
            raw_metadata={"provider_id": self.provider_id, "request": payload, "response": body},
        )


__all__ = ["ZAIImagesAdapter"]