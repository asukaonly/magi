"""LLM invocation entry points for function-calling execution."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Dict, List, NamedTuple, Optional, Protocol, TypeVar, cast

from ....config.models import ThinkingDepth
from ....llm.base import LLMAdapter
from ....llm.model_context import automatic_output_reserve, unknown_model_context
from ....llm.output_limit import OutputLimitReached
from ....llm.streaming_events import LLMStreamEvent, emit_stream_event
from ....context.window_budget import build_context_window_budget, measure_provider_prompt_usage
from ....core.logger import get_logger

from ....llm.cancellable_client import (
    CancellationRaised,
    RetractRaised,
)
from ....llm.provider_bridge import LLMProviderBridge
from ..context_compactor import ContextCompactor
from ..task_budget import consume_task_llm_calls
from magi.control.run_control import RunControl
from .llm_invocation import (
    FinalProviderCallResult,
    FunctionCallingLlmRequest,
    LlmInvocationHostProtocol,
    ToolsProviderCallResult,
    call_provider_with_tools,
    call_provider_without_tools,
    pre_poll_run_control,
    resolve_llm_timeout,
    resolve_tools_request_kind,
)
from .llm_logging import (
    log_final_llm_failure,
    log_final_llm_request,
    log_final_llm_success,
    log_tools_llm_failure,
    log_tools_llm_request,
    log_tools_llm_success,
)
from .llm_payloads import build_llm_response_payload, build_llm_trace

_Result = TypeVar("_Result")
logger = get_logger(__name__)


class _LlmHostProtocol(Protocol):
    provider_bridge: LLMProviderBridge
    _context_compactor: ContextCompactor

    def _resolve_llm(self) -> LLMAdapter: ...

    async def _invoke_with_rate_limit_backoff(
        self,
        factory: Callable[[], Awaitable[Any]],
        *,
        label: str,
    ) -> Any: ...


class _PreparedLlmCall(NamedTuple):
    host: _LlmHostProtocol
    request_id: str
    start_time: float
    llm: LLMAdapter


@dataclass(frozen=True, slots=True)
class _ToolsLlmCallParams:
    system_prompt: str
    messages: List[Dict]
    tools: List[Dict]
    thinking_depth: ThinkingDepth
    timeout_seconds: Optional[float]
    session_id: Optional[str]
    turn_id: Optional[str]
    execution_preset: str
    execution_agent_id: str
    iteration: int | None
    control: RunControl | None


@dataclass(frozen=True, slots=True)
class _FinalLlmCallParams:
    system_prompt: str
    messages: List[Dict]
    thinking_depth: ThinkingDepth
    json_mode: bool
    timeout_seconds: Optional[float]
    session_id: Optional[str]
    turn_id: Optional[str]
    execution_preset: str
    execution_agent_id: str
    iteration: int | None
    control: RunControl | None


class FunctionCallingLlmMixin:
    """Call the configured LLM for tool and final-response turns."""

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        execution_preset: str = "unknown",
        execution_agent_id: str = "chat_agent",
        iteration: int | None = None,
        control: RunControl | None = None,
    ) -> Dict[str, Any]:
        """Call the provider with the current tool surface."""
        params = _ToolsLlmCallParams(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            thinking_depth=thinking_depth,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            turn_id=turn_id,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            iteration=iteration,
            control=control,
        )
        return await _call_llm_with_tools_params(self, params)

    async def _call_llm_without_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        execution_preset: str = "unknown",
        execution_agent_id: str = "chat_agent",
        iteration: int | None = None,
        control: RunControl | None = None,
    ) -> Dict[str, Any]:
        """Call the provider for the final assistant response."""
        params = _FinalLlmCallParams(
            system_prompt=system_prompt,
            messages=messages,
            thinking_depth=thinking_depth,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            turn_id=turn_id,
            execution_preset=execution_preset,
            execution_agent_id=execution_agent_id,
            iteration=iteration,
            control=control,
        )
        return await _call_llm_without_tools_params(self, params)

    @staticmethod
    def _resolve_llm_timeout(
        timeout_seconds: Optional[float],
        *,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
    ) -> Optional[float]:
        return resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth)

    def _build_llm_trace(
        self,
        *,
        metadata: Dict[str, Any] | None,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        duration_ms: int,
        model_name: str,
        provider_name: str,
    ) -> Dict[str, Any]:
        return build_llm_trace(
            metadata=metadata,
            thinking_depth=thinking_depth,
            duration_ms=duration_ms,
            model_name=model_name,
            provider_name=provider_name,
        )


async def _prepare_llm_call(
    owner: object,
    control: RunControl | None,
) -> _PreparedLlmCall:
    await pre_poll_run_control(control)
    host = cast(_LlmHostProtocol, owner)
    llm = host._resolve_llm()
    await consume_task_llm_calls()
    return _PreparedLlmCall(
        host=host,
        request_id=str(uuid.uuid4())[:8],
        start_time=time.time(),
        llm=llm,
    )


async def _call_llm_with_tools_params(
    owner: object,
    params: _ToolsLlmCallParams,
) -> Dict[str, Any]:
    prepared = await _prepare_llm_call(owner, params.control)
    model_name = prepared.llm.model_name
    request = _build_tools_request(prepared.request_id, params)

    log_tools_llm_request(
        request_id=prepared.request_id,
        model_name=model_name,
        system_prompt=params.system_prompt,
        messages=params.messages,
        tools=params.tools,
    )

    try:
        call_result = await _call_with_output_recovery(
            prepared, request, control=params.control, tools=params.tools,
            invoke=lambda attempt: call_provider_with_tools(
                cast(LlmInvocationHostProtocol, prepared.host), attempt, tools=params.tools,
            ),
        )
        duration_ms = _elapsed_ms(prepared.start_time)
        result = _build_tools_result(
            prepared=prepared,
            call_result=call_result,
            thinking_depth=params.thinking_depth,
            duration_ms=duration_ms,
        )
        log_tools_llm_success(
            request_id=prepared.request_id,
            result=result,
            duration_ms=duration_ms,
        )
        return result
    except Exception as exc:
        duration_ms = _elapsed_ms(prepared.start_time)
        log_tools_llm_failure(
            request_id=prepared.request_id,
            model_name=model_name,
            tools=params.tools,
            exc=exc,
            duration_ms=duration_ms,
        )
        raise


async def _call_llm_without_tools_params(
    owner: object,
    params: _FinalLlmCallParams,
) -> Dict[str, Any]:
    prepared = await _prepare_llm_call(owner, params.control)
    model_name = prepared.llm.model_name
    request = _build_final_response_request(prepared.request_id, params)

    log_final_llm_request(
        request_id=prepared.request_id,
        model_name=model_name,
        system_prompt=params.system_prompt,
        messages=params.messages,
    )

    try:
        call_result = await _call_with_output_recovery(
            prepared, request, control=params.control, tools=[],
            invoke=lambda attempt: call_provider_without_tools(
                cast(LlmInvocationHostProtocol, prepared.host), attempt,
                json_mode=params.json_mode, control=params.control,
            ),
        )
        duration_ms = _elapsed_ms(prepared.start_time)
        log_final_llm_success(
            request_id=prepared.request_id,
            content=call_result.content,
            duration_ms=duration_ms,
            metadata=_provider_response_metadata(call_result),
        )
        return _build_final_result(
            prepared=prepared,
            call_result=call_result,
            thinking_depth=params.thinking_depth,
            duration_ms=duration_ms,
        )
    except (CancellationRaised, RetractRaised):
        raise
    except Exception as exc:
        duration_ms = _elapsed_ms(prepared.start_time)
        log_final_llm_failure(
            request_id=prepared.request_id,
            exc=exc,
            duration_ms=duration_ms,
        )
        raise


async def _call_with_output_recovery(
    prepared: _PreparedLlmCall,
    request: FunctionCallingLlmRequest,
    *,
    control: RunControl | None,
    tools: list[dict[str, Any]],
    invoke: Callable[[FunctionCallingLlmRequest], Awaitable[_Result]],
) -> _Result:
    profile = getattr(prepared.host, "_active_model_context", None) or unknown_model_context(prepared.llm)
    budget = build_context_window_budget(profile)
    for attempt in range(3):
        try:
            return await invoke(request)
        except OutputLimitReached as exc:
            if attempt == 2:
                raise
            used = max(request.max_tokens or 0, exc.token_count("completion_tokens"))
            reserve = automatic_output_reserve(profile)
            next_limit = max(reserve, used * 2) if used else (profile.max_output_tokens or reserve * 2)
            usage = measure_provider_prompt_usage(
                budget, request.messages,
                prompt_overhead={"system_prompt": request.system_prompt, "tools": tools},
                observed_input_tokens=exc.token_count("prompt_tokens"),
            )
            next_limit = min(
                next_limit, profile.max_output_tokens or next_limit,
                budget.context_window - usage.estimated_tokens - 1_024,
            )
            if next_limit <= (used or reserve):
                raise
            await pre_poll_run_control(control)
            await consume_task_llm_calls()
            logger.warning(
                "Retrying truncated model generation",
                request_id=request.request_id, attempt=attempt + 1, max_tokens=next_limit,
            )
            # Regenerate only this model step; no partial tool call enters execution/history.
            await emit_stream_event(LLMStreamEvent(kind="text_reset", step_label="output_limit_retry"))
            request = replace(request, request_id=str(uuid.uuid4())[:8], max_tokens=next_limit)
    raise AssertionError("Output recovery loop exited without a result")


def _build_tools_request(
    request_id: str,
    params: _ToolsLlmCallParams,
) -> FunctionCallingLlmRequest:
    return FunctionCallingLlmRequest(
        request_id=request_id,
        request_kind=resolve_tools_request_kind(
            execution_agent_id=params.execution_agent_id,
            execution_preset=params.execution_preset,
        ),
        system_prompt=params.system_prompt,
        messages=params.messages,
        thinking_depth=params.thinking_depth,
        timeout_seconds=params.timeout_seconds,
        session_id=params.session_id,
        turn_id=params.turn_id,
        execution_agent_id=params.execution_agent_id,
        execution_preset=params.execution_preset,
        iteration=params.iteration,
    )


def _build_tools_result(
    *,
    prepared: _PreparedLlmCall,
    call_result: ToolsProviderCallResult,
    thinking_depth: ThinkingDepth,
    duration_ms: int,
) -> Dict[str, Any]:
    return build_llm_response_payload(
        provider_response=call_result.provider_response,
        content=call_result.provider_response.content,
        streamed=call_result.streamed,
        context_compactor=prepared.host._context_compactor,
        thinking_depth=thinking_depth,
        duration_ms=duration_ms,
        model_name=prepared.llm.model_name,
        provider_name=prepared.llm.provider_name,
    )


def _build_final_response_request(
    request_id: str,
    params: _FinalLlmCallParams,
) -> FunctionCallingLlmRequest:
    return FunctionCallingLlmRequest(
        request_id=request_id,
        request_kind="function_calling:final_response",
        system_prompt=params.system_prompt,
        messages=params.messages,
        thinking_depth=params.thinking_depth,
        timeout_seconds=params.timeout_seconds,
        session_id=params.session_id,
        turn_id=params.turn_id,
        execution_agent_id=params.execution_agent_id,
        execution_preset=params.execution_preset,
        iteration=params.iteration,
    )


def _provider_response_metadata(
    call_result: FinalProviderCallResult,
) -> Dict[str, Any]:
    if call_result.provider_response is None:
        return {}
    return dict(call_result.provider_response.metadata or {})


def _build_final_result(
    *,
    prepared: _PreparedLlmCall,
    call_result: FinalProviderCallResult,
    thinking_depth: ThinkingDepth,
    duration_ms: int,
) -> Dict[str, Any]:
    return build_llm_response_payload(
        provider_response=call_result.provider_response,
        content=call_result.content,
        streamed=call_result.streamed,
        context_compactor=prepared.host._context_compactor,
        thinking_depth=thinking_depth,
        duration_ms=duration_ms,
        model_name=prepared.llm.model_name,
        provider_name=prepared.llm.provider_name,
    )


def _elapsed_ms(start_time: float) -> int:
    return int((time.time() - start_time) * 1000)
