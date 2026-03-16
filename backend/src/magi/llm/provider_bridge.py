"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import LLMAdapter
from .anthropic import AnthropicAdapter
from .parsers import parse_legacy_tool_calls, sanitize_llm_text
from .usage_events import LLMCallEventPayload, LLMUsageEventPublisher, publish_llm_call_event
from ..config.constants import DEFAULT_MAX_TOKENS, DEFAULT_THINKING_TOKENS


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


class LLMProviderBridge:
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(
        self,
        llm_adapter: LLMAdapter,
        usage_event_publisher: LLMUsageEventPublisher | None = None,
    ):
        self.llm = llm_adapter
        self._usage_event_publisher = usage_event_publisher or getattr(
            llm_adapter,
            "_llm_usage_event_publisher",
            None,
        )

    def _provider_name(self) -> str:
        return (getattr(self.llm, "provider_name", "") or "").lower()

    def is_anthropic(self) -> bool:
        return isinstance(self.llm, AnthropicAdapter)

    def is_glm(self) -> bool:
        """Check if using GLM provider."""
        return self._provider_name() == "glm"

    @staticmethod
    def _disabled_thinking_extra_body(disable_thinking: Optional[bool]) -> Dict[str, Any] | None:
        """Build provider-specific payload to disable reasoning/thinking mode."""
        if disable_thinking is not True:
            return None
        return {"thinking": {"type": "disabled"}}

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
    ) -> str:
        """
        Unified non-tool chat call with system prompt.
        """
        response = await self.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            disable_thinking=disable_thinking,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
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
    ) -> ProviderResponse:
        """
        Unified plain-chat call that still returns normalized ProviderResponse.
        """
        started_at = time.time()
        try:
            if self.is_anthropic():
                anthropic_kwargs: Dict[str, Any] = {
                    "model": self.llm.model_name,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system_prompt,
                    "messages": messages,
                }
                if timeout_seconds is not None:
                    anthropic_kwargs["timeout"] = timeout_seconds
                response = await self.llm._client.messages.create(**anthropic_kwargs)
                if hasattr(response, "content"):
                    provider_response = self._parse_anthropic_response(response)
                else:
                    provider_response = self._build_content_response("")
            else:
                full_messages = [{"role": "system", "content": system_prompt}] + messages
                chat_kwargs: Dict[str, Any] = {
                    "messages": full_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if json_mode:
                    chat_kwargs["response_format"] = {"type": "json_object"}
                if timeout_seconds is not None:
                    chat_kwargs["timeout"] = timeout_seconds
                if self.is_glm():
                    extra_body = self._disabled_thinking_extra_body(disable_thinking)
                    if extra_body:
                        chat_kwargs["extra_body"] = extra_body

                if getattr(self.llm, "_client", None) is not None:
                    chat_kwargs["model"] = self.llm.model_name
                    response = await self.llm._client.chat.completions.create(**chat_kwargs)
                    provider_response = self._parse_openai_response(response)
                else:
                    content = await self.llm.chat(**chat_kwargs)
                    provider_response = self._build_content_response(content)

            await self._emit_usage_event(
                success=True,
                latency_ms=int((time.time() - started_at) * 1000),
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
    ) -> ProviderResponse:
        """
        Unified tool-calling chat call.
        """
        started_at = time.time()
        try:
            if self.is_anthropic():
                api_messages = self._convert_messages_to_anthropic(messages)
                response = await self.llm._client.messages.create(
                    model=self.llm.model_name,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=api_messages,
                    tools=tools if tools else None,
                    timeout=timeout_seconds,
                )
                provider_response = self._parse_anthropic_response(response)
            elif hasattr(self.llm, "_client"):
                full_messages = [{"role": "system", "content": system_prompt}] + messages
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
                if self.is_glm():
                    extra_body = self._disabled_thinking_extra_body(disable_thinking)
                    if extra_body:
                        kwargs["extra_body"] = extra_body

                response = await self.llm._client.chat.completions.create(**kwargs)
                provider_response = self._parse_openai_response(response)
            else:
                provider_response = await self.chat_response(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    disable_thinking=disable_thinking,
                    timeout_seconds=timeout_seconds,
                    event_context=event_context,
                )
                return provider_response

            await self._emit_usage_event(
                success=True,
                latency_ms=int((time.time() - started_at) * 1000),
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
            elif msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
                converted.append({"role": "assistant", "content": msg["content"]})
            else:
                converted.append({
                    "role": msg.get("role"),
                    "content": msg.get("content", ""),
                })
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
        )

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
