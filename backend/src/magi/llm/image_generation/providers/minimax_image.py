"""MiniMax image generation adapter."""

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
from .http_common import join_url, parse_json_response, provider_error_from_body, translate_httpx_error

MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_SUPPORTED_SIZES = [
    "1024x1024",
    "1792x1024",
    "1024x1792",
    "1024x768",
    "768x1024",
]
MINIMAX_SUPPORTED_QUALITIES = ["auto", "high", "medium", "low"]
_SIZE_TO_ASPECT_RATIO = {
    "1024x1024": "1:1",
    "1792x1024": "16:9",
    "1024x1792": "9:16",
    "1024x768": "4:3",
    "768x1024": "3:4",
}


class MiniMaxImageAdapter(ImageGenerationAdapter):
    """Adapter for MiniMax `/image_generation`."""

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
        self._base_url = str(base_url or MINIMAX_DEFAULT_BASE_URL).rstrip("/")
        self.capability = capability or ImageGenerationCapability(
            supported_sizes=list(MINIMAX_SUPPORTED_SIZES),
            supported_qualities=list(MINIMAX_SUPPORTED_QUALITIES),
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
        size = self.normalize_size(req.size)
        self.normalize_quality(req.quality)
        return {
            "model": req.model or self._model,
            "prompt": req.prompt,
            "aspect_ratio": _SIZE_TO_ASPECT_RATIO[size],
            "response_format": "base64",
        }

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        payload = self._build_request_payload(req)
        endpoint = join_url(self._base_url, "image_generation")
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

        base_response = body.get("base_resp")
        if isinstance(base_response, dict):
            status_code = base_response.get("status_code")
            if status_code not in (None, 0, "0"):
                raise provider_error_from_body(
                    {
                        "code": status_code,
                        "message": base_response.get("status_msg") or body.get("message"),
                    },
                    status_code=200,
                    provider_id=self.provider_id,
                    raw=body,
                )

        data = body.get("data")
        image_values = _coerce_image_base64_values(
            data.get("image_base64") if isinstance(data, dict) else None
        )
        if not image_values:
            raise ImageGenInvalidParameterError(
                "MiniMax did not return image_base64 data.",
                field="data.image_base64",
                provider_id=self.provider_id,
                raw=body,
            )

        return ImageGenerationResponse(
            images=[
                ImageArtifact(b64=image_value, mime="image/png", raw_metadata={"index": index})
                for index, image_value in enumerate(image_values)
            ],
            model=str(payload.get("model") or self._model),
            raw_metadata={"provider_id": self.provider_id, "request": payload, "response": body},
        )


def _coerce_image_base64_values(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


__all__ = ["MiniMaxImageAdapter"]