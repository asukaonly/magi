"""Logging sanitization helpers for provider bridge requests and responses."""

from __future__ import annotations

import json
import logging
from typing import Any
import uuid

from ...utils.diagnostic_logging import full_content_logging_enabled
from ...utils.llm_logger import _omit_binary_log_payloads, get_llm_logger
from ...utils.log_redaction import redact_log_value
from ..base import LLMAdapter
from .models import ProviderResponse


class RawProviderResponseLogger:
    """Record SDK responses before parsing, without changing response objects."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        event_context: dict[str, Any] | None,
    ) -> None:
        context = event_context or {}
        capture_id = uuid.uuid4().hex
        self._request_id = str(context.get("request_id") or capture_id)
        self._metadata = {
            "capture_id": capture_id,
            "request_id": self._request_id,
            "provider": llm_adapter.provider_name,
            "model": llm_adapter.model_name,
            **{
                key: context[key]
                for key in ("request_kind", "session_id", "turn_id", "trace_id", "span_id")
                if context.get(key) is not None
            },
        }
        self._chunk_index = 0

    def log_response(self, response: Any) -> None:
        """Log one complete SDK response before provider normalization."""
        self._write("LLM_RAW_RESPONSE", response)

    def log_chunk(self, chunk: Any) -> None:
        """Log an ordered SDK stream event before text/reasoning separation."""
        self._write("LLM_RAW_CHUNK", chunk, chunk_index=self._chunk_index)
        self._chunk_index += 1

    def _write(self, event: str, response: Any, **extra: Any) -> None:
        logger = get_llm_logger("provider")
        if not full_content_logging_enabled() or not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            payload = {
                **self._metadata,
                **extra,
                "capture_stage": "sdk_before_normalization",
                "response_type": type(response).__name__,
                "raw_response": _omit_binary_log_payloads(redact_log_value(response)),
            }
            logger.debug(
                "%s [%s] %s",
                event,
                self._request_id,
                json.dumps(redact_log_value(payload), ensure_ascii=False),
            )
        except Exception as exc:
            # Diagnostics must not fail an otherwise successful provider call.
            logger.warning("LLM raw response logging failed: %s", type(exc).__name__)


def is_provider_test_event(event_context: dict[str, Any] | None) -> bool:
    return (event_context or {}).get("surface") == "config_provider_test"


def build_provider_test_log_context(
    llm_adapter: LLMAdapter,
    event_context: dict[str, Any] | None,
    **extra: Any,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "provider_name": str(getattr(llm_adapter, "provider_name", "unknown")),
        "model": str(getattr(llm_adapter, "model_name", "unknown")),
        "base_url": getattr(llm_adapter, "base_url", None),
    }
    if event_context:
        context["event_context"] = sanitize_log_value(event_context)
    for key, value in extra.items():
        context[key] = sanitize_log_value(value)
    return context


def extract_provider_error_details(exc: Exception) -> dict[str, Any]:
    details: dict[str, Any] = {
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr_name in ("status_code", "request_id", "body", "code", "param", "type"):
        attr_value = getattr(exc, attr_name, None)
        if attr_value is not None:
            details[attr_name] = sanitize_log_value(attr_value)
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            details["response_headers"] = sanitize_log_value(dict(headers))
    request = getattr(exc, "request", None)
    if request is not None:
        details["request_method"] = getattr(request, "method", None)
        details["request_url"] = str(getattr(request, "url", "")) or None
    return details


def truncate_provider_response(provider_response: ProviderResponse) -> dict[str, Any]:
    return {
        "content": provider_response.content[:200],
        "tool_calls": [
            {
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": sanitize_log_value(tool_call.arguments),
            }
            for tool_call in provider_response.tool_calls or []
        ],
        "assistant_message": sanitize_log_value(provider_response.assistant_message),
        "metadata": sanitize_log_value(provider_response.metadata),
        "usage": sanitize_log_value(provider_response.usage),
    }


def summarize_raw_provider_response(response: Any) -> dict[str, Any]:
    return {
        "response_type": type(response).__name__,
        "raw_response": truncate_log_value(sanitize_log_value(response)),
    }


def sanitize_log_value(value: Any) -> Any:
    """Sanitize provider diagnostics through the shared logging boundary."""
    return redact_log_value(value)


def truncate_log_value(value: Any, *, max_string_length: int = 500, max_items: int = 20) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:max_string_length]
    if isinstance(value, list):
        return [
            truncate_log_value(item, max_string_length=max_string_length, max_items=max_items)
            for item in value[:max_items]
        ]
    if isinstance(value, dict):
        truncated: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                truncated["__truncated_items__"] = len(value) - max_items
                break
            truncated[str(key)] = truncate_log_value(
                item,
                max_string_length=max_string_length,
                max_items=max_items,
            )
        return truncated
    if hasattr(value, "model_dump"):
        try:
            return truncate_log_value(
                value.model_dump(),
                max_string_length=max_string_length,
                max_items=max_items,
            )
        except Exception:
            return repr(value)[:max_string_length]
    return repr(value)[:max_string_length]
