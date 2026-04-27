"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
import time
import uuid
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from .base import LLMAdapter
from .anthropic import AnthropicAdapter
from .concurrency_limiter import LLMConcurrencyLimiter, get_llm_concurrency_limiter
from .parsers import parse_legacy_tool_calls, sanitize_llm_text
from .streaming_events import LLMStreamEvent, emit_stream_event
from .usage_events import LLMCallEventPayload, LLMUsageEventPublisher, publish_llm_call_event
from ..config import get_config
from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMProviderRegistryModel,
    find_chat_model_meta,
    load_llm_provider_registry,
)
from ..config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS
from ..config.models import ThinkingDepth
from ..core.logger import get_logger


logger = get_logger(__name__)


_SENSITIVE_LOG_FIELD_PATTERNS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "credential",
    "private",
    "authorization",
)


def _is_sensitive_log_field(field_name: str) -> bool:
    field_lower = field_name.lower()
    return any(pattern in field_lower for pattern in _SENSITIVE_LOG_FIELD_PATTERNS)


def _sanitize_log_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_sanitize_log_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: ("***MASKED***" if _is_sensitive_log_field(str(key)) else _sanitize_log_value(item))
            for key, item in value.items()
        }
    if hasattr(value, "model_dump"):
        return _sanitize_log_value(value.model_dump())
    if hasattr(value, "__dict__"):
        return _sanitize_log_value(vars(value))
    return str(value)


def _is_provider_test_event(event_context: Optional[Dict[str, Any]]) -> bool:
    return (event_context or {}).get("surface") == "config_provider_test"


def _build_provider_test_log_context(
    llm_adapter: LLMAdapter,
    event_context: Optional[Dict[str, Any]],
    **extra: Any,
) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "provider_name": str(getattr(llm_adapter, "provider_name", "unknown")),
        "model": str(getattr(llm_adapter, "model_name", "unknown")),
        "base_url": getattr(llm_adapter, "base_url", None),
    }
    if event_context:
        context["event_context"] = _sanitize_log_value(event_context)
    for key, value in extra.items():
        context[key] = _sanitize_log_value(value)
    return context


def _extract_provider_error_details(exc: Exception) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }
    for attr_name in ("status_code", "request_id", "body", "code", "param", "type"):
        attr_value = getattr(exc, attr_name, None)
        if attr_value is not None:
            details[attr_name] = _sanitize_log_value(attr_value)
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            details["response_headers"] = _sanitize_log_value(dict(headers))
    request = getattr(exc, "request", None)
    if request is not None:
        details["request_method"] = getattr(request, "method", None)
        details["request_url"] = str(getattr(request, "url", "")) or None
    return details


def _truncate_provider_response(provider_response: "ProviderResponse") -> Dict[str, Any]:
    return {
        "content": provider_response.content[:200],
        "tool_calls": [
            {
                "id": tool_call.id,
                "name": tool_call.name,
                "arguments": _sanitize_log_value(tool_call.arguments),
            }
            for tool_call in provider_response.tool_calls
        ],
        "assistant_message": _sanitize_log_value(provider_response.assistant_message),
        "metadata": _sanitize_log_value(provider_response.metadata),
        "usage": _sanitize_log_value(provider_response.usage),
    }


def _truncate_log_value(value: Any, *, max_string_length: int = 500, max_items: int = 20) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return value[:max_string_length]
    if isinstance(value, list):
        return [_truncate_log_value(item, max_string_length=max_string_length, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        truncated: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                truncated["__truncated_items__"] = len(value) - max_items
                break
            truncated[str(key)] = _truncate_log_value(item, max_string_length=max_string_length, max_items=max_items)
        return truncated
    if hasattr(value, "model_dump"):
        try:
            return _truncate_log_value(value.model_dump(), max_string_length=max_string_length, max_items=max_items)
        except Exception:
            return repr(value)[:max_string_length]
    return repr(value)[:max_string_length]


def _summarize_raw_provider_response(response: Any) -> Dict[str, Any]:
    return {
        "response_type": type(response).__name__,
        "raw_response": _truncate_log_value(_sanitize_log_value(response)),
    }


def _coerce_thinking_depth(
    thinking_depth: ThinkingDepth | None,
    disable_thinking: bool | None,
) -> ThinkingDepth:
    """Resolve a ThinkingDepth from the new or legacy parameter.

    If the caller passed an explicit ``thinking_depth``, use it directly.
    Otherwise fall back to the legacy ``disable_thinking`` boolean:
    ``True`` → NONE, ``False`` / ``None`` → MEDIUM.
    """
    if thinking_depth is not None:
        return thinking_depth
    if disable_thinking is True:
        return ThinkingDepth.NONE
    return ThinkingDepth.MEDIUM


@dataclass
class ProviderToolCall:
    """Normalized tool call returned by a provider."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ProviderResponse:
    """Normalized response returned by a provider."""
    content: str = ""
    tool_calls: List[ProviderToolCall] = None
    assistant_message: Dict[str, Any] | None = None
    metadata: Dict[str, Any] | None = None
    usage: "ProviderUsage | None" = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ProviderUsage:
    """Normalized token usage returned by a provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ToolStreamResult:
    """Result of a streaming tool-call LLM invocation.

    Collects text chunks emitted so far and any tool_calls detected.
    The caller inspects ``has_tool_calls`` after iteration to decide
    whether to proceed with tool execution or treat the streamed text
    as the final response.
    """

    provider_response: ProviderResponse
    text_chunks_emitted: int = 0
    has_tool_calls: bool = False


DEFAULT_CHAT_CONCURRENCY_FALLBACK = 4


class _ThinkTagScrubber:
    """Strip ``<think>...</think>`` blocks from streaming text content.

    Some OpenAI-compatible providers occasionally embed reasoning into
    ``delta.content`` rather than the dedicated ``reasoning_content``
    channel, which causes the thinking text to leak into the assistant
    bubble. Tags can span chunk boundaries, so this helper keeps a
    small carry-over buffer between ``feed`` calls.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Process ``chunk`` and return ``(visible_text, reasoning_text)``."""
        if not chunk:
            return "", ""
        text = self._pending + chunk
        self._pending = ""
        visible: list[str] = []
        reasoning: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if self._inside:
                close_idx = text.find(self.CLOSE, i)
                if close_idx == -1:
                    tail = len(self.CLOSE) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        reasoning.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if close_idx > i:
                    reasoning.append(text[i:close_idx])
                i = close_idx + len(self.CLOSE)
                self._inside = False
            else:
                open_idx = text.find(self.OPEN, i)
                if open_idx == -1:
                    tail = len(self.OPEN) - 1
                    if n - i <= tail:
                        self._pending = text[i:]
                        i = n
                    else:
                        safe_end = n - tail
                        visible.append(text[i:safe_end])
                        self._pending = text[safe_end:]
                        i = n
                    break
                if open_idx > i:
                    visible.append(text[i:open_idx])
                i = open_idx + len(self.OPEN)
                self._inside = True
        return "".join(visible), "".join(reasoning)

    def flush(self) -> tuple[str, str]:
        """Return any leftover buffered text when the stream ends."""
        if not self._pending:
            return "", ""
        leftover = self._pending
        self._pending = ""
        if self._inside:
            return "", leftover
        return leftover, ""


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    """Load the packaged LLM provider registry once per process."""
    return load_llm_provider_registry(
        get_llm_provider_registry_file(),
        fallback=LLMProviderRegistryModel(),
    )


class LLMProviderBridge:
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        usage_event_publisher: LLMUsageEventPublisher | None = None,
        concurrency_limiter: LLMConcurrencyLimiter | None = None,
    ):
        self.llm = llm_adapter
        self._usage_event_publisher = usage_event_publisher or getattr(
            llm_adapter,
            "_llm_usage_event_publisher",
            None,
        )
        self._concurrency_limiter = concurrency_limiter or get_llm_concurrency_limiter()

    def _provider_name(self) -> str:
        return (getattr(self.llm, "provider_name", "") or "").lower()

    def is_anthropic(self) -> bool:
        return isinstance(self.llm, AnthropicAdapter)

    def is_glm(self) -> bool:
        """Check if using GLM provider (including CodePlan)."""
        return self._provider_name() in ("glm", "glm_codeplan")

    @staticmethod
    def _disabled_thinking_extra_body(disable_thinking: bool | None) -> Dict[str, Any] | None:
        """Build provider-specific payload to disable reasoning/thinking mode.

        .. deprecated:: Use ``_build_glm_thinking_params`` with ThinkingDepth.
        """
        if disable_thinking is not True:
            return None
        return {"thinking": {"type": "disabled"}}

    # ------------------------------------------------------------------
    # Provider-specific thinking-depth helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_glm_thinking_params(depth: ThinkingDepth) -> Dict[str, Any] | None:
        """Build GLM extra_body payload for the requested thinking depth.

        GLM only supports a binary toggle: thinking enabled or disabled.
        """
        if depth == ThinkingDepth.NONE:
            return {"thinking": {"type": "disabled"}}
        return None  # GLM defaults to thinking enabled

    @staticmethod
    def _build_dashscope_thinking_params(depth: ThinkingDepth) -> Dict[str, Any]:
        """Build DashScope/Bailian extra_body payload for thinking control.

        DashScope uses ``enable_thinking`` boolean in extra_body.
        """
        if depth == ThinkingDepth.NONE:
            return {"enable_thinking": False}
        return {"enable_thinking": True}

    @staticmethod
    def _build_openai_reasoning_params(depth: ThinkingDepth) -> Dict[str, Any]:
        """Build OpenAI-compatible extra kwargs for reasoning effort."""
        mapping = {
            ThinkingDepth.NONE: "none",
            ThinkingDepth.LOW: "low",
            ThinkingDepth.MEDIUM: "medium",
            ThinkingDepth.HIGH: "high",
            ThinkingDepth.MAX: "high",
        }
        return {"reasoning_effort": mapping.get(depth, "medium")}

    @staticmethod
    def _build_anthropic_thinking_params(depth: ThinkingDepth) -> Dict[str, Any] | None:
        """Map ThinkingDepth to Anthropic extended thinking budget."""
        budget_map = {
            ThinkingDepth.NONE: None,
            ThinkingDepth.LOW: 2048,
            ThinkingDepth.MEDIUM: 8192,
            ThinkingDepth.HIGH: 16384,
            ThinkingDepth.MAX: 32768,
        }
        tokens = budget_map.get(depth)
        if tokens is None:
            return None
        return {"thinking": {"type": "enabled", "budget_tokens": tokens}}

    def _model_supports_reasoning(self) -> bool:
        """Check if the current model advertises reasoning capability."""
        model_meta = find_chat_model_meta(
            _load_provider_registry(),
            self._provider_name(),
            str(getattr(self.llm, "model_name", "unknown")),
        )
        if model_meta is not None:
            return model_meta.capabilities.reasoning
        return False

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Inject provider-specific parameters into LLM request kwargs.

        Single entry point for all provider-specific customization.
        Called once per LLM request, after base kwargs are assembled
        and before the API call is made.
        """
        provider = self._provider_name()

        if provider == "dashscope":
            extra_body = self._build_dashscope_thinking_params(thinking_depth)
            existing = kwargs.get("extra_body", {})
            kwargs["extra_body"] = {**existing, **extra_body}

        elif provider in ("glm", "glm_codeplan"):
            extra_body = self._build_glm_thinking_params(thinking_depth)
            if extra_body:
                existing = kwargs.get("extra_body", {})
                kwargs["extra_body"] = {**existing, **extra_body}

        elif self.is_anthropic():
            budget = self._build_anthropic_thinking_params(thinking_depth)
            if budget:
                kwargs.update(budget)

        elif self._model_supports_reasoning():
            kwargs.update(self._build_openai_reasoning_params(thinking_depth))

        return kwargs

    def _build_concurrency_key(self, request_family: str) -> str:
        base_url = getattr(self.llm, "base_url", None)
        return LLMConcurrencyLimiter.build_key(
            provider_name=self._provider_name(),
            model_name=str(getattr(self.llm, "model_name", "unknown")),
            request_family=request_family,
            base_url=base_url,
        )

    def _resolve_chat_concurrency_limit(self) -> int:
        """Resolve the effective concurrency cap for chat requests."""
        key = self._build_concurrency_key("chat")
        runtime_config = get_config()
        runtime_override = getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}
        override = runtime_override.get(key)
        if override is not None:
            override_limit = getattr(override, "max_concurrency", None)
            if override_limit is not None:
                return int(override_limit)

        model_meta = find_chat_model_meta(
            _load_provider_registry(),
            self._provider_name(),
            str(getattr(self.llm, "model_name", "unknown")),
        )
        if model_meta is not None and model_meta.limits.max_concurrency is not None:
            return int(model_meta.limits.max_concurrency)

        return DEFAULT_CHAT_CONCURRENCY_FALLBACK

    async def _run_with_concurrency_limit(
        self,
        *,
        request_family: str,
        operation: Callable[[], Awaitable[ProviderResponse]],
        limit: int | None = None,
    ) -> ProviderResponse:
        key = self._build_concurrency_key(request_family)
        return await self._concurrency_limiter.run_with_limit(key, operation, limit=limit)

    async def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> str:
        """
        Unified non-tool chat call with system prompt.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        response = await self.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            thinking_depth=depth,
        )
        return response.content

    async def chat_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ProviderResponse:
        """
        Unified plain-chat call that still returns normalized ProviderResponse.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        started_at = time.time()
        try:
            provider_response = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_response_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    json_mode=json_mode,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=event_context,
            )
            return provider_response
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
                error=str(exc),
            )
            raise

    async def chat_response_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        """Streaming variant of chat_response().

        Yields :class:`LLMStreamEvent` — one ``text_delta`` per visible
        text fragment, one ``reasoning_delta`` per thinking/reasoning
        fragment (GLM ``delta.reasoning_content`` or Anthropic
        ``thinking`` blocks), an optional final ``usage``, and a
        terminal ``done``. Each event is also forwarded to the
        contextual stream sink via :func:`emit_stream_event`.
        """
        depth = _coerce_thinking_depth(thinking_depth, None)
        if self.is_anthropic():
            api_messages = self._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": self.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": api_messages,
                "stream": True,
            }
            if timeout_seconds is not None:
                anthropic_kwargs["timeout"] = timeout_seconds
            anthropic_kwargs = self._apply_provider_options(anthropic_kwargs, depth)
            stream = await self.llm._client.messages.create(**anthropic_kwargs)
            in_thinking = False
            usage_data: Any = None
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    block_type = getattr(block, "type", None) if block is not None else None
                    in_thinking = block_type == "thinking"
                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, "type", None)
                    # Anthropic emits thinking via ``thinking_delta``
                    # with a ``thinking`` attribute, or as text inside
                    # a thinking content block.
                    if delta_type == "thinking_delta":
                        text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
                        if text:
                            ev = LLMStreamEvent(kind="reasoning_delta", text=text)
                            await emit_stream_event(ev)
                            yield ev
                    elif in_thinking and getattr(delta, "text", None):
                        ev = LLMStreamEvent(kind="reasoning_delta", text=delta.text)
                        await emit_stream_event(ev)
                        yield ev
                    elif getattr(delta, "text", None):
                        ev = LLMStreamEvent(kind="text_delta", text=delta.text)
                        await emit_stream_event(ev)
                        yield ev
                elif event_type == "content_block_stop":
                    in_thinking = False
                elif event_type == "message_delta":
                    usage_data = getattr(event, "usage", usage_data)
                elif event_type == "message_start":
                    msg = getattr(event, "message", None)
                    if msg is not None:
                        usage_data = getattr(msg, "usage", usage_data)
            usage_payload = self._anthropic_usage_to_wire(usage_data)
            if usage_payload is not None:
                usage_ev = LLMStreamEvent(kind="usage", usage=usage_payload)
                await emit_stream_event(usage_ev)
                yield usage_ev
        else:
            full_messages = [{"role": "system", "content": system_prompt}] + self._convert_messages_to_openai(messages)
            chat_kwargs: Dict[str, Any] = {
                "messages": full_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            if json_mode:
                chat_kwargs["response_format"] = {"type": "json_object"}
            if timeout_seconds is not None:
                chat_kwargs["timeout"] = timeout_seconds
            chat_kwargs = self._apply_provider_options(chat_kwargs, depth)
            if getattr(self.llm, "_client", None) is not None:
                chat_kwargs["model"] = self.llm.model_name
                stream = await self.llm._client.chat.completions.create(**chat_kwargs)
                usage_data: Any = None
                scrubber = _ThinkTagScrubber()
                async for chunk in stream:
                    if not getattr(chunk, "choices", None):
                        if hasattr(chunk, "usage") and chunk.usage is not None:
                            usage_data = chunk.usage
                        continue
                    delta = chunk.choices[0].delta
                    if delta is None:
                        continue
                    # GLM / DashScope-compatible reasoning fields.
                    reasoning_text = (
                        getattr(delta, "reasoning_content", None)
                        or getattr(delta, "reasoning", None)
                    )
                    if reasoning_text:
                        ev = LLMStreamEvent(kind="reasoning_delta", text=reasoning_text)
                        await emit_stream_event(ev)
                        yield ev
                    content = getattr(delta, "content", None)
                    if content:
                        visible, reasoning_leak = scrubber.feed(content)
                        if reasoning_leak:
                            ev = LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak)
                            await emit_stream_event(ev)
                            yield ev
                        if visible:
                            ev = LLMStreamEvent(kind="text_delta", text=visible)
                            await emit_stream_event(ev)
                            yield ev
                    if hasattr(chunk, "usage") and chunk.usage is not None:
                        usage_data = chunk.usage
                tail_visible, tail_reasoning = scrubber.flush()
                if tail_reasoning:
                    ev = LLMStreamEvent(kind="reasoning_delta", text=tail_reasoning)
                    await emit_stream_event(ev)
                    yield ev
                if tail_visible:
                    ev = LLMStreamEvent(kind="text_delta", text=tail_visible)
                    await emit_stream_event(ev)
                    yield ev
                usage_payload = self._openai_usage_to_wire(usage_data)
                if usage_payload is not None:
                    usage_ev = LLMStreamEvent(kind="usage", usage=usage_payload)
                    await emit_stream_event(usage_ev)
                    yield usage_ev
            else:
                content = await self.llm.chat(**chat_kwargs)
                if content:
                    scrubber = _ThinkTagScrubber()
                    visible, reasoning_leak = scrubber.feed(content)
                    tail_visible, tail_reasoning = scrubber.flush()
                    visible = visible + tail_visible
                    reasoning_leak = reasoning_leak + tail_reasoning
                    if reasoning_leak:
                        ev = LLMStreamEvent(kind="reasoning_delta", text=reasoning_leak)
                        await emit_stream_event(ev)
                        yield ev
                    if visible:
                        ev = LLMStreamEvent(kind="text_delta", text=visible)
                        await emit_stream_event(ev)
                        yield ev
        done_ev = LLMStreamEvent(kind="done")
        await emit_stream_event(done_ev)
        yield done_ev

    @staticmethod
    def _openai_usage_to_wire(usage_data: Any) -> Optional[Dict[str, int]]:
        if usage_data is None:
            return None
        return {
            "prompt_tokens": int(getattr(usage_data, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage_data, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage_data, "total_tokens", 0) or 0),
            "reasoning_tokens": int(getattr(usage_data, "reasoning_tokens", 0) or 0),
        }

    @staticmethod
    def _anthropic_usage_to_wire(usage_data: Any) -> Optional[Dict[str, int]]:
        if usage_data is None:
            return None
        prompt_tokens = int(getattr(usage_data, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_data, "output_tokens", 0) or 0)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ProviderResponse:
        """
        Unified tool-calling chat call.
        """
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        started_at = time.time()
        try:
            if getattr(self.llm, "_client", None) is None and not self.is_anthropic():
                provider_response = await self.chat_response(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                    thinking_depth=depth,
                )
                return provider_response

            provider_response = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_with_tools_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    timeout_seconds=timeout_seconds,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._attach_trace_metrics(
                provider_response=provider_response,
                usage=provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=provider_response.usage,
                event_context=event_context,
            )
            return provider_response
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
                error=str(exc),
            )
            raise

    async def chat_with_tools_stream(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        timeout_seconds: Optional[float] = None,
        event_context: Optional[Dict[str, Any]] = None,
        thinking_depth: ThinkingDepth | None = None,
    ) -> ToolStreamResult:
        """Streaming variant of chat_with_tools().

        All events (text deltas, reasoning deltas, tool-call lifecycle,
        usage) are forwarded to the stream sink bound via
        :func:`magi.llm.streaming_events.stream_scope`. If no sink is
        set this behaves like a silent aggregator — the returned
        ``ToolStreamResult`` still contains the complete assembled
        response.
        """
        depth = _coerce_thinking_depth(thinking_depth, None)
        started_at = time.time()
        try:
            result = await self._run_with_concurrency_limit(
                request_family="chat",
                limit=self._resolve_chat_concurrency_limit(),
                operation=lambda: self._chat_with_tools_stream_impl(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    thinking_depth=depth,
                    timeout_seconds=timeout_seconds,
                ),
            )

            latency_ms = int((time.time() - started_at) * 1000)
            self._attach_trace_metrics(
                provider_response=result.provider_response,
                usage=result.provider_response.usage,
                latency_ms=latency_ms,
                thinking_depth=depth,
            )
            await self._emit_usage_event(
                success=True,
                latency_ms=latency_ms,
                usage=result.provider_response.usage,
                event_context=event_context,
            )
            return result
        except Exception as exc:
            await self._emit_usage_event(
                success=False,
                latency_ms=int((time.time() - started_at) * 1000),
                usage=None,
                event_context=event_context,
                error=str(exc),
            )
            raise

    async def _chat_response_impl(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        json_mode: bool,
        timeout_seconds: Optional[float],
        event_context: Optional[Dict[str, Any]],
    ) -> ProviderResponse:
        if self.is_anthropic():
            api_messages = self._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": self.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": api_messages,
            }
            if timeout_seconds is not None:
                anthropic_kwargs["timeout"] = timeout_seconds
            anthropic_kwargs = self._apply_provider_options(anthropic_kwargs, thinking_depth)
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_request",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        request_type="anthropic_messages",
                        request=anthropic_kwargs,
                    ),
                )
            try:
                response = await self.llm._client.messages.create(**anthropic_kwargs)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_provider_error",
                        **_build_provider_test_log_context(
                            self.llm,
                            event_context,
                            request_type="anthropic_messages",
                            request=anthropic_kwargs,
                            provider_error=_extract_provider_error_details(exc),
                        ),
                    )
                raise
            if hasattr(response, "content"):
                parsed_response = self._parse_anthropic_response(response)
            else:
                parsed_response = self._build_content_response("")
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_response",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        response=_truncate_provider_response(parsed_response),
                    ),
                )
            return parsed_response

        full_messages = [{"role": "system", "content": system_prompt}] + self._convert_messages_to_openai(messages)
        chat_kwargs: Dict[str, Any] = {
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            chat_kwargs["response_format"] = {"type": "json_object"}
        if timeout_seconds is not None:
            chat_kwargs["timeout"] = timeout_seconds
        chat_kwargs = self._apply_provider_options(chat_kwargs, thinking_depth)

        if getattr(self.llm, "_client", None) is not None:
            chat_kwargs["model"] = self.llm.model_name
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_request",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        request_type="openai_chat_completions",
                        request=chat_kwargs,
                    ),
                )
            try:
                response = await self.llm._client.chat.completions.create(**chat_kwargs)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_provider_error",
                        **_build_provider_test_log_context(
                            self.llm,
                            event_context,
                            request_type="openai_chat_completions",
                            request=chat_kwargs,
                            provider_error=_extract_provider_error_details(exc),
                        ),
                    )
                raise
            raw_response_summary = _summarize_raw_provider_response(response)
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_raw_response",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        request_type="openai_chat_completions",
                        **raw_response_summary,
                    ),
                )
            try:
                parsed_response = self._parse_openai_response(response)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_parse_error",
                        **_build_provider_test_log_context(
                            self.llm,
                            event_context,
                            request_type="openai_chat_completions",
                            request=chat_kwargs,
                            parse_error={
                                "error_type": exc.__class__.__name__,
                                "error": str(exc),
                            },
                            **raw_response_summary,
                        ),
                    )
                raise ValueError(
                    f"Provider returned a non-OpenAI chat response payload (type={type(response).__name__})"
                ) from exc
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_response",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        response=_truncate_provider_response(parsed_response),
                    ),
                )
            return parsed_response

        if _is_provider_test_event(event_context):
            logger.info(
                "llm_provider_test_request",
                **_build_provider_test_log_context(
                    self.llm,
                    event_context,
                    request_type="adapter_chat",
                    request=chat_kwargs,
                ),
            )
        try:
            content = await self.llm.chat(**chat_kwargs)
        except Exception as exc:
            if _is_provider_test_event(event_context):
                logger.error(
                    "llm_provider_test_provider_error",
                    **_build_provider_test_log_context(
                        self.llm,
                        event_context,
                        request_type="adapter_chat",
                        request=chat_kwargs,
                        provider_error=_extract_provider_error_details(exc),
                    ),
                )
            raise
        provider_response = self._build_content_response(content)
        if _is_provider_test_event(event_context):
            logger.info(
                "llm_provider_test_response",
                **_build_provider_test_log_context(
                    self.llm,
                    event_context,
                    response=_truncate_provider_response(provider_response),
                ),
            )
        return provider_response

    async def _chat_with_tools_impl(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ProviderResponse:
        if self.is_anthropic():
            api_messages = self._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": self.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": api_messages,
                "tools": tools if tools else None,
                "timeout": timeout_seconds,
            }
            anthropic_kwargs = self._apply_provider_options(anthropic_kwargs, thinking_depth)
            response = await self.llm._client.messages.create(**anthropic_kwargs)
            return self._parse_anthropic_response(response)

        full_messages = [{"role": "system", "content": system_prompt}] + self._convert_messages_to_openai(messages)
        kwargs: Dict[str, Any] = {
            "model": self.llm.model_name,
            "messages": full_messages,
            "tools": tools if tools else None,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        kwargs = self._apply_provider_options(kwargs, thinking_depth)

        response = await self.llm._client.chat.completions.create(**kwargs)
        return self._parse_openai_response(response)

    async def _chat_with_tools_stream_impl(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        """Stream an LLM call with tools.

        All events (text, reasoning, tool-call lifecycle) are forwarded
        to the contextual stream sink via
        :func:`magi.llm.streaming_events.emit_stream_event`. The full
        assembled ``ProviderResponse`` (including any tool_calls) is
        returned inside ``ToolStreamResult``.
        """
        if self.is_anthropic():
            return await self._stream_anthropic_with_tools(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                thinking_depth=thinking_depth,
                timeout_seconds=timeout_seconds,
            )
        return await self._stream_openai_with_tools(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_depth=thinking_depth,
            timeout_seconds=timeout_seconds,
        )

    async def _stream_anthropic_with_tools(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        api_messages = self._convert_messages_to_anthropic(messages)
        anthropic_kwargs: Dict[str, Any] = {
            "model": self.llm.model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": api_messages,
            "tools": tools if tools else None,
            "timeout": timeout_seconds,
            "stream": True,
        }
        anthropic_kwargs = self._apply_provider_options(anthropic_kwargs, thinking_depth)
        stream = await self.llm._client.messages.create(**anthropic_kwargs)

        tool_calls: List[ProviderToolCall] = []
        content_parts: List[str] = []
        assistant_blocks: List[Dict[str, Any]] = []
        has_tool_calls = False
        chunks_emitted = 0
        in_thinking = False
        # Track current tool_use block being streamed
        current_tool_id: str | None = None
        current_tool_name: str | None = None
        current_tool_json_parts: List[str] = []
        usage_data: Any = None

        async for event in stream:
            event_type = getattr(event, "type", None)
            if event_type == "content_block_start":
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", None) if block is not None else None
                if block_type == "tool_use":
                    has_tool_calls = True
                    current_tool_id = block.id
                    current_tool_name = block.name
                    current_tool_json_parts = []
                    await emit_stream_event(LLMStreamEvent(
                        kind="tool_call_start",
                        tool_call_id=block.id,
                        tool_name=block.name,
                    ))
                elif block_type == "thinking":
                    in_thinking = True
            elif event_type == "content_block_delta":
                delta = event.delta
                delta_type = getattr(delta, "type", None)
                if delta_type == "thinking_delta":
                    text = getattr(delta, "thinking", None) or getattr(delta, "text", None)
                    if text:
                        await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text=text))
                elif in_thinking and getattr(delta, "text", None):
                    await emit_stream_event(LLMStreamEvent(kind="reasoning_delta", text=delta.text))
                elif hasattr(delta, "text") and not has_tool_calls:
                    text = delta.text
                    if text:
                        content_parts.append(text)
                        await emit_stream_event(LLMStreamEvent(kind="text_delta", text=text))
                        chunks_emitted += 1
                elif hasattr(delta, "text") and has_tool_calls:
                    # Text arriving after tool_use detected — collect but don't emit
                    if delta.text:
                        content_parts.append(delta.text)
                elif delta_type == "input_json_delta":
                    partial = getattr(delta, "partial_json", "")
                    if partial:
                        current_tool_json_parts.append(partial)
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_args",
                            tool_call_id=current_tool_id,
                            tool_name=current_tool_name,
                            tool_args_delta=partial,
                        ))
            elif event_type == "content_block_stop":
                if current_tool_id is not None:
                    raw_json = "".join(current_tool_json_parts)
                    try:
                        arguments = json.loads(raw_json) if raw_json else {}
                    except json.JSONDecodeError:
                        arguments = {"raw": raw_json}
                    tool_calls.append(ProviderToolCall(
                        id=current_tool_id,
                        name=current_tool_name or "",
                        arguments=arguments,
                    ))
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": current_tool_id,
                        "name": current_tool_name,
                        "input": arguments,
                    })
                    await emit_stream_event(LLMStreamEvent(
                        kind="tool_call_end",
                        tool_call_id=current_tool_id,
                        tool_name=current_tool_name,
                        tool_arguments=arguments,
                    ))
                    current_tool_id = None
                    current_tool_name = None
                    current_tool_json_parts = []
                in_thinking = False
            elif event_type == "message_delta":
                usage_data = getattr(event, "usage", usage_data)
            elif event_type == "message_start":
                msg = getattr(event, "message", None)
                if msg is not None:
                    usage_data = getattr(msg, "usage", usage_data)

        content_text = "".join(content_parts)
        if content_text:
            assistant_blocks.insert(0, {"type": "text", "text": content_text})

        usage = self._extract_anthropic_stream_usage(stream, usage_data)
        usage_payload = self._anthropic_usage_to_wire(usage_data)
        if usage_payload is not None:
            await emit_stream_event(LLMStreamEvent(kind="usage", usage=usage_payload))

        if tool_calls:
            provider_response = ProviderResponse(
                content=content_text,
                tool_calls=tool_calls,
                assistant_message={"role": "assistant", "content": assistant_blocks},
                usage=usage,
            )
        else:
            provider_response = ProviderResponse(content=content_text, usage=usage)

        return ToolStreamResult(
            provider_response=provider_response,
            text_chunks_emitted=chunks_emitted,
            has_tool_calls=has_tool_calls,
        )

    def _extract_anthropic_stream_usage(self, stream: Any, usage_data: Any) -> ProviderUsage | None:
        """Extract usage from Anthropic streaming events."""
        final_message = getattr(stream, "final_message", None) if hasattr(stream, "final_message") else None
        if final_message is not None:
            return self._extract_anthropic_usage(final_message)
        if usage_data is None:
            return None
        prompt_tokens = int(getattr(usage_data, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage_data, "output_tokens", 0) or 0)
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    async def _stream_openai_with_tools(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        thinking_depth: ThinkingDepth,
        timeout_seconds: Optional[float],
    ) -> ToolStreamResult:
        full_messages = [{"role": "system", "content": system_prompt}] + self._convert_messages_to_openai(messages)
        kwargs: Dict[str, Any] = {
            "model": self.llm.model_name,
            "messages": full_messages,
            "tools": tools if tools else None,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        kwargs = self._apply_provider_options(kwargs, thinking_depth)

        stream = await self.llm._client.chat.completions.create(**kwargs)

        tool_calls_by_index: Dict[int, Dict[str, Any]] = {}
        content_parts: List[str] = []
        has_tool_calls = False
        chunks_emitted = 0
        usage_data: Any = None
        scrubber = _ThinkTagScrubber()

        async for chunk in stream:
            if not chunk.choices:
                # usage-only final chunk
                if hasattr(chunk, "usage") and chunk.usage is not None:
                    usage_data = chunk.usage
                continue
            delta = chunk.choices[0].delta

            # Detect tool_calls
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                has_tool_calls = True
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    existing = tool_calls_by_index.get(idx)
                    if existing is None:
                        entry = {
                            "id": getattr(tc_delta, "id", None) or "",
                            "name": "",
                            "arguments_parts": [],
                            "start_emitted": False,
                        }
                        tool_calls_by_index[idx] = entry
                    else:
                        entry = existing
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if hasattr(tc_delta, "function") and tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        args_fragment = tc_delta.function.arguments
                        if args_fragment:
                            entry["arguments_parts"].append(args_fragment)
                    # Emit tool_call_start once we have both id and name
                    if not entry["start_emitted"] and entry["id"] and entry["name"]:
                        entry["start_emitted"] = True
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_start",
                            tool_call_id=entry["id"],
                            tool_name=entry["name"],
                        ))
                    # Emit tool_call_args for any fragment seen this chunk
                    if (
                        entry["start_emitted"]
                        and hasattr(tc_delta, "function")
                        and tc_delta.function
                        and tc_delta.function.arguments
                    ):
                        await emit_stream_event(LLMStreamEvent(
                            kind="tool_call_args",
                            tool_call_id=entry["id"],
                            tool_name=entry["name"],
                            tool_args_delta=tc_delta.function.arguments,
                        ))

            # Reasoning (GLM / compatible providers)
            reasoning_text = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_text:
                await emit_stream_event(LLMStreamEvent(
                    kind="reasoning_delta",
                    text=reasoning_text,
                ))

            # Visible text
            if hasattr(delta, "content") and delta.content:
                if not has_tool_calls:
                    visible, reasoning_leak = scrubber.feed(delta.content)
                    if reasoning_leak:
                        await emit_stream_event(LLMStreamEvent(
                            kind="reasoning_delta",
                            text=reasoning_leak,
                        ))
                    if visible:
                        content_parts.append(visible)
                        await emit_stream_event(LLMStreamEvent(
                            kind="text_delta",
                            text=visible,
                        ))
                        chunks_emitted += 1
                else:
                    # Tool-call branch already collects post-tool text raw.
                    content_parts.append(delta.content)

            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage_data = chunk.usage

        tail_visible, tail_reasoning = scrubber.flush()
        if tail_reasoning:
            await emit_stream_event(LLMStreamEvent(
                kind="reasoning_delta",
                text=tail_reasoning,
            ))
        if tail_visible and not has_tool_calls:
            content_parts.append(tail_visible)
            await emit_stream_event(LLMStreamEvent(
                kind="text_delta",
                text=tail_visible,
            ))
            chunks_emitted += 1

        content_text = "".join(content_parts)

        # Build tool_calls
        tool_calls: List[ProviderToolCall] = []
        raw_tool_calls: List[Dict[str, Any]] = []
        for idx in sorted(tool_calls_by_index.keys()):
            entry = tool_calls_by_index[idx]
            raw_args = "".join(entry["arguments_parts"])
            try:
                arguments = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                arguments = {"raw": raw_args}
            tool_calls.append(ProviderToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=arguments,
            ))
            raw_tool_calls.append({
                "id": entry["id"],
                "type": "function",
                "function": {
                    "name": entry["name"],
                    "arguments": raw_args or "{}",
                },
            })
            await emit_stream_event(LLMStreamEvent(
                kind="tool_call_end",
                tool_call_id=entry["id"],
                tool_name=entry["name"],
                tool_arguments=arguments,
            ))

        usage = self._extract_openai_stream_usage(usage_data)
        usage_payload = self._openai_usage_to_wire(usage_data)
        if usage_payload is not None:
            await emit_stream_event(LLMStreamEvent(kind="usage", usage=usage_payload))

        if tool_calls:
            provider_response = ProviderResponse(
                content=content_text,
                tool_calls=tool_calls,
                assistant_message={
                    "role": "assistant",
                    "content": content_text or "",
                    "tool_calls": raw_tool_calls,
                },
                usage=usage,
            )
        else:
            provider_response = ProviderResponse(content=content_text, usage=usage)

        return ToolStreamResult(
            provider_response=provider_response,
            text_chunks_emitted=chunks_emitted,
            has_tool_calls=has_tool_calls,
        )

    @staticmethod
    def _extract_openai_stream_usage(usage_data: Any) -> ProviderUsage | None:
        if usage_data is None:
            return None
        return ProviderUsage(
            prompt_tokens=int(getattr(usage_data, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage_data, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage_data, "total_tokens", 0) or 0),
            reasoning_tokens=int(getattr(usage_data, "reasoning_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage_data, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage_data, "cache_write_tokens", 0) or 0),
        )

    def _convert_messages_to_anthropic(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted = []
        for msg in messages:
            if msg.get("role") == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id"),
                        "content": msg.get("content", ""),
                    }],
                })
            elif msg.get("role") == "user" and isinstance(msg.get("content"), list):
                converted.append({
                    "role": "user",
                    "content": self._convert_content_blocks_to_anthropic(msg["content"]),
                })
            elif msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
                converted.append({"role": "assistant", "content": msg["content"]})
            else:
                converted.append({
                    "role": msg.get("role"),
                    "content": msg.get("content", ""),
                })
        return converted

    def _convert_messages_to_openai(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                converted.append({
                    "role": "user",
                    "content": self._convert_content_blocks_to_openai(msg["content"]),
                })
                continue
            converted.append(dict(msg))
        return converted

    @staticmethod
    def _convert_content_blocks_to_openai(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
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
    def _convert_content_blocks_to_anthropic(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
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
        tool_calls: List[ProviderToolCall] = []
        content_text_parts: List[str] = []
        assistant_blocks: List[Dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                text_value = block.text or ""
                content_text_parts.append(text_value)
                assistant_blocks.append({"type": "text", "text": text_value})
            elif block.type == "tool_use":
                tool_calls.append(ProviderToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

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

        tool_calls: List[ProviderToolCall] = []
        raw_tool_calls: List[Dict[str, Any]] = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                arguments: Dict[str, Any] = {}
                if tc.function.arguments:
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": tc.function.arguments}

                tool_calls.append(ProviderToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                ))
                raw_tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                })

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
        raw_tool_calls: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
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
            reasoning_tokens=int(getattr(usage, "reasoning_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_write_tokens", 0) or 0),
        )

    @staticmethod
    def _extract_anthropic_usage(response: Any) -> ProviderUsage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return ProviderUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            reasoning_tokens=int(getattr(usage, "reasoning_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_write_tokens", 0) or 0),
        )

    def _attach_trace_metrics(
        self,
        *,
        provider_response: ProviderResponse,
        usage: ProviderUsage | None,
        latency_ms: int,
        thinking_depth: ThinkingDepth,
        disable_thinking: Optional[bool] = None,
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

    async def _emit_usage_event(
        self,
        *,
        success: bool,
        latency_ms: int,
        usage: ProviderUsage | None,
        event_context: Optional[Dict[str, Any]],
        error: str | None = None,
    ) -> None:
        context = dict(event_context or {})
        payload = LLMCallEventPayload(
            request_id=str(context.get("request_id") or uuid.uuid4().hex[:8]),
            provider=self._provider_name() or type(self.llm).__name__,
            model=str(getattr(self.llm, "model_name", "unknown")),
            request_kind=str(context.get("request_kind") or "chat"),
            prompt_tokens=int(usage.prompt_tokens if usage else 0),
            completion_tokens=int(usage.completion_tokens if usage else 0),
            total_tokens=int(usage.total_tokens if usage else 0),
            usage_available=usage is not None,
            latency_ms=int(latency_ms),
            success=success,
            error=error,
            correlation_id=context.get("correlation_id"),
            session_id=context.get("session_id"),
            turn_id=context.get("turn_id"),
            agent_id=context.get("agent_id"),
        )
        await publish_llm_call_event(payload, publisher=self._usage_event_publisher)
