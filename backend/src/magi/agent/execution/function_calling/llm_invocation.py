"""Provider-call variants for function-calling LLM execution."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol, cast

from ....config.constants import DEFAULT_MAX_TOKENS
from ....config.models import ThinkingDepth
from ....llm.cancellable_client import (
    CancellableLLMClient,
    CancellationRaised,
    RetractRaised,
)
from ....llm.provider_bridge import LLMProviderBridge, ToolStreamResult
from ....llm.streaming_events import get_stream_sink
from ....runtime_trace import enrich_event_context_with_turn_trace
from magi.control.run_control import RunControl

THINKING_LLM_TIMEOUT_SECONDS = 180.0


class LlmInvocationHostProtocol(Protocol):
    provider_bridge: LLMProviderBridge

    async def _invoke_with_rate_limit_backoff(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        label: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class FunctionCallingLlmRequest:
    request_id: str
    request_kind: str
    system_prompt: str
    messages: list[dict[str, Any]]
    thinking_depth: ThinkingDepth
    timeout_seconds: float | None
    session_id: str | None
    turn_id: str | None
    execution_agent_id: str
    execution_preset: str
    iteration: int | None


@dataclass(frozen=True, slots=True)
class ToolsProviderCallResult:
    provider_response: Any
    streamed: bool


@dataclass(frozen=True, slots=True)
class FinalProviderCallResult:
    content: str
    provider_response: Any | None
    streamed: bool


def build_llm_event_context(request: FunctionCallingLlmRequest) -> dict[str, Any]:
    context = {
        "request_id": request.request_id,
        "request_kind": request.request_kind,
        "session_id": request.session_id,
        "turn_id": request.turn_id,
        "agent_id": request.execution_agent_id,
        "correlation_id": request.turn_id,
        "execution_preset": request.execution_preset,
    }
    normalized_turn_id = str(request.turn_id or "").strip()
    if normalized_turn_id and request.iteration is not None and request.iteration > 0:
        context["parent_span_id"] = f"{normalized_turn_id}:iteration:{request.iteration}"
    return cast(dict[str, Any], enrich_event_context_with_turn_trace(context))


def resolve_tools_request_kind(*, execution_agent_id: str, execution_preset: str) -> str:
    agent_id = str(execution_agent_id or "").strip()
    normalized_intent = str(execution_preset or "").strip()
    if agent_id.startswith("worker_") or normalized_intent.startswith("worker_"):
        return "function_calling:worker_tools"
    return "function_calling:chat_tools"


def resolve_llm_timeout(
    timeout_seconds: float | None,
    *,
    thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
) -> float | None:
    if timeout_seconds is not None:
        return timeout_seconds
    if thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW):
        return THINKING_LLM_TIMEOUT_SECONDS
    return None


async def pre_poll_run_control(control: RunControl | None) -> None:
    if control is None:
        return
    if control.retract_signal.is_requested():
        raise RetractRaised(control.retract_signal.payload)
    if await control.cancel_token.is_cancelled():
        raise CancellationRaised(control.cancel_token.reason)


async def call_provider_with_tools(
    host: LlmInvocationHostProtocol,
    request: FunctionCallingLlmRequest,
    *,
    tools: list[dict[str, Any]],
) -> ToolsProviderCallResult:
    if get_stream_sink() is not None:
        stream_result: ToolStreamResult = await host._invoke_with_rate_limit_backoff(
            lambda: host.provider_bridge.chat_with_tools_stream(
                system_prompt=request.system_prompt,
                messages=request.messages,
                tools=tools,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=0.7,
                thinking_depth=request.thinking_depth,
                timeout_seconds=resolve_llm_timeout(
                    request.timeout_seconds,
                    thinking_depth=request.thinking_depth,
                ),
                event_context=build_llm_event_context(request),
            ),
            label="chat_with_tools_stream",
        )
        return ToolsProviderCallResult(
            provider_response=stream_result.provider_response,
            streamed=(
                not stream_result.has_tool_calls
                and stream_result.text_chunks_emitted > 0
            ),
        )

    provider_response = await host._invoke_with_rate_limit_backoff(
        lambda: host.provider_bridge.chat_with_tools(
            system_prompt=request.system_prompt,
            messages=request.messages,
            tools=tools,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=0.7,
            thinking_depth=request.thinking_depth,
            timeout_seconds=resolve_llm_timeout(
                request.timeout_seconds,
                thinking_depth=request.thinking_depth,
            ),
            event_context=build_llm_event_context(request),
        ),
        label="chat_with_tools",
    )
    return ToolsProviderCallResult(provider_response=provider_response, streamed=False)


async def call_provider_without_tools(
    host: LlmInvocationHostProtocol,
    request: FunctionCallingLlmRequest,
    *,
    json_mode: bool,
    control: RunControl | None,
) -> FinalProviderCallResult:
    if get_stream_sink() is not None and not json_mode:
        content = await _stream_final_response(host, request, control=control)
        return FinalProviderCallResult(content=content, provider_response=None, streamed=True)

    if control is not None:
        provider_response = await _call_final_response_with_control(
            host,
            request,
            json_mode=json_mode,
            control=control,
        )
    else:
        provider_response = await _call_final_response(host, request, json_mode=json_mode)
    return FinalProviderCallResult(
        content=provider_response.content,
        provider_response=provider_response,
        streamed=False,
    )


async def _stream_final_response(
    host: LlmInvocationHostProtocol,
    request: FunctionCallingLlmRequest,
    *,
    control: RunControl | None,
) -> str:
    chunks: list[str] = []
    if control is not None:
        cancellable = CancellableLLMClient(bridge=host.provider_bridge)
        async for event in cancellable.stream(
            system_prompt=request.system_prompt,
            messages=request.messages,
            control=control,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=0.7,
            thinking_depth=request.thinking_depth,
            timeout_seconds=resolve_llm_timeout(
                request.timeout_seconds,
                thinking_depth=request.thinking_depth,
            ),
            event_context=build_llm_event_context(request),
        ):
            if event.kind == "text_delta" and event.text:
                chunks.append(event.text)
        return "".join(chunks)

    async for event in host.provider_bridge.chat_response_stream(
        system_prompt=request.system_prompt,
        messages=request.messages,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=0.7,
        thinking_depth=request.thinking_depth,
        timeout_seconds=resolve_llm_timeout(
            request.timeout_seconds,
            thinking_depth=request.thinking_depth,
        ),
        event_context=build_llm_event_context(request),
    ):
        if event.kind == "text_delta" and event.text:
            chunks.append(event.text)
    return "".join(chunks)


async def _call_final_response_with_control(
    host: LlmInvocationHostProtocol,
    request: FunctionCallingLlmRequest,
    *,
    json_mode: bool,
    control: RunControl,
) -> Any:
    cancellable = CancellableLLMClient(bridge=host.provider_bridge)
    llm_result = await cancellable.call(
        system_prompt=request.system_prompt,
        messages=request.messages,
        control=control,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=0.7,
        thinking_depth=request.thinking_depth,
        json_mode=json_mode,
        timeout_seconds=resolve_llm_timeout(
            request.timeout_seconds,
            thinking_depth=request.thinking_depth,
        ),
        event_context=build_llm_event_context(request),
    )
    return SimpleNamespace(
        content=llm_result.content,
        metadata=llm_result.metadata,
        assistant_message=None,
        tool_calls=None,
    )


async def _call_final_response(
    host: LlmInvocationHostProtocol,
    request: FunctionCallingLlmRequest,
    *,
    json_mode: bool,
) -> Any:
    return await host._invoke_with_rate_limit_backoff(
        lambda: host.provider_bridge.chat_response(
            system_prompt=request.system_prompt,
            messages=request.messages,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=0.7,
            thinking_depth=request.thinking_depth,
            json_mode=json_mode,
            timeout_seconds=resolve_llm_timeout(
                request.timeout_seconds,
                thinking_depth=request.thinking_depth,
            ),
            event_context=build_llm_event_context(request),
        ),
        label="chat_response",
    )


__all__ = [
    "FinalProviderCallResult",
    "FunctionCallingLlmRequest",
    "LlmInvocationHostProtocol",
    "THINKING_LLM_TIMEOUT_SECONDS",
    "ToolsProviderCallResult",
    "call_provider_with_tools",
    "call_provider_without_tools",
    "pre_poll_run_control",
    "resolve_llm_timeout",
    "resolve_tools_request_kind",
]
