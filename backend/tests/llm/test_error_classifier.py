"""Unit tests for the centralized LLM error classifier."""

from __future__ import annotations

import pytest

from magi.llm.error_classifier import (
    ClassifiedError,
    LLMErrorKind,
    classify_exception,
    classify_provider_payload,
    is_rate_limit_exception,
)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeHTTPError(Exception):
    def __init__(self, message: str, status_code: int | None = None, response=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if response is not None:
            self.response = response


class TestClassifyException:
    def test_status_429_is_rate_limit(self) -> None:
        result = classify_exception(_FakeHTTPError("nope", status_code=429))
        assert result.kind == LLMErrorKind.RATE_LIMIT
        assert result.retryable is True

    def test_response_status_429_is_rate_limit(self) -> None:
        result = classify_exception(
            _FakeHTTPError("nope", response=_FakeResponse(429))
        )
        assert result.kind == LLMErrorKind.RATE_LIMIT

    def test_status_401_is_auth(self) -> None:
        result = classify_exception(_FakeHTTPError("unauthorized", status_code=401))
        assert result.kind == LLMErrorKind.AUTH
        assert result.retryable is False

    def test_status_403_is_auth(self) -> None:
        assert classify_exception(_FakeHTTPError("x", status_code=403)).kind == LLMErrorKind.AUTH

    def test_5xx_service_unavailable(self) -> None:
        for code in (500, 502, 503):
            assert (
                classify_exception(_FakeHTTPError("x", status_code=code)).kind
                == LLMErrorKind.SERVICE_UNAVAILABLE
            )

    def test_504_is_timeout_not_unavailable(self) -> None:
        assert classify_exception(_FakeHTTPError("gateway timeout", status_code=504)).kind == LLMErrorKind.TIMEOUT

    @pytest.mark.parametrize(
        "message",
        [
            "rate limit exceeded",
            "Too many requests, slow down",
            "ratelimit hit",
            "上游返回 速率限制",
            "请求过于频繁",
            "Quota exceeded for project",
        ],
    )
    def test_substring_rate_limit(self, message: str) -> None:
        result = classify_exception(Exception(message))
        assert result.kind == LLMErrorKind.RATE_LIMIT

    @pytest.mark.parametrize("message", ["timeout reached", "Request timed out", "调用超时"])
    def test_substring_timeout(self, message: str) -> None:
        assert classify_exception(Exception(message)).kind == LLMErrorKind.TIMEOUT

    def test_data_inspection_failed_bucket(self) -> None:
        result = classify_exception(Exception("DataInspectionFailed: blocked content"))
        assert result.kind == LLMErrorKind.CONTENT_INSPECTION_FAILED

    def test_content_filter_distinct_from_inspection(self) -> None:
        result = classify_exception(Exception("response blocked by safety filter"))
        assert result.kind == LLMErrorKind.CONTENT_FILTER

    def test_unknown_message_falls_back(self) -> None:
        result = classify_exception(Exception("some random bug"))
        assert result.kind == LLMErrorKind.UNKNOWN
        assert result.retryable is False


class TestClassifyProviderPayload:
    def test_status_only(self) -> None:
        result = classify_provider_payload(status_code=429, message="busy")
        assert result.kind == LLMErrorKind.RATE_LIMIT

    def test_provider_code_1302_is_rate_limit(self) -> None:
        # Tencent / DashScope-style "speed limit" body code.
        result = classify_provider_payload(status_code=200, code="1302", message="busy")
        assert result.kind == LLMErrorKind.RATE_LIMIT
        assert result.provider_code == "1302"

    def test_safety_filter_in_message(self) -> None:
        result = classify_provider_payload(
            status_code=200,
            code=None,
            message="prompt blocked by safety filter",
        )
        assert result.kind == LLMErrorKind.CONTENT_FILTER

    def test_invalid_parameter_400(self) -> None:
        assert (
            classify_provider_payload(status_code=400, message="missing required arg").kind
            == LLMErrorKind.INVALID_PARAMETER
        )

    def test_none_status_with_unknown_message_falls_back(self) -> None:
        assert (
            classify_provider_payload(status_code=None, message="¯\\_(ツ)_/¯").kind
            == LLMErrorKind.UNKNOWN
        )


class TestIsRateLimitException:
    def test_returns_true_for_429(self) -> None:
        assert is_rate_limit_exception(_FakeHTTPError("x", status_code=429)) is True

    def test_returns_false_for_unknown(self) -> None:
        assert is_rate_limit_exception(Exception("oops")) is False


def test_classified_error_is_immutable() -> None:
    err = ClassifiedError(
        kind=LLMErrorKind.RATE_LIMIT,
        status_code=429,
        provider_code=None,
        raw_message="x",
    )
    with pytest.raises(Exception):  # frozen dataclass
        err.kind = LLMErrorKind.AUTH  # type: ignore[misc]
