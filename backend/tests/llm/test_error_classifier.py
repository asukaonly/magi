"""Provider error classification and retry decisions at both public entry points."""

from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from magi.llm.error_classifier import (
    LLMErrorKind,
    classify_exception,
    classify_provider_payload,
    is_rate_limit_exception,
)


@pytest.mark.parametrize(
    "status,message,kind,retryable",
    [
        (429, "nope", LLMErrorKind.RATE_LIMIT, True),
        (401, "unauthorized", LLMErrorKind.AUTH, False),
        (403, "x", LLMErrorKind.AUTH, False),
        (500, "x", LLMErrorKind.SERVICE_UNAVAILABLE, True),
        (502, "x", LLMErrorKind.SERVICE_UNAVAILABLE, True),
        (503, "x", LLMErrorKind.SERVICE_UNAVAILABLE, True),
        (529, "overloaded", LLMErrorKind.SERVICE_UNAVAILABLE, True),
        (504, "gateway timeout", LLMErrorKind.TIMEOUT, True),
        (None, "rate limit exceeded", LLMErrorKind.RATE_LIMIT, True),
        (None, "Too many requests, slow down", LLMErrorKind.RATE_LIMIT, True),
        (None, "ratelimit hit", LLMErrorKind.RATE_LIMIT, True),
        (None, "上游返回 速率限制", LLMErrorKind.RATE_LIMIT, True),
        (None, "请求过于频繁", LLMErrorKind.RATE_LIMIT, True),
        (None, "Quota exceeded for project", LLMErrorKind.RATE_LIMIT, True),
        (None, "timeout reached", LLMErrorKind.TIMEOUT, True),
        (None, "Request timed out", LLMErrorKind.TIMEOUT, True),
        (None, "调用超时", LLMErrorKind.TIMEOUT, True),
        (
            429,
            "DataInspectionFailed: blocked content",
            LLMErrorKind.CONTENT_INSPECTION_FAILED,
            False,
        ),
        (429, "response blocked by safety filter", LLMErrorKind.CONTENT_FILTER, False),
        (None, "some random bug", LLMErrorKind.UNKNOWN, False),
    ],
)
def test_exception_classification_preserves_retry_policy_and_source(
    status, message, kind, retryable
):
    error = RuntimeError(message)
    if status is not None:
        error.status_code = status
    result = classify_exception(error)
    assert result.kind == kind
    assert result.retryable is retryable
    assert result.status_code == status
    assert result.raw_message == message
    assert result.provider_code is None
    assert is_rate_limit_exception(error) is (kind == LLMErrorKind.RATE_LIMIT)


@pytest.mark.parametrize(
    "direct,nested,expected", [(None, 429, LLMErrorKind.RATE_LIMIT), (401, 429, LLMErrorKind.AUTH)]
)
def test_exception_status_prefers_direct_then_response(direct, nested, expected):
    error = RuntimeError("Upstream error")
    error.status_code = direct
    error.response = SimpleNamespace(status_code=nested)
    result = classify_exception(error)
    assert result.kind == expected
    assert result.status_code == (nested if direct is None else direct)


@pytest.mark.parametrize(
    "status,code,message,kind,retryable",
    [
        (429, None, "busy", LLMErrorKind.RATE_LIMIT, True),
        (200, "1302", "busy", LLMErrorKind.RATE_LIMIT, True),
        (200, None, "prompt blocked by safety filter", LLMErrorKind.CONTENT_FILTER, False),
        (400, None, "missing required arg", LLMErrorKind.INVALID_PARAMETER, False),
        (None, None, "unrecognized failure", LLMErrorKind.UNKNOWN, False),
    ],
)
def test_provider_payload_classification_preserves_diagnostics(
    status, code, message, kind, retryable
):
    result = classify_provider_payload(status_code=status, code=code, message=message)
    assert result.kind == kind
    assert result.retryable is retryable
    assert result.status_code == status
    assert result.provider_code == code
    assert result.raw_message == message


@pytest.mark.parametrize(
    "error,kind",
    [
        (TimeoutError(), LLMErrorKind.TIMEOUT),
        (ConnectionResetError("peer closed"), LLMErrorKind.SERVICE_UNAVAILABLE),
        (httpx.ReadTimeout("read interrupted"), LLMErrorKind.TIMEOUT),
        (httpx.ConnectError("network unreachable"), LLMErrorKind.SERVICE_UNAVAILABLE),
        (httpx.RemoteProtocolError("peer closed"), LLMErrorKind.SERVICE_UNAVAILABLE),
        (httpx.LocalProtocolError("bad request headers"), LLMErrorKind.INVALID_PARAMETER),
        (httpx.UnsupportedProtocol("unsupported scheme"), LLMErrorKind.UNKNOWN),
        (
            openai.APIConnectionError(request=httpx.Request("POST", "https://test.invalid")),
            LLMErrorKind.SERVICE_UNAVAILABLE,
        ),
        (
            openai.APITimeoutError(request=httpx.Request("POST", "https://test.invalid")),
            LLMErrorKind.TIMEOUT,
        ),
        (
            anthropic.APIConnectionError(request=httpx.Request("POST", "https://test.invalid")),
            LLMErrorKind.SERVICE_UNAVAILABLE,
        ),
        (
            anthropic.APITimeoutError(request=httpx.Request("POST", "https://test.invalid")),
            LLMErrorKind.TIMEOUT,
        ),
    ],
)
def test_typed_transport_failures_do_not_depend_on_message_words(error, kind):
    classified = classify_exception(error)
    assert classified.kind is kind
    assert classified.retryable is (kind in {LLMErrorKind.TIMEOUT, LLMErrorKind.SERVICE_UNAVAILABLE})
