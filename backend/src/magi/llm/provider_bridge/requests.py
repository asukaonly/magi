"""Non-streaming provider request helpers for the LLM provider bridge."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, cast

from .logging import (
    build_provider_test_log_context as _build_provider_test_log_context,
    extract_provider_error_details as _extract_provider_error_details,
    is_provider_test_event as _is_provider_test_event,
    summarize_raw_provider_response as _summarize_raw_provider_response,
    truncate_provider_response as _truncate_provider_response,
)
from .models import ProviderResponse
from ...config.models import ThinkingDepth
from ...core.logger import get_logger

logger = get_logger(__name__)


class _ProviderBridgeRequestHostProtocol(Protocol):
    llm: Any

    def is_anthropic(self) -> bool:
        ...

    def _convert_messages_to_anthropic(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...

    def _convert_messages_to_openai(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        ...

    def _cache_marked_system(self, system_prompt: str) -> Any:
        ...

    def _inject_turn_context(
        self, messages: list[dict[str, Any]], system_prompt: str
    ) -> list[dict[str, Any]]:
        ...

    def _parse_anthropic_response(self, response: Any) -> ProviderResponse:
        ...

    def _parse_openai_response(self, response: Any) -> ProviderResponse:
        ...

    def _build_content_response(self, content: str) -> ProviderResponse:
        ...


class ProviderBridgeRequestMixin:
    """Execute non-streaming provider requests and normalize responses."""

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
        host = cast(_ProviderBridgeRequestHostProtocol, self)
        messages = host._inject_turn_context(messages, system_prompt)
        if host.is_anthropic():
            api_messages = host._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": host.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": host._cache_marked_system(system_prompt),
                "messages": api_messages,
            }
            if timeout_seconds is not None:
                anthropic_kwargs["timeout"] = timeout_seconds
            anthropic_kwargs = host._apply_provider_options(anthropic_kwargs, thinking_depth)
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_request",
                    **_build_provider_test_log_context(
                        host.llm,
                        event_context,
                        request_type="anthropic_messages",
                        request=anthropic_kwargs,
                    ),
                )
            try:
                response = await host.llm._client.messages.create(**anthropic_kwargs)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_provider_error",
                        **_build_provider_test_log_context(
                            host.llm,
                            event_context,
                            request_type="anthropic_messages",
                            request=anthropic_kwargs,
                            provider_error=_extract_provider_error_details(exc),
                        ),
                    )
                raise
            if hasattr(response, "content"):
                parsed_response = host._parse_anthropic_response(response)
            else:
                parsed_response = host._build_content_response("")
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_response",
                    **_build_provider_test_log_context(
                        host.llm,
                        event_context,
                        response=_truncate_provider_response(parsed_response),
                    ),
                )
            return parsed_response

        full_messages = [{"role": "system", "content": host._cache_marked_system(system_prompt)}] + host._convert_messages_to_openai(messages)
        chat_kwargs: Dict[str, Any] = {
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            chat_kwargs["response_format"] = {"type": "json_object"}
        if timeout_seconds is not None:
            chat_kwargs["timeout"] = timeout_seconds
        chat_kwargs = host._apply_provider_options(chat_kwargs, thinking_depth)

        if getattr(host.llm, "_client", None) is not None:
            chat_kwargs["model"] = host.llm.model_name
            if _is_provider_test_event(event_context):
                logger.info(
                    "llm_provider_test_request",
                    **_build_provider_test_log_context(
                        host.llm,
                        event_context,
                        request_type="openai_chat_completions",
                        request=chat_kwargs,
                    ),
                )
            try:
                response = await host.llm._client.chat.completions.create(**chat_kwargs)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_provider_error",
                        **_build_provider_test_log_context(
                            host.llm,
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
                        host.llm,
                        event_context,
                        request_type="openai_chat_completions",
                        **raw_response_summary,
                    ),
                )
            try:
                parsed_response = host._parse_openai_response(response)
            except Exception as exc:
                if _is_provider_test_event(event_context):
                    logger.error(
                        "llm_provider_test_parse_error",
                        **_build_provider_test_log_context(
                            host.llm,
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
                        host.llm,
                        event_context,
                        response=_truncate_provider_response(parsed_response),
                    ),
                )
            return parsed_response

        if _is_provider_test_event(event_context):
            logger.info(
                "llm_provider_test_request",
                **_build_provider_test_log_context(
                    host.llm,
                    event_context,
                    request_type="adapter_chat",
                    request=chat_kwargs,
                ),
            )
        try:
            content = await host.llm.chat(**chat_kwargs)
        except Exception as exc:
            if _is_provider_test_event(event_context):
                logger.error(
                    "llm_provider_test_provider_error",
                    **_build_provider_test_log_context(
                        host.llm,
                        event_context,
                        request_type="adapter_chat",
                        request=chat_kwargs,
                        provider_error=_extract_provider_error_details(exc),
                    ),
                )
            raise
        provider_response = host._build_content_response(content)
        if _is_provider_test_event(event_context):
            logger.info(
                "llm_provider_test_response",
                **_build_provider_test_log_context(
                    host.llm,
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
        host = cast(_ProviderBridgeRequestHostProtocol, self)
        messages = host._inject_turn_context(messages, system_prompt)
        if host.is_anthropic():
            api_messages = host._convert_messages_to_anthropic(messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": host.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": host._cache_marked_system(system_prompt),
                "messages": api_messages,
                "tools": tools if tools else None,
                "timeout": timeout_seconds,
            }
            anthropic_kwargs = host._apply_provider_options(anthropic_kwargs, thinking_depth)
            response = await host.llm._client.messages.create(**anthropic_kwargs)
            return host._parse_anthropic_response(response)

        full_messages = [{"role": "system", "content": host._cache_marked_system(system_prompt)}] + host._convert_messages_to_openai(messages)
        kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "messages": full_messages,
            "tools": tools if tools else None,
            "tool_choice": "auto" if tools else None,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        kwargs = host._apply_provider_options(kwargs, thinking_depth)

        response = await host.llm._client.chat.completions.create(**kwargs)
        return host._parse_openai_response(response)
