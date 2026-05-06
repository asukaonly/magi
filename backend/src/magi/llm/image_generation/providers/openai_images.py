"""OpenAI-compatible Images API adapter."""

from __future__ import annotations

import inspect
from typing import Any

import httpx
from openai import AsyncOpenAI

from ..base import ImageGenerationAdapter
from ..errors import (
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
)
from ..types import (
    ImageArtifact,
    ImageGenerationCapability,
    ImageGenerationRequest,
    ImageGenerationResponse,
)

GPT_IMAGE_1_SIZES = ["1024x1024", "1536x1024", "1024x1536"]
GPT_IMAGE_1_QUALITIES = ["auto", "high", "medium", "low"]
DALL_E_3_SIZES = ["1024x1024", "1792x1024", "1024x1792"]
DALL_E_3_QUALITIES = ["auto", "high", "medium", "low"]


class OpenAIImagesAdapter(ImageGenerationAdapter):
    """Adapter for OpenAI-compatible image generation endpoints."""

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
        self._model = model
        self._timeout = timeout
        self.capability = capability or self._default_capability_for_model(model)

        self._http_client = httpx.AsyncClient(
            proxy=proxy_url,
            trust_env=False,
        )
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": timeout,
            "http_client": self._http_client,
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**client_kwargs)

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
            return
        await self._http_client.aclose()

    @staticmethod
    def _default_capability_for_model(model: str) -> ImageGenerationCapability:
        normalized_model = str(model or "").strip().lower()
        if normalized_model == "dall-e-3":
            return ImageGenerationCapability(
                supported_sizes=list(DALL_E_3_SIZES),
                supported_qualities=list(DALL_E_3_QUALITIES),
                max_n=1,
            )
        return ImageGenerationCapability(
            supported_sizes=list(GPT_IMAGE_1_SIZES),
            supported_qualities=list(GPT_IMAGE_1_QUALITIES),
            max_n=1,
        )

    def normalize_quality(self, raw: str) -> str:
        quality = super().normalize_quality(raw)
        if self._model.strip().lower() == "dall-e-3":
            return "hd" if quality == "high" else "standard"
        return quality

    def _build_request_kwargs(self, req: ImageGenerationRequest) -> dict[str, Any]:
        self.validate_request(req)
        payload: dict[str, Any] = {
            "model": req.model or self._model,
            "prompt": req.prompt,
            "n": req.n,
            "size": self.normalize_size(req.size),
        }
        quality = self.normalize_quality(req.quality)
        if quality:
            payload["quality"] = quality
        return payload

    async def generate(self, req: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate images via the OpenAI-compatible Images API."""
        payload = self._build_request_kwargs(req)
        try:
            response = await self._client.images.generate(**payload)
        except Exception as exc:  # noqa: BLE001 - mapped to structured provider errors below
            raise self._translate_error(exc) from exc

        images: list[ImageArtifact] = []
        for item in getattr(response, "data", []) or []:
            raw_metadata = _model_dump(item)
            images.append(
                ImageArtifact(
                    b64=getattr(item, "b64_json", None),
                    url=getattr(item, "url", None),
                    mime="image/png",
                    revised_prompt=getattr(item, "revised_prompt", None),
                    raw_metadata=raw_metadata,
                )
            )
        return ImageGenerationResponse(
            images=images,
            model=str(payload.get("model") or self._model),
            raw_metadata={"provider_id": self.provider_id, "request": payload},
        )

    def _translate_error(self, exc: Exception) -> ImageGenProviderError:
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return ImageGenTimeoutError(
                "Image generation request timed out.",
                provider_id=self.provider_id,
                raw=exc,
            )

        status_code = _extract_status_code(exc)
        code = _extract_error_code(exc)
        message = _extract_error_message(exc)
        lowered = f"{code or ''} {message}".lower()

        if "content_policy" in lowered or "safety" in lowered or "filtered" in lowered:
            return ImageGenContentFilteredError(
                message,
                status_code=status_code,
                code=code,
                provider_id=self.provider_id,
                raw=exc,
            )
        if status_code in (401, 403):
            return ImageGenAuthError(
                message,
                status_code=status_code,
                code=code,
                provider_id=self.provider_id,
                raw=exc,
            )
        if status_code == 429:
            return ImageGenRateLimitError(
                message,
                status_code=status_code,
                code=code,
                provider_id=self.provider_id,
                raw=exc,
            )
        if status_code in (408, 504):
            return ImageGenTimeoutError(
                message,
                status_code=status_code,
                code=code,
                provider_id=self.provider_id,
                raw=exc,
            )
        if status_code in (400, 422):
            return ImageGenInvalidParameterError(
                message,
                status_code=status_code,
                code=code,
                provider_id=self.provider_id,
                raw=exc,
            )
        return ImageGenProviderError(
            message,
            status_code=status_code,
            code=code,
            provider_id=self.provider_id,
            raw=exc,
        )


def _model_dump(value: Any) -> dict[str, Any]:
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        dumped = dumper()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _extract_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _extract_error_code(exc: Exception) -> str | None:
    code = getattr(exc, "code", None)
    if code:
        return str(code)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code"):
            return str(error.get("code"))
        if body.get("code"):
            return str(body.get("code"))
    return None


def _extract_error_message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error.get("message"))
        if body.get("message"):
            return str(body.get("message"))
    return str(exc) or exc.__class__.__name__


__all__ = ["OpenAIImagesAdapter"]
