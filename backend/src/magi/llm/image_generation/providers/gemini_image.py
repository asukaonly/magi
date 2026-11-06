"""Google Gemini native image generation adapter."""

from __future__ import annotations

from typing import Any

import httpx
from ...media_usage import gemini_image_usage

from ..base import ImageGenerationAdapter
from ..errors import ImageGenInvalidParameterError
from ..types import (
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from .http_common import join_url, parse_json_response, translate_httpx_error

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_SUPPORTED_SIZES = [
    "1024x1024",
    "1024x768",
    "768x1024",
    "1792x1024",
    "1024x1792",
]
GEMINI_SUPPORTED_QUALITIES = ["auto", "high", "medium", "low"]
_SIZE_TO_ASPECT_RATIO = {
    "1024x1024": "1:1",
    "1024x768": "4:3",
    "768x1024": "3:4",
    "1792x1024": "16:9",
    "1024x1792": "9:16",
}


class GeminiImageAdapter(ImageGenerationAdapter):
    """Adapter for Gemini images through the stateless Interactions API."""

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
        self._base_url = _normalize_gemini_base_url(base_url)
        self.capability = capability or ImageGenerationCapability(
            supported_sizes=list(GEMINI_SUPPORTED_SIZES),
            supported_qualities=list(GEMINI_SUPPORTED_QUALITIES),
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
        if req.n != 1:
            raise ImageGenInvalidParameterError("Gemini generates one image per request.", field="n", provider_id=self.provider_id)
        size = self.normalize_size(req.size)
        quality = self.normalize_quality(req.quality)
        return {
            "model": req.model or self._model,
            "input": req.prompt,
            "store": False,
            "response_format": {
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": _SIZE_TO_ASPECT_RATIO[size],
                "image_size": "2K" if quality == "high" else "1K",
            },
        }

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        payload = self._build_request_payload(req)
        model = str(req.model or self._model).strip()
        endpoint = join_url(self._base_url, "interactions")
        try:
            response = await self._client.post(
                endpoint,
                headers={"x-goog-api-key": self._api_key, "Api-Revision": "2026-05-20"},
                json=payload,
            )
            body = await parse_json_response(response, provider_id=self.provider_id)
        except Exception as exc:  # noqa: BLE001 - mapped into provider taxonomy
            if hasattr(exc, "provider_id"):
                raise
            raise translate_httpx_error(exc, provider_id=self.provider_id) from exc

        images = _extract_gemini_images(body)
        if not images:
            raise ImageGenInvalidParameterError(
                "Gemini did not return base64 image data.",
                field="steps.content.data",
                provider_id=self.provider_id,
                raw=body,
            )
        return ImageGenerationResponse(
            images=images,
            model=model,
            raw_metadata={"provider_id": self.provider_id, "request": payload, "response": body,
                          "usage": gemini_image_usage(body.get("usage"))},
        )


def _normalize_gemini_base_url(base_url: str | None) -> str:
    raw_base_url = str(base_url or GEMINI_DEFAULT_BASE_URL).strip().rstrip("/")
    if raw_base_url.endswith("/openai"):
        raw_base_url = raw_base_url.removesuffix("/openai")
    return raw_base_url


def _extract_gemini_images(body: dict[str, Any]) -> list[ImageArtifact]:
    images: list[ImageArtifact] = []
    steps = body.get("steps")
    if body.get("status") != "completed" or not isinstance(steps, list):
        return images
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image":
                continue
            data, mime = part.get("data"), part.get("mime_type")
            if isinstance(data, str) and data and mime in {"image/png", "image/jpeg", "image/webp"}:
                images.append(ImageArtifact(b64=data, mime=mime, raw_metadata=dict(part)))
    return images


__all__ = ["GeminiImageAdapter"]
