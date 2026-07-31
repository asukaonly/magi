"""Logging sanitization helpers for provider bridge requests and responses."""

from __future__ import annotations

from typing import Any

from ...utils.log_redaction import redact_log_value
from ..base import LLMAdapter
from .models import ProviderResponse


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
