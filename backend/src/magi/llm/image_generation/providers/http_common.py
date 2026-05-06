"""Shared HTTP helpers for image generation provider adapters."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from ..errors import (
    ImageGenAuthError,
    ImageGenContentFilteredError,
    ImageGenInvalidParameterError,
    ImageGenProviderError,
    ImageGenRateLimitError,
    ImageGenTimeoutError,
)


def join_url(base_url: str, path: str) -> str:
    """Join a base URL and path without losing nested API prefixes."""
    normalized_base = str(base_url or "").strip().rstrip("/") + "/"
    normalized_path = str(path or "").strip().lstrip("/")
    return urljoin(normalized_base, normalized_path)


async def parse_json_response(
    response: httpx.Response,
    *,
    provider_id: str,
) -> dict[str, Any]:
    """Parse a provider response and map transport/provider errors."""
    try:
        body = response.json()
    except ValueError as exc:
        raise ImageGenProviderError(
            "Image generation provider returned a non-JSON response.",
            status_code=response.status_code,
            provider_id=provider_id,
            raw=exc,
        ) from exc
    if not isinstance(body, dict):
        raise ImageGenProviderError(
            "Image generation provider returned an unexpected response shape.",
            status_code=response.status_code,
            provider_id=provider_id,
            raw=body,
        )
    if response.is_error:
        raise provider_error_from_body(
            body,
            status_code=response.status_code,
            provider_id=provider_id,
        )
    provider_code = body.get("code")
    provider_message = body.get("message")
    if _is_error_code(provider_code):
        raise provider_error_from_body(
            body,
            status_code=response.status_code,
            provider_id=provider_id,
            fallback_message=str(provider_message or provider_code),
        )
    return body


def translate_httpx_error(exc: Exception, *, provider_id: str) -> ImageGenProviderError:
    """Translate low-level httpx errors into image generation errors."""
    if isinstance(exc, httpx.TimeoutException):
        return ImageGenTimeoutError(
            "Image generation request timed out.",
            provider_id=provider_id,
            raw=exc,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        body = _response_json(exc.response)
        return provider_error_from_body(
            body,
            status_code=exc.response.status_code,
            provider_id=provider_id,
            fallback_message=str(exc),
            raw=exc,
        )
    if isinstance(exc, httpx.HTTPError):
        return ImageGenProviderError(
            f"Image generation provider request failed: {exc}",
            provider_id=provider_id,
            raw=exc,
        )
    return ImageGenProviderError(
        str(exc) or exc.__class__.__name__,
        provider_id=provider_id,
        raw=exc,
    )


def provider_error_from_body(
    body: Any,
    *,
    status_code: int | None,
    provider_id: str,
    fallback_message: str | None = None,
    raw: Any = None,
) -> ImageGenProviderError:
    """Create a structured provider error from a JSON error payload."""
    code = _extract_error_code(body)
    message = _extract_error_message(body) or fallback_message or "Image generation failed."
    lowered = f"{code or ''} {message}".lower()
    raw_payload = raw if raw is not None else body

    if any(token in lowered for token in ("safety", "filter", "blocked", "prohibited", "sensitive")):
        return ImageGenContentFilteredError(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw_payload,
        )
    if status_code in (401, 403) or "auth" in lowered or "api key" in lowered:
        return ImageGenAuthError(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw_payload,
        )
    if status_code == 429 or "rate" in lowered or "quota" in lowered:
        return ImageGenRateLimitError(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw_payload,
        )
    if status_code in (408, 504) or "timeout" in lowered:
        return ImageGenTimeoutError(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw_payload,
        )
    if status_code in (400, 422) or "invalid" in lowered or "parameter" in lowered:
        return ImageGenInvalidParameterError(
            message,
            status_code=status_code,
            code=code,
            provider_id=provider_id,
            raw=raw_payload,
        )
    return ImageGenProviderError(
        message,
        status_code=status_code,
        code=code,
        provider_id=provider_id,
        raw=raw_payload,
    )


def collect_values_by_key(value: Any, key: str) -> list[Any]:
    """Collect values for a key recursively from nested dict/list provider payloads."""
    matches: list[Any] = []
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            if item_key == key:
                matches.append(item_value)
            matches.extend(collect_values_by_key(item_value, key))
    elif isinstance(value, list):
        for item in value:
            matches.extend(collect_values_by_key(item, key))
    return matches


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _is_error_code(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized not in {"", "0", "200", "ok", "success", "none", "null"}


def _extract_error_code(body: Any) -> str | None:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("code", "status"):
                value = error.get(key)
                if value:
                    return str(value)
        for key in ("code", "status", "error_code"):
            value = body.get(key)
            if value:
                return str(value)
    return None


def _extract_error_message(body: Any) -> str | None:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error.get("message"))
        for key in ("message", "error_msg", "msg"):
            value = body.get(key)
            if value:
                return str(value)
    return None


__all__ = [
    "collect_values_by_key",
    "join_url",
    "parse_json_response",
    "provider_error_from_body",
    "translate_httpx_error",
]