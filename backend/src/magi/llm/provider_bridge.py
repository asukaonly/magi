"""
Provider bridge for provider-specific request/response handling.

This module centralizes API differences between OpenAI-compatible models
(OpenAI/GLM) and Anthropic, so business layers can use one unified interface.
"""
import json
from dataclasses import dataclass
from typing import Any, Dict, List

from .base import LLMAdapter
from .anthropic import AnthropicAdapter


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

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


class LLMProviderBridge:
    """Unified entrypoint for provider-specific LLM calls."""

    def __init__(self, llm_adapter: LLMAdapter):
        self.llm = llm_adapter

    def _provider_name(self) -> str:
        return (getattr(self.llm, "provider_name", "") or "").lower()

    def is_anthropic(self) -> bool:
        return isinstance(self.llm, AnthropicAdapter)

    def is_glm(self) -> bool:
        provider = self._provider_name()
        model_name = (getattr(self.llm, "model_name", "") or "").lower()
        return provider == "glm" or model_name.startswith("glm")

    async def chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7,
        disable_thinking: bool = True,
    ) -> str:
        """
        Unified non-tool chat call with system prompt.
        """
        if self.is_anthropic():
            response = await self.llm._client.messages.create(
                model=self.llm.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text if response.content else ""

        full_messages = [{"role": "system", "content": system_prompt}] + messages
        kwargs: Dict[str, Any] = {}
        if self.is_glm():
            # GLM thinking flag is provider-specific; bridge normalizes by behavior intent.
            extra_body: Dict[str, Any] = {}
            if disable_thinking:
                extra_body["thinking"] = {"type": "disabled"}
            if extra_body:
                kwargs["extra_body"] = extra_body

        return await self.llm.chat(
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    async def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        disable_thinking: bool = True,
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
            if self.is_glm() and disable_thinking:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

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
        return ProviderResponse(content=content)

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

        return ProviderResponse(content="".join(content_text_parts))

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
            )

        return ProviderResponse(content=message.content or "")
