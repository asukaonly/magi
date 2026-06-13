"""Response conversion and usage helpers for provider bridge calls."""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from typing import Any

from ..parsers import parse_legacy_tool_calls, sanitize_llm_text
from .models import ProviderResponse, ProviderToolCall, ProviderUsage
from ...config.models import ThinkingDepth

logger = logging.getLogger(__name__)


def _nested_int(obj: Any, outer: str, inner: str) -> int:
    """Read an int from a nested SDK usage detail (e.g. usage.prompt_tokens_details.cached_tokens); 0 if absent/None."""
    container = getattr(obj, outer, None)
    if container is None:
        return 0
    return int(getattr(container, inner, 0) or 0)


class ProviderBridgeResponseMixin:
    """Normalize provider responses, content blocks, metadata, and usage events."""

    llm: Any

    def _provider_name(self) -> str:
        raise NotImplementedError

    @staticmethod
    def _openai_usage_to_wire(usage_data: Any) -> dict[str, int] | None:
        if usage_data is None:
            return None
        return {
            "prompt_tokens": int(getattr(usage_data, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage_data, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_data, "total_tokens", 0) or 0),
            "reasoning_tokens": int(getattr(usage_data, "reasoning_tokens", 0) or 0),
        }

    @staticmethod
    def _anthropic_usage_to_wire(usage_data: Any) -> dict[str, int] | None:
        if usage_data is None:
            return None
        prompt_tokens = int(getattr(usage_data, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_data, "output_tokens", 0) or 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    def _extract_anthropic_stream_usage(self, stream: Any, usage_data: Any) -> ProviderUsage | None:
        """Extract usage from Anthropic streaming events."""
        final_message = (
            getattr(stream, "final_message", None) if hasattr(stream, "final_message") else None
        )
        if final_message is not None:
            return self._extract_anthropic_usage(final_message)
        if usage_data is None:
            return None
        input_tokens = int(getattr(usage_data, "input_tokens", 0) or 0)
        cache_read_tokens = int(getattr(usage_data, "cache_read_input_tokens", 0) or 0)
        cache_write_tokens = int(getattr(usage_data, "cache_creation_input_tokens", 0) or 0)
        prompt_tokens = input_tokens + cache_read_tokens + cache_write_tokens
        completion_tokens = int(getattr(usage_data, "output_tokens", 0) or 0)
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            reasoning_tokens=0,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    @staticmethod
    def _extract_openai_stream_usage(usage_data: Any) -> ProviderUsage | None:
        if usage_data is None:
            return None
        return ProviderUsage(
            prompt_tokens=int(getattr(usage_data, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage_data, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage_data, "total_tokens", 0) or 0),
            reasoning_tokens=_nested_int(usage_data, "completion_tokens_details", "reasoning_tokens"),
            cache_read_tokens=_nested_int(usage_data, "prompt_tokens_details", "cached_tokens"),
            cache_write_tokens=0,
        )

    def _convert_messages_to_anthropic(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.get("tool_call_id"),
                                "content": message.get("content", ""),
                            }
                        ],
                    }
                )
            elif message.get("role") == "user" and isinstance(message.get("content"), list):
                converted.append(
                    {
                        "role": "user",
                        "content": self._convert_content_blocks_to_anthropic(message["content"]),
                    }
                )
            elif message.get("role") == "assistant" and isinstance(message.get("content"), list):
                converted.append({"role": "assistant", "content": message["content"]})
            else:
                converted.append(
                    {
                        "role": message.get("role"),
                        "content": message.get("content", ""),
                    }
                )
        return converted

    def _convert_messages_to_openai(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "user" and isinstance(message.get("content"), list):
                converted.append(
                    {
                        "role": "user",
                        "content": self._convert_content_blocks_to_openai(message["content"]),
                    }
                )
                continue
            converted.append(dict(message))
        return converted

    @staticmethod
    def _convert_content_blocks_to_openai(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for block in blocks:
            block_type = str(block.get("type") or "").strip()
            if block_type == "text":
                converted.append({"type": "text", "text": str(block.get("text") or "")})
                continue
            if block_type == "image":
                mime_type = str(block.get("mime_type") or "image/png").strip() or "image/png"
                data = str(block.get("data") or "").strip()
                converted.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{data}",
                        },
                    }
                )
                continue
            converted.append(dict(block))
        return converted

    @staticmethod
    def _convert_content_blocks_to_anthropic(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for block in blocks:
            block_type = str(block.get("type") or "").strip()
            if block_type == "text":
                converted.append({"type": "text", "text": str(block.get("text") or "")})
                continue
            if block_type == "image":
                mime_type = str(block.get("mime_type") or "image/png").strip() or "image/png"
                data = str(block.get("data") or "").strip()
                converted.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": data,
                        },
                    }
                )
                continue
            converted.append(dict(block))
        return converted

    def _parse_anthropic_response(self, response: Any) -> ProviderResponse:
        tool_calls: list[ProviderToolCall] = []
        content_text_parts: list[str] = []
        assistant_blocks: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text_value = block.text or ""
                content_text_parts.append(text_value)
                assistant_blocks.append({"type": "text", "text": text_value})
            elif block.type == "tool_use":
                tool_calls.append(
                    ProviderToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        if tool_calls:
            return ProviderResponse(
                tool_calls=tool_calls,
                assistant_message={"role": "assistant", "content": assistant_blocks},
                usage=self._extract_anthropic_usage(response),
            )
        provider_response = self._build_content_response("".join(content_text_parts))
        provider_response.usage = self._extract_anthropic_usage(response)
        return provider_response

    def _parse_openai_response(self, response: Any) -> ProviderResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ProviderToolCall] = []
        raw_tool_calls: list[dict[str, Any]] = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tool_call in message.tool_calls:
                arguments: dict[str, Any] = {}
                if tool_call.function.arguments:
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": tool_call.function.arguments}

                tool_calls.append(
                    ProviderToolCall(
                        id=tool_call.id,
                        name=tool_call.function.name,
                        arguments=arguments,
                    )
                )
                raw_tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments or "{}",
                        },
                    }
                )

        if tool_calls:
            return ProviderResponse(
                tool_calls=tool_calls,
                assistant_message={
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": raw_tool_calls,
                },
                metadata=self._build_openai_metadata(choice, message, raw_tool_calls),
                usage=self._extract_openai_usage(response),
            )

        provider_response = self._build_content_response(message.content or "")
        provider_response.metadata = self._build_openai_metadata(choice, message, raw_tool_calls)
        provider_response.usage = self._extract_openai_usage(response)
        return provider_response

    def _build_openai_metadata(
        self,
        choice: Any,
        message: Any,
        raw_tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "provider": self._provider_name() or type(self.llm).__name__,
            "model": getattr(self.llm, "model_name", "unknown"),
            "finish_reason": getattr(choice, "finish_reason", None),
            "tool_call_count": len(raw_tool_calls),
            "has_content": bool(getattr(message, "content", None)),
        }
        if hasattr(message, "model_dump"):
            try:
                dumped = message.model_dump()
                metadata["raw_message"] = dumped
            except Exception:
                pass
        else:
            metadata["raw_message"] = {
                "role": getattr(message, "role", None),
                "content": getattr(message, "content", None),
                "tool_calls": raw_tool_calls or None,
            }
        return metadata

    def normalize_content_response(self, content: Any) -> ProviderResponse:
        """Normalize plain text content into ProviderResponse with legacy parsing fallback."""
        return self._build_content_response(content)

    def _build_content_response(self, content: Any) -> ProviderResponse:
        """Build provider response from plain text content with legacy tool-call fallback."""
        raw_content = content if isinstance(content, str) else str(content or "")
        normalized_content = sanitize_llm_text(raw_content)
        parsed_tool_calls = [
            ProviderToolCall(
                id=parsed_call.id,
                name=parsed_call.name,
                arguments=parsed_call.arguments,
            )
            for parsed_call in parse_legacy_tool_calls(raw_content)
        ]
        if parsed_tool_calls:
            return ProviderResponse(
                content=normalized_content,
                tool_calls=parsed_tool_calls,
                assistant_message={
                    "role": "assistant",
                    "content": normalized_content,
                },
            )
        return ProviderResponse(content=normalized_content)

    @staticmethod
    def _extract_openai_usage(response: Any) -> ProviderUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        return ProviderUsage(
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            reasoning_tokens=_nested_int(usage, "completion_tokens_details", "reasoning_tokens"),
            cache_read_tokens=_nested_int(usage, "prompt_tokens_details", "cached_tokens"),
            cache_write_tokens=0,
        )

    @staticmethod
    def _extract_anthropic_usage(response: Any) -> ProviderUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write_tokens = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        prompt_tokens = input_tokens + cache_read_tokens + cache_write_tokens
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            reasoning_tokens=0,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    def _attach_trace_metrics(
        self,
        *,
        provider_response: ProviderResponse,
        usage: ProviderUsage | None,
        latency_ms: int,
        thinking_depth: ThinkingDepth,
        disable_thinking: bool | None = None,
    ) -> None:
        metadata = dict(provider_response.metadata or {})
        metadata["trace_metrics"] = {
            "provider": self._provider_name() or type(self.llm).__name__,
            "model": str(getattr(self.llm, "model_name", "unknown")),
            "input_tokens": int(usage.prompt_tokens if usage else 0),
            "output_tokens": int(usage.completion_tokens if usage else 0),
            "total_tokens": int(usage.total_tokens if usage else 0),
            "reasoning_tokens": int(usage.reasoning_tokens if usage else 0),
            "cache_read_tokens": int(usage.cache_read_tokens if usage else 0),
            "cache_write_tokens": int(usage.cache_write_tokens if usage else 0),
            "thinking_enabled": thinking_depth != ThinkingDepth.NONE,
            "thinking_depth": thinking_depth.value,
            "duration_ms": int(latency_ms),
        }
        provider_response.metadata = metadata

    @staticmethod
    def _usage_int(usage: ProviderUsage | dict[str, Any] | None, *keys: str) -> int:
        if usage is None:
            return 0
        for key in keys:
            value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
            if value is None:
                continue
            if not isinstance(value, (int, float, str)):
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    async def _emit_usage_event(
        self,
        *,
        success: bool,
        latency_ms: int,
        usage: ProviderUsage | dict[str, Any] | None,
        event_context: dict[str, Any] | None,
        error: str | None = None,
    ) -> None:
        """Publish a SpanCompleted(node_type='llm_call') event for this LLM call."""
        from magi.runtime_trace.span_publisher import publish_trace_span, resolve_event_bus
        from magi.runtime_trace import enrich_event_context_with_turn_trace
        from magi.events.tracing import current_trace_context
        from magi.events.domain_payloads import ToolError

        context = enrich_event_context_with_turn_trace(event_context)
        request_id = str(context.get("request_id") or uuid.uuid4().hex[:8])
        provider = self._provider_name() or type(self.llm).__name__
        model = str(getattr(self.llm, "model_name", "unknown"))
        request_kind = str(context.get("request_kind") or "chat")

        prompt_tokens = self._usage_int(usage, "prompt_tokens", "input_tokens")
        completion_tokens = self._usage_int(usage, "completion_tokens", "output_tokens")
        total_tokens = self._usage_int(usage, "total_tokens") or prompt_tokens + completion_tokens
        reasoning_tokens = self._usage_int(usage, "reasoning_tokens")
        cache_read_tokens = self._usage_int(usage, "cache_read_tokens")
        cache_write_tokens = self._usage_int(usage, "cache_write_tokens")
        request_preview = (
            str(context.get("request_preview") or context.get("input_preview") or "").strip()
            or None
        )
        response_preview = (
            str(context.get("response_preview") or context.get("output_preview") or "").strip()
            or None
        )

        ended_at = time.time()
        started_at = ended_at - (latency_ms / 1000.0)
        started_at_ms = int(started_at * 1000)
        ended_at_ms = started_at_ms + int(latency_ms)

        error_obj = None
        if not success and error:
            error_obj = ToolError(type="LLMError", message=str(error)[:1000])

        ctx = current_trace_context()
        trace_id = ctx.trace_id if ctx is not None else str(context.get("trace_id") or "")
        parent_span_id = (
            ctx.span_id
            if ctx is not None
            else str(context.get("parent_span_id") or "").strip() or None
        )

        try:
            await publish_trace_span(
                event_bus=resolve_event_bus(fallback=None),
                node_type="llm_call",
                name=model,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                status="ok" if success else "error",
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                error=error_obj,
                turn_id=context.get("turn_id"),
                attributes={
                    "request_id": request_id,
                    "provider": provider,
                    "model": model,
                    "request_kind": request_kind,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "usage_available": usage is not None,
                    "request_preview": request_preview,
                    "response_preview": response_preview,
                    "input_preview": request_preview,
                    "output_preview": response_preview,
                    "correlation_id": context.get("correlation_id"),
                    "session_id": context.get("session_id"),
                    "turn_id": context.get("turn_id"),
                    "agent_id": context.get("agent_id"),
                },
            )
        except Exception:
            logger.exception("publish llm_call SpanCompleted failed")
