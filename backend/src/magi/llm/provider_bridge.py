"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
import time
import uuid
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from .base import LLMAdapter
from .anthropic import AnthropicAdapter
from .concurrency_limiter import LLMConcurrencyLimiter, get_llm_concurrency_limiter
from .parsers import parse_legacy_tool_calls, sanitize_llm_text
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


DEFAULT_CHAT_CONCURRENCY_FALLBACK = 4


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
    ) -> AsyncIterator[str]:
        """Streaming variant of chat_response(). Yields text chunks."""
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
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield event.delta.text
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
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            else:
                content = await self.llm.chat(**chat_kwargs)
                yield content

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
            response = await self.llm._client.messages.create(**anthropic_kwargs)
            if hasattr(response, "content"):
                return self._parse_anthropic_response(response)
            return self._build_content_response("")

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
            response = await self.llm._client.chat.completions.create(**chat_kwargs)
            return self._parse_openai_response(response)

        content = await self.llm.chat(**chat_kwargs)
        return self._build_content_response(content)

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
