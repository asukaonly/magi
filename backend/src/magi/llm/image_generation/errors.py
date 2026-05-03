"""Structured image generation error taxonomy."""

from __future__ import annotations

from typing import Any


class ImageGenProviderError(Exception):
    """Base class for image generation provider errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        provider_id: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.provider_id = provider_id
        self.raw = raw


class ImageGenAuthError(ImageGenProviderError):
    """Provider rejected credentials or authorization."""


class ImageGenRateLimitError(ImageGenProviderError):
    """Provider rate-limited the request."""


class ImageGenTimeoutError(ImageGenProviderError):
    """Provider call timed out."""


class ImageGenContentFilteredError(ImageGenProviderError):
    """Provider blocked the request due to safety or content policy."""


class ImageGenInvalidParameterError(ImageGenProviderError):
    """Provider-independent parameter validation failure."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        allowed_values: list[str] | None = None,
        status_code: int | None = None,
        code: str | None = None,
        provider_id: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw,
        )
        self.field = field
        self.allowed_values = list(allowed_values or [])
