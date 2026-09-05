"""Non-streaming provider request helpers for the LLM provider bridge."""

from __future__ import annotations

from dataclasses import dataclass
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

    def is_anthropic(self) -> bool: ...

    def _convert_messages_to_anthropic(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def _convert_messages_to_openai(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]: ...

    def _cache_marked_system(
        self, system_prompt: str, *, cache_whole: bool = False
    ) -> Any: ...

    def _mark_message_cache_breakpoints(
        self,
        injected_messages: list[dict[str, Any]],
        api_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]: ...

    def _apply_cache_routing(
        self, kwargs: dict[str, Any], event_context: Optional[dict[str, Any]]
    ) -> dict[str, Any]: ...

    def _parse_anthropic_response(self, response: Any) -> ProviderResponse: ...

    def _parse_openai_response(self, response: Any) -> ProviderResponse: ...

    def _build_content_response(self, content: str) -> ProviderResponse: ...


@dataclass(frozen=True)
class _ChatResponseRequest:
    system_prompt: str
    messages: List[Dict[str, Any]]
    max_tokens: int
    temperature: float
    thinking_depth: ThinkingDepth
    json_mode: bool
    timeout_seconds: Optional[float]
    event_context: Optional[Dict[str, Any]]
    cache_system: bool


def _log_provider_test_request(
    host: _ProviderBridgeRequestHostProtocol,
    event_context: Optional[Dict[str, Any]],
    *,
    request_type: str,
    request: Dict[str, Any],
) -> None:
    if not _is_provider_test_event(event_context):
        return
    logger.info(
        "llm_provider_test_request",
        **_build_provider_test_log_context(
            host.llm,
            event_context,
            request_type=request_type,
            request=request,
        ),
    )


def _log_provider_test_error(
    host: _ProviderBridgeRequestHostProtocol,
    event_context: Optional[Dict[str, Any]],
    *,
    request_type: str,
    request: Dict[str, Any],
    exc: Exception,
) -> None:
    if not _is_provider_test_event(event_context):
        return
    logger.error(
        "llm_provider_test_provider_error",
        **_build_provider_test_log_context(
            host.llm,
            event_context,
            request_type=request_type,
            request=request,
            provider_error=_extract_provider_error_details(exc),
        ),
    )


def _log_provider_test_response(
    host: _ProviderBridgeRequestHostProtocol,
    event_context: Optional[Dict[str, Any]],
    response: ProviderResponse,
) -> None:
    if not _is_provider_test_event(event_context):
        return
    logger.info(
        "llm_provider_test_response",
        **_build_provider_test_log_context(
            host.llm,
            event_context,
            response=_truncate_provider_response(response),
        ),
    )


def _log_openai_raw_response(
    host: _ProviderBridgeRequestHostProtocol,
    event_context: Optional[Dict[str, Any]],
    raw_response_summary: Dict[str, Any],
) -> None:
    if not _is_provider_test_event(event_context):
        return
    logger.info(
        "llm_provider_test_raw_response",
        **_build_provider_test_log_context(
            host.llm,
            event_context,
            request_type="openai_chat_completions",
            **raw_response_summary,
        ),
    )


def _log_openai_parse_error(
    host: _ProviderBridgeRequestHostProtocol,
    event_context: Optional[Dict[str, Any]],
    *,
    request: Dict[str, Any],
    exc: Exception,
    raw_response_summary: Dict[str, Any],
) -> None:
    if not _is_provider_test_event(event_context):
        return
    logger.error(
        "llm_provider_test_parse_error",
        **_build_provider_test_log_context(
            host.llm,
            event_context,
            request_type="openai_chat_completions",
            request=request,
            parse_error={
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            },
            **raw_response_summary,
        ),
    )


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
        cache_system: bool = False,
    ) -> ProviderResponse:
        host = cast(_ProviderBridgeRequestHostProtocol, self)
        if getattr(host.llm, "is_plugin_provider", False) is True:
            return await host.llm.invoke_response(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                options={
                    "json_mode": json_mode,
                    "thinking_depth": thinking_depth.value,
                },
            )
        request = _ChatResponseRequest(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking_depth=thinking_depth,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            event_context=event_context,
            cache_system=cache_system,
        )
        if host.is_anthropic():
            return await self._chat_response_anthropic(host, request)
        return await self._chat_response_openai_or_adapter(host, request)

    async def _chat_response_anthropic(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
    ) -> ProviderResponse:
        anthropic_kwargs = self._build_anthropic_chat_kwargs(host, request)
        _log_provider_test_request(
            host,
            request.event_context,
            request_type="anthropic_messages",
            request=anthropic_kwargs,
        )
        try:
            response = await host.llm._client.messages.create(**anthropic_kwargs)
        except Exception as exc:
            _log_provider_test_error(
                host,
                request.event_context,
                request_type="anthropic_messages",
                request=anthropic_kwargs,
                exc=exc,
            )
            raise
        if hasattr(response, "content"):
            parsed_response = host._parse_anthropic_response(response)
        else:
            parsed_response = host._build_content_response("")
        _log_provider_test_response(host, request.event_context, parsed_response)
        return parsed_response

    async def _chat_response_openai_or_adapter(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
    ) -> ProviderResponse:
        chat_kwargs = self._build_openai_chat_kwargs(host, request)
        if getattr(host.llm, "_client", None) is not None:
            return await self._chat_response_openai_client(host, request, chat_kwargs)
        return await self._chat_response_adapter(host, request, chat_kwargs)

    async def _chat_response_openai_client(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
        chat_kwargs: Dict[str, Any],
    ) -> ProviderResponse:
        chat_kwargs["model"] = host.llm.model_name
        _log_provider_test_request(
            host,
            request.event_context,
            request_type="openai_chat_completions",
            request=chat_kwargs,
        )
        try:
            response = await host.llm._client.chat.completions.create(**chat_kwargs)
        except Exception as exc:
            _log_provider_test_error(
                host,
                request.event_context,
                request_type="openai_chat_completions",
                request=chat_kwargs,
                exc=exc,
            )
            raise

        raw_response_summary = _summarize_raw_provider_response(response)
        _log_openai_raw_response(host, request.event_context, raw_response_summary)
        try:
            parsed_response = host._parse_openai_response(response)
        except Exception as exc:
            _log_openai_parse_error(
                host,
                request.event_context,
                request=chat_kwargs,
                exc=exc,
                raw_response_summary=raw_response_summary,
            )
            raise ValueError(
                f"Provider returned a non-OpenAI chat response payload (type={type(response).__name__})"
            ) from exc
        _log_provider_test_response(host, request.event_context, parsed_response)
        return parsed_response

    async def _chat_response_adapter(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
        chat_kwargs: Dict[str, Any],
    ) -> ProviderResponse:
        _log_provider_test_request(
            host,
            request.event_context,
            request_type="adapter_chat",
            request=chat_kwargs,
        )
        try:
            content = await host.llm.chat(**chat_kwargs)
        except Exception as exc:
            _log_provider_test_error(
                host,
                request.event_context,
                request_type="adapter_chat",
                request=chat_kwargs,
                exc=exc,
            )
            raise
        provider_response = host._build_content_response(content)
        _log_provider_test_response(host, request.event_context, provider_response)
        return provider_response

    def _build_anthropic_chat_kwargs(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
    ) -> Dict[str, Any]:
        api_messages = host._convert_messages_to_anthropic(request.messages)
        api_messages = host._mark_message_cache_breakpoints(
            request.messages, api_messages
        )
        anthropic_kwargs: Dict[str, Any] = {
            "model": host.llm.model_name,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": host._cache_marked_system(
                request.system_prompt,
                cache_whole=request.cache_system,
            ),
            "messages": api_messages,
        }
        if request.timeout_seconds is not None:
            anthropic_kwargs["timeout"] = request.timeout_seconds
        return host._apply_provider_options(anthropic_kwargs, request.thinking_depth)

    def _build_openai_chat_kwargs(
        self,
        host: _ProviderBridgeRequestHostProtocol,
        request: _ChatResponseRequest,
    ) -> Dict[str, Any]:
        openai_messages = host._mark_message_cache_breakpoints(
            request.messages, host._convert_messages_to_openai(request.messages)
        )
        full_messages = [
            {
                "role": "system",
                "content": host._cache_marked_system(
                    request.system_prompt,
                    cache_whole=request.cache_system,
                ),
            }
        ] + openai_messages
        chat_kwargs: Dict[str, Any] = {
            "messages": full_messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.json_mode:
            chat_kwargs["response_format"] = {"type": "json_object"}
        if request.timeout_seconds is not None:
            chat_kwargs["timeout"] = request.timeout_seconds
        chat_kwargs = host._apply_provider_options(chat_kwargs, request.thinking_depth)
        return host._apply_cache_routing(chat_kwargs, request.event_context)

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
        event_context: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        host = cast(_ProviderBridgeRequestHostProtocol, self)
        if getattr(host.llm, "is_plugin_provider", False) is True:
            return await host.llm.invoke_response(
                system_prompt=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
                event_context=event_context,
                options={"thinking_depth": thinking_depth.value},
            )
        if host.is_anthropic():
            api_messages = host._convert_messages_to_anthropic(messages)
            api_messages = host._mark_message_cache_breakpoints(messages, api_messages)
            anthropic_kwargs: Dict[str, Any] = {
                "model": host.llm.model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": host._cache_marked_system(system_prompt),
                "messages": api_messages,
                "tools": tools if tools else None,
                "timeout": timeout_seconds,
            }
            anthropic_kwargs = host._apply_provider_options(
                anthropic_kwargs, thinking_depth
            )
            response = await host.llm._client.messages.create(**anthropic_kwargs)
            return host._parse_anthropic_response(response)

        openai_messages = host._mark_message_cache_breakpoints(
            messages, host._convert_messages_to_openai(messages)
        )
        full_messages = [
            {"role": "system", "content": host._cache_marked_system(system_prompt)}
        ] + openai_messages
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
        kwargs = host._apply_cache_routing(kwargs, event_context)

        response = await host.llm._client.chat.completions.create(**kwargs)
        return host._parse_openai_response(response)
