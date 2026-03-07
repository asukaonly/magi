"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import LLMAdapter
from .anthropic import AnthropicAdapter
from .parsers import parse_legacy_tool_calls, sanitize_llm_text
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

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []
        if self.metadata is None:
            self.metadata = {}


class LLMProviderBridge:
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(self, llm_adapter: LLMAdapter):
        self.llm = llm_adapter

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
    ) -> str:
        """
        Unified notttn-tool chat call with system prompt.
        """
        response = await self.chat_response(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            disable_thinking=disable_thinking,
        )
        return response.content

    async def chat_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_THINKING_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
    ) -> ProviderResponse:
        """
        Unified plain-chat call that still returns normalized ProviderResponse.
        """
        if self.is_anthropic():
            response = await self.llm._client.messages.create(
                model=self.llm.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=messages,
            )
            if hasattr(response, "content"):
                return self._parse_anthropic_response(response)
            return self._build_content_response("")

        full_messages = [{"role": "system", "content": system_prompt}] + messages
        chat_kwargs: Dict[str, Any] = {
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self.is_glm():
            extra_body = self._disabled_thinking_extra_body(disable_thinking)
            if extra_body:
                chat_kwargs["extra_body"] = extra_body

        if getattr(self.llm, "_client", None) is not None:
            chat_kwargs["model"] = self.llm.model_name
            response = await self.llm._client.chat.completions.create(**chat_kwargs)
            return self._parse_openai_response(response)

        content = await self.llm.chat(**chat_kwargs)
        return self._build_content_response(content)

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.7,
        disable_thinking: Optional[bool] = None,
    ) -> ProviderResponse:
        """
        Unified tool-calling chat call.
        """
        if self.is_anthropic():
            api_messages = self._convert_messages_to_anthropic(messages)
            response = await self.llm._client.messages.create(
                model=self.llm.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=api_messages,
                tools=tools if tools else None,
            )
            return self._parse_anthropic_response(response)

        if hasattr(self.llm, "_client"):
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            kwargs: Dict[str, Any] = {
                "model": self.llm.model_name,
                "messages": full_messages,
                "tools": tools if tools else None,
                "tool_choice": "auto" if tools else None,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if self.is_glm():
                extra_body = self._disabled_thinking_extra_body(disable_thinking)
                if extra_body:
                    kwargs["extra_body"] = extra_body

            response = await self.llm._client.chat.completions.create(**kwargs)
            return self._parse_openai_response(response)

        # Fallback to plain chat for adapters without native tool API client.
        content = await self.chat(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            disable_thinking=disable_thinking,
        )
        return self._build_content_response(content)

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
            )

        return self._build_content_response("".join(content_text_parts))

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
            )

        response = self._build_content_response(message.content or "")
        response.metadata = self._build_openai_metadata(choice, message, raw_tool_calls)
        return response

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
