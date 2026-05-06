"""Google Gemini Imagen prediction adapter."""

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


class GeminiPredictImageAdapter(ImageGenerationAdapter):
    """Adapter for Gemini API Imagen models via `models/{model}:predict`."""

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
            max_n=4,
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
        size = self.normalize_size(req.size)
        quality = self.normalize_quality(req.quality)
        parameters: dict[str, Any] = {
            "sampleCount": req.n,
            "aspectRatio": _SIZE_TO_ASPECT_RATIO[size],
            "personGeneration": "allow_adult",
        }
        if quality == "high" and "fast" not in (req.model or self._model).lower():
            parameters["imageSize"] = "2K"
        elif "fast" not in (req.model or self._model).lower():
            parameters["imageSize"] = "1K"
        return {
            "instances": [{"prompt": req.prompt}],
            "parameters": parameters,
        }

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        payload = self._build_request_payload(req)
        model = str(req.model or self._model).strip()
        endpoint = join_url(self._base_url, f"models/{model}:predict")
        try:
            response = await self._client.post(
                endpoint,
                headers={"x-goog-api-key": self._api_key},
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
                field="predictions.bytesBase64Encoded",
                provider_id=self.provider_id,
                raw=body,
            )
        return ImageGenerationResponse(
            images=images,
            model=model,
            raw_metadata={"provider_id": self.provider_id, "request": payload, "response": body},
        )


def _normalize_gemini_base_url(base_url: str | None) -> str:
    raw_base_url = str(base_url or GEMINI_DEFAULT_BASE_URL).strip().rstrip("/")
    if raw_base_url.endswith("/openai"):
        raw_base_url = raw_base_url.removesuffix("/openai")
    return raw_base_url


def _extract_gemini_images(body: dict[str, Any]) -> list[ImageArtifact]:
    images: list[ImageArtifact] = []
    predictions = body.get("predictions")
    if isinstance(predictions, list):
        for prediction in predictions:
            images.extend(_images_from_prediction(prediction))

    candidates = body.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                inline_data = part.get("inlineData") if isinstance(part, dict) else None
                if isinstance(inline_data, dict) and inline_data.get("data"):
                    images.append(
                        ImageArtifact(
                            b64=str(inline_data["data"]),
                            mime=str(inline_data.get("mimeType") or "image/png"),
                            raw_metadata=dict(part),
                        )
                    )
    return images


def _images_from_prediction(prediction: Any) -> list[ImageArtifact]:
    if not isinstance(prediction, dict):
        return []
    image_source = prediction.get("image") if isinstance(prediction.get("image"), dict) else prediction
    image_data = (
        image_source.get("bytesBase64Encoded")
        or image_source.get("bytes_base64_encoded")
        or image_source.get("b64_json")
        or image_source.get("data")
    )
    if not image_data:
        return []
    return [
        ImageArtifact(
            b64=str(image_data),
            mime=str(image_source.get("mimeType") or image_source.get("mime_type") or "image/png"),
            raw_metadata=dict(prediction),
        )
    ]


__all__ = ["GeminiPredictImageAdapter"]