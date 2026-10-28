"""Failures keep SDK diagnostics at the shared LLM boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from anthropic import BadRequestError as AnthropicBadRequestError
from openai import BadRequestError

from magi.llm.provider_bridge import LLMProviderBridge
from magi.llm.provider_bridge import logging as provider_logging


def _error(protocol="openai"):
    body = {
        "error": {
            "code": "data_inspection_failed",
            "message": "Input text data may contain inappropriate content.",
        },
        "request_id": "provider-body-id",
        "authorization": "Bearer test-secret",
        "audio": {"data": "binary-payload"},
    }
    response = httpx.Response(
        400, json=body, headers={"x-request-id": "provider-header-id"},
        request=httpx.Request("POST", "https://provider.invalid/chat"),
    )
    error_class = AnthropicBadRequestError if protocol == "anthropic" else BadRequestError
    return error_class(f"Error code: 400 - {body}", response=response, body=body)


@pytest.fixture
def failure_logs(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(provider_logging, "logger", logger)
    monkeypatch.setattr(provider_logging, "full_content_logging_enabled", lambda: True)
    return logger


def _bridge(exc, protocol="openai"):
    create = AsyncMock(side_effect=exc)
    adapter = SimpleNamespace(
        provider_name=protocol, model_name="diagnostic-model", base_url=None,
        _client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            messages=SimpleNamespace(create=create),
        ),
    )
    bridge = LLMProviderBridge(adapter)
    bridge.is_anthropic = lambda: protocol == "anthropic"
    bridge._operations._apply_provider_options = lambda kwargs, _: kwargs
    bridge._operations._emit_usage_event = AsyncMock()
    return bridge


async def _invoke(bridge, operation, **context):
    kwargs = {
        "system_prompt": "private-system-input",
        "messages": [{"role": "user", "content": "private-user-input"}],
        "event_context": {"request_id": "local-call-id", "request_kind": "test", **context},
    }
    if operation == "chat_stream":
        async for _ in bridge.chat_response_stream(**kwargs):
            pass
    elif operation == "chat":
        await bridge.chat_response(**kwargs)
    else:
        await getattr(bridge, operation)(**kwargs, tools=[])


@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "operation", ["chat", "chat_stream", "chat_with_tools", "chat_with_tools_stream"],
)
@pytest.mark.parametrize("surface", [None, "config_provider_test"])
async def test_failed_sdk_call_is_logged_once_with_original_exception(
    failure_logs, protocol, operation, surface,
):
    exc = _error(protocol)
    bridge = _bridge(exc, protocol)
    with pytest.raises(type(exc)) as caught:
        await _invoke(bridge, operation, surface=surface)
    assert caught.value is exc
    failure_logs.error.assert_called_once()
    event, = failure_logs.error.call_args.args
    fields = failure_logs.error.call_args.kwargs
    assert event == "LLM provider call failed"
    assert fields["operation"] == operation
    assert fields["provider"] == protocol
    assert fields["model"] == "diagnostic-model"
    assert fields["request_id"] == "local-call-id"
    assert fields["provider_request_id"] == "provider-header-id"
    assert fields["status_code"] == 400
    assert fields["error_kind"] == "content_inspection_failed"
    assert fields["provider_code"] == "data_inspection_failed"
    assert fields["retryable"] is False
    assert fields["provider_error"]["body"]["error"] == exc.body["error"]
    assert fields["provider_error"]["body"]["authorization"] == "[REDACTED]"
    assert "binary-payload" not in str(fields)
    assert "private-user-input" not in str(fields)
    assert "private-system-input" not in str(fields)
    assert exc.body["authorization"] == "Bearer test-secret"
    bridge._operations._emit_usage_event.assert_awaited_once()
    assert bridge._operations._emit_usage_event.await_args.kwargs["success"] is False


async def test_adapter_tool_delegation_does_not_duplicate_failure(failure_logs):
    exc = _error()
    bridge = _bridge(exc)
    bridge.llm._client = None
    bridge.llm.chat = AsyncMock(side_effect=exc)
    with pytest.raises(BadRequestError):
        await _invoke(bridge, "chat_with_tools")
    failure_logs.error.assert_called_once()
    bridge._operations._emit_usage_event.assert_awaited_once()


@pytest.mark.parametrize("operation", ["chat_stream", "chat_with_tools_stream"])
async def test_error_after_stream_started_is_logged(failure_logs, operation):
    exc = _error()

    async def stream():
        yield SimpleNamespace(choices=[], usage=None)
        raise exc

    bridge = _bridge(None)
    bridge.llm._client.chat.completions.create.return_value = stream()
    with pytest.raises(BadRequestError) as caught:
        await _invoke(bridge, operation)
    assert caught.value is exc
    failure_logs.error.assert_called_once()


async def test_metadata_survives_disabled_full_content_logging(failure_logs, monkeypatch):
    monkeypatch.setattr(provider_logging, "full_content_logging_enabled", lambda: False)
    bridge = _bridge(_error())
    with pytest.raises(BadRequestError):
        await _invoke(bridge, "chat")
    fields = failure_logs.error.call_args.kwargs
    assert fields["provider_code"] == "data_inspection_failed"
    assert fields["provider_request_id"] == "provider-header-id"
    assert "provider_error" not in fields
    assert "Input text" not in str(fields)


async def test_body_request_id_is_used_when_header_is_absent(failure_logs):
    exc = _error()
    exc.request_id = None
    exc.response.headers.clear()
    with pytest.raises(BadRequestError):
        await _invoke(_bridge(exc), "chat")
    assert failure_logs.error.call_args.kwargs["provider_request_id"] == "provider-body-id"


async def test_logging_failure_does_not_replace_provider_exception(failure_logs, monkeypatch):
    exc = _error()
    monkeypatch.setattr(
        provider_logging, "extract_provider_error_details", Mock(side_effect=ValueError("bad data")),
    )
    with pytest.raises(BadRequestError) as caught:
        await _invoke(_bridge(exc), "chat")
    assert caught.value is exc
    failure_logs.warning.assert_called_once_with(
        "LLM provider error logging failed", error_type="ValueError",
    )


@pytest.mark.parametrize(
    "operation", ["chat", "chat_stream", "chat_with_tools", "chat_with_tools_stream"],
)
async def test_cancellation_is_not_a_provider_failure(failure_logs, operation):
    with pytest.raises(asyncio.CancelledError):
        await _invoke(_bridge(asyncio.CancelledError()), operation)
    failure_logs.error.assert_not_called()
    failure_logs.warning.assert_not_called()


async def test_transient_error_is_logged_with_retryability(failure_logs):
    with pytest.raises(TimeoutError):
        await _invoke(_bridge(TimeoutError("timed out")), "chat")
    failure_logs.warning.assert_called_once()
    assert failure_logs.warning.call_args.kwargs["retryable"] is True
    assert failure_logs.warning.call_args.kwargs["error_kind"] == "timeout"
