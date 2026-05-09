"""Centralized LLM error classification.

The codebase historically detected rate limits, auth failures, content
filters, and timeouts in four separate places (function-calling worker
retries, L2 LLM JSON client, chat streaming user-message formatter,
image-generation HTTP helper). Each kept its own substring list and
``"429"``/``"rate limit"``/``"too many requests"`` ad-hoc match. The
lists drifted apart and the ``"1302"`` / ``"speed limit"`` magic codes
had no documented home.

This module is the single source of truth. Callers feed in either an
``Exception`` (transport-level) or a parsed provider error payload
(``status_code`` + ``code`` + ``message``) and receive a structured
``ClassifiedError`` describing what kind of failure it is and whether
retrying is sensible.

Domain wrappers (e.g. ``ImageGenRateLimitError``) keep their own
exception classes — they just delegate the *classification* decision
here so the substring/code lists live in one file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class LLMErrorKind(str, Enum):
    """Coarse buckets used by retry / user-feedback logic."""

    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    TIMEOUT = "timeout"
    SERVICE_UNAVAILABLE = "service_unavailable"
    CONTENT_FILTER = "content_filter"
    INVALID_PARAMETER = "invalid_parameter"
    CONTENT_INSPECTION_FAILED = "content_inspection_failed"
    UNKNOWN = "unknown"


# Status-code → kind mapping. Entries higher in the list win when status
# alone is enough to decide; finer-grained reasoning (e.g. 400 vs 429
# both being retryable in some gateways) goes through the substring
# tables below.
_STATUS_CODE_TO_KIND: dict[int, LLMErrorKind] = {
    401: LLMErrorKind.AUTH,
    403: LLMErrorKind.AUTH,
    408: LLMErrorKind.TIMEOUT,
    429: LLMErrorKind.RATE_LIMIT,
    500: LLMErrorKind.SERVICE_UNAVAILABLE,
    502: LLMErrorKind.SERVICE_UNAVAILABLE,
    503: LLMErrorKind.SERVICE_UNAVAILABLE,
    504: LLMErrorKind.TIMEOUT,
}


# Provider-specific numeric / text codes that aren't HTTP status. These
# leak through error message bodies and lack a portable contract, but
# they're stable enough to centralize.
_RATE_LIMIT_PROVIDER_CODES: frozenset[str] = frozenset(
    {
        "429",
        "1302",  # Tencent / DashScope-style "speed limit reached" body code
        "rate_limit_exceeded",
    }
)


# Substring buckets, all matched case-insensitively. Order within a
# bucket is irrelevant; bucket-level priority is encoded in
# ``_classify_text``. CJK substrings live alongside Latin ones so
# zh-CN provider gateways are covered without each call site shipping
# its own translation table.
_RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "ratelimit",
    "rate_limit",
    "too many requests",
    "速率限制",
    "请求过于频繁",
    "quota",
)
_AUTH_MARKERS: tuple[str, ...] = (
    "auth",
    "api key",
    "apikey",
    "unauthorized",
    "forbidden",
    "鉴权",
    "未授权",
)
_CONTENT_FILTER_MARKERS: tuple[str, ...] = (
    "safety",
    "filter",
    "blocked",
    "prohibited",
    "sensitive",
    "content_policy",
    "内容审核",
)
_TIMEOUT_MARKERS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "deadline",
    "超时",
)
_INVALID_PARAMETER_MARKERS: tuple[str, ...] = (
    "invalid",
    "parameter",
    "bad request",
    "missing required",
)
_CONTENT_INSPECTION_MARKERS: tuple[str, ...] = (
    "datainspectionfailed",
    "data_inspection_failed",
)


@dataclass(frozen=True)
class ClassifiedError:
    """Structured result of classifying an upstream LLM error."""

    kind: LLMErrorKind
    status_code: int | None
    provider_code: str | None
    raw_message: str

    @property
    def retryable(self) -> bool:
        """Whether a transient retry is sensible for this kind of error."""
        return self.kind in (
            LLMErrorKind.RATE_LIMIT,
            LLMErrorKind.SERVICE_UNAVAILABLE,
            LLMErrorKind.TIMEOUT,
        )


def classify_exception(exc: Exception) -> ClassifiedError:
    """Classify a transport-level exception (raised by the LLM SDK / httpx)."""
    status_code = _coerce_int(getattr(exc, "status_code", None))
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = _coerce_int(getattr(response, "status_code", None))

    message = str(exc) or exc.__class__.__name__
    return _classify(
        status_code=status_code,
        provider_code=None,
        message=message,
    )


def classify_provider_payload(
    *,
    status_code: int | None,
    code: Any = None,
    message: str | None = None,
) -> ClassifiedError:
    """Classify a parsed provider response body.

    Used by image-generation and other paths that already have a
    structured ``{code, message}`` from the provider. ``code`` is
    accepted as ``Any`` because providers play loose with int / str.
    """
    raw_message = str(message or "").strip()
    return _classify(
        status_code=_coerce_int(status_code),
        provider_code=str(code).strip() if code not in (None, "") else None,
        message=raw_message,
    )


def is_rate_limit_exception(exc: Exception) -> bool:
    """Common ``except`` predicate used by retry loops."""
    return classify_exception(exc).kind == LLMErrorKind.RATE_LIMIT


def _classify(
    *,
    status_code: int | None,
    provider_code: str | None,
    message: str,
) -> ClassifiedError:
    text = message.lower()
    code_text = (provider_code or "").lower()

    # Order matters here: more specific kinds win over broader buckets.
    # Content-inspection-failed before generic "filter" so the upstream
    # `CONTENT_INSPECTION_FAILED` bucket survives.
    if _matches(text, _CONTENT_INSPECTION_MARKERS):
        return _result(
            LLMErrorKind.CONTENT_INSPECTION_FAILED, status_code, provider_code, message
        )

    if _matches(text, _CONTENT_FILTER_MARKERS):
        return _result(LLMErrorKind.CONTENT_FILTER, status_code, provider_code, message)

    if status_code == 429 or _matches(text, _RATE_LIMIT_MARKERS) or code_text in _RATE_LIMIT_PROVIDER_CODES:
        return _result(LLMErrorKind.RATE_LIMIT, status_code, provider_code, message)

    if status_code in (401, 403) or _matches(text, _AUTH_MARKERS):
        return _result(LLMErrorKind.AUTH, status_code, provider_code, message)

    if status_code in (408, 504) or _matches(text, _TIMEOUT_MARKERS):
        return _result(LLMErrorKind.TIMEOUT, status_code, provider_code, message)

    if status_code in (500, 502, 503):
        return _result(LLMErrorKind.SERVICE_UNAVAILABLE, status_code, provider_code, message)

    if status_code in (400, 422) or _matches(text, _INVALID_PARAMETER_MARKERS):
        return _result(LLMErrorKind.INVALID_PARAMETER, status_code, provider_code, message)

    if status_code is not None and status_code in _STATUS_CODE_TO_KIND:
        return _result(_STATUS_CODE_TO_KIND[status_code], status_code, provider_code, message)

    return _result(LLMErrorKind.UNKNOWN, status_code, provider_code, message)


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _result(
    kind: LLMErrorKind,
    status_code: int | None,
    provider_code: str | None,
    message: str,
) -> ClassifiedError:
    return ClassifiedError(
        kind=kind,
        status_code=status_code,
        provider_code=provider_code,
        raw_message=message,
    )


__all__ = [
    "ClassifiedError",
    "LLMErrorKind",
    "classify_exception",
    "classify_provider_payload",
    "is_rate_limit_exception",
]
