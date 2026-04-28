"""
Function Calling Orchestrator - LLM native function calling support

Handles tool execution using LLM's native function calling capability:
1. Builds tools parameter in OpenAI/Claude format
2. Parses tool call responses from LLM
3. Executes tools (local or skill-based)
4. Supports continuous tool calling loop
"""
import inspect
import json
import logging
import getpass
import os
import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING

from ...llm.base import LLMAdapter
from ...llm.provider_bridge import LLMProviderBridge, ToolStreamResult, _coerce_thinking_depth
from ...llm.streaming_events import LLMStreamEvent, emit_stream_event, get_stream_sink
from ...chat.workspace import get_default_chat_workspace_path
from ...config.models import LLMScenario, ThinkingDepth
from ...config.constants import DEFAULT_MAX_TOKENS
from ..cancel import CancelToken, null_cancel_token
from ..message_utils import append_latest_user_message
from ..run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    SteerInbox,
    SteerMessage,
    bind_detach_signal,
)
from ...runtime_trace import RuntimeTraceStore, TraceLlmCallRecord, TraceSpanRecord, TraceToolRecord
from .context_compactor import ContextCompactor
from .function_calling_failures import FunctionCallingFailureMixin
from .function_calling_guardrails import FunctionCallingGuardrailsMixin
from .function_calling_messages import FunctionCallingMessageHistoryMixin
from .function_calling_postprocessor import FunctionCallingPostprocessor
from .function_calling_responses import FunctionCallingResponseMixin
from .function_calling_step_executor import (
    FunctionCallingStepExecutor,
    FunctionCallingStepState,
)
from .function_calling_tools import (
    build_tool_description,
    build_tools_parameter,
    to_json_schema_type as _to_json_schema_type,
)
from .function_calling_types import ExecutionOutcome, ToolCall, ToolCallResult
from ...utils.llm_logger import get_llm_logger, log_llm_request, log_llm_response

if TYPE_CHECKING:
    from ...tools.registry import ToolRegistry

logger = logging.getLogger(__name__)
llm_logger = get_llm_logger('function_calling')

THINKING_LLM_TIMEOUT_SECONDS = 180.0


class FunctionCallingOrchestrator(
    FunctionCallingFailureMixin,
    FunctionCallingGuardrailsMixin,
    FunctionCallingMessageHistoryMixin,
    FunctionCallingResponseMixin,
):
    """
    Function Calling Orchestrator

    Manages tool execution using LLM's native function calling.
    Supports continuous tool calling with multi-turn conversations.
    """

    MAX_ITERATIONS = 30  # Maximum tool calls in a single loop
    _RAW_TOOL_HISTORY_LIMIT = 4
    _FAILED_ITERATION_REPLAN_LIMIT = 2
    # In-loop 429 backoff. The orchestrator-level retry in
    # ``task_orchestrator.LLM_RATE_LIMIT_*`` is still the last line of
    # defence for worker runs, but retrying *inside* the step loop avoids
    # throwing away tool results accumulated mid-run.
    _RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)
    _NON_REPLAN_ERROR_CODES = {
        "ACCESS_DENIED",
        "AUTH_REQUIRED",
        "NO_PROVIDERS_CONFIGURED",
        "PERMISSION_DENIED",
        "PROVIDER_NOT_CONFIGURED",
        "READ_ONLY",
        "ROLE_NOT_ALLOWED",
    }
    _SLOW_SCAN_WARNING_SECONDS = 5.0
    _PARENT_CONTEXT_MAX_MESSAGES = 20
    _PARENT_CONTEXT_MAX_CHARS = 12_000

    def __init__(
        self,
        tool_registry: "ToolRegistry",
        llm_adapter: Optional[LLMAdapter] = None,
        llm_pool=None,
        skill_runner=None,
        tool_result_callback=None,
        loop_event_callback=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        scenario_llm_pool=None,
        context_window: int | None = None,
        permission_gateway: Any = None,
    ):
        """
        initialize the executor

        Args:
            llm_adapter: LLM adapter
            tool_registry: Tool registry
            skill_runner: Optional skill runner for skill-based tools
            scenario_llm_pool: ScenarioLLMPool for context compaction summariser
            context_window: Context window size of the active model (tokens)
        """
        self.llm = llm_adapter
        self._llm_pool = llm_pool
        self.provider_bridge = LLMProviderBridge(llm_adapter) if llm_adapter else None
        self.postprocessor = FunctionCallingPostprocessor()
        self.tool_registry = tool_registry
        self.skill_runner = skill_runner
        self.tool_result_callback = tool_result_callback
        self.loop_event_callback = loop_event_callback
        self.runtime_trace_store = runtime_trace_store
        self.permission_gateway = permission_gateway
        self.step_executor = FunctionCallingStepExecutor(self)
        self._current_messages: List[Dict[str, Any]] = []
        self._context_compactor = ContextCompactor(
            scenario_llm_pool=scenario_llm_pool,
            context_window=context_window,
            on_event=loop_event_callback,
        )

    def build_step_state(
        self,
        *,
        user_message: str,
        system_prompt: str,
        selected_tools: List[str],
        conversation_history: List[Dict[str, Any]] | None = None,
        allow_attachment_grounding: bool = False,
    ) -> FunctionCallingStepState:
        """Build the initial loop state for step-wise function calling."""
        messages = append_latest_user_message(
            conversation_history,
            user_message,
            history_limit=10,
        )
        return FunctionCallingStepState(
            messages=messages,
            effective_system_prompt=self._augment_system_prompt(system_prompt),
            tools=self._build_tools_parameter(selected_tools),
            allow_attachment_grounding=allow_attachment_grounding,
        )

    def inject_prepared_attachment_grounding_message(
        self,
        *,
        messages: List[Dict[str, Any]],
        attachments: List[Dict[str, Any]],
        user_id: str | None,
        session_id: str | None,
    ) -> List[Dict[str, Any]]:
        if not attachments:
            return messages
        reminder = (
            "These prepared attachments will be sent with your response. "
            "Keep the text reply brief and confirmation-focused unless the user explicitly asks for commentary. "
            "If you mention them, use only details that are directly visible in the attached images "
            "or already confirmed by tool results. Do not guess location, identity, or scene details."
        )
        return append_latest_user_message(
            messages,
            reminder,
            history_limit=max(len(messages), 1) + 1,
            attachments=attachments,
            user_id=user_id,
            session_id=session_id,
        )

    def _resolve_llm(self) -> LLMAdapter:
        if self._llm_pool is not None:
            llm = self._llm_pool.get(LLMScenario.CORE)
            if llm is not self.llm:
                self.llm = llm
                self.provider_bridge = LLMProviderBridge(llm)
        if self.llm is None or self.provider_bridge is None:
            raise ValueError("FunctionCallingOrchestrator requires an LLM adapter or llm_pool")
        return self.llm

    async def execute_with_tools(
        self,
        user_message: str,
        system_prompt: str,
        selected_tools: List[str],
        user_id: str,
        session_id: Optional[str] = None,
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        turn_id: Optional[str] = None,
        conversation_history: List[Dict] = None,
        max_iterations: int = MAX_ITERATIONS,
        disable_thinking: bool = True,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
        execution_workspace: Optional[str] = None,
        orchestration_strategy: Optional[Dict[str, Any]] = None,
        llm_timeout_seconds: Optional[float] = None,
        final_response_json_mode: bool = False,
        thinking_depth: ThinkingDepth | None = None,
        cancel_token: CancelToken | None = None,
        steer_inbox: SteerInbox | None = None,
        detach_signal: DetachSignal | None = None,
    ) -> ExecutionOutcome:
        """
        Execute with continuous tool calling

        Args:
            user_message: User's message
            system_prompt: System prompt for LLM
            selected_tools: List of tool names to include
            user_id: User id for execution context
            conversation_history: Previous conversation
            max_iterations: Maximum tool call iterations
            cancel_token: Cooperative cancellation signal polled before each
                LLM/tool step. When ``await cancel_token.is_cancelled()``
                returns True the run is aborted and a ``cancelled``
                ExecutionOutcome is returned. Pass ``None`` (or omit) to
                opt out of cancellation.
            steer_inbox: Optional :class:`SteerInbox` drained at each tool
                boundary. Any enqueued :class:`SteerMessage` is appended as
                a ``user`` message before the next LLM call, allowing the
                chat layer to route mid-run follow-ups into the active
                orchestrator loop instead of superseding it.
            detach_signal: Optional :class:`DetachSignal` polled at each
                tool boundary. When the signal has been requested the
                orchestrator exits with ``status="detached"`` and a
                populated ``snapshot`` carrying the current messages so a
                background worker can resume from the same LLM turn.

        Returns:
            Structured execution outcome
        """
        with bind_detach_signal(detach_signal):
            return await self._execute_with_tools_impl(
                user_message=user_message,
                system_prompt=system_prompt,
                selected_tools=selected_tools,
                user_id=user_id,
                session_id=session_id,
                session_run_id=session_run_id,
                session_run_revision=session_run_revision,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
                execution_workspace=execution_workspace,
                orchestration_strategy=orchestration_strategy,
                llm_timeout_seconds=llm_timeout_seconds,
                conversation_history=conversation_history,
                max_iterations=max_iterations,
                thinking_depth=thinking_depth,
                disable_thinking=disable_thinking,
                final_response_json_mode=final_response_json_mode,
                cancel_token=cancel_token,
                steer_inbox=steer_inbox,
                detach_signal=detach_signal,
            )

    async def _execute_with_tools_impl(
        self,
        *,
        user_message: str,
        system_prompt: str,
        selected_tools: list[str],
        user_id: str,
        session_id: Optional[str],
        session_run_id: Optional[str],
        session_run_revision: int,
        turn_id: Optional[str],
        intent: Optional[str],
        execution_agent_id: Optional[str],
        execution_workspace: Optional[str],
        orchestration_strategy: Optional[str],
        llm_timeout_seconds: Optional[float],
        conversation_history: Optional[List[Dict[str, Any]]],
        max_iterations: int,
        thinking_depth: Optional[ThinkingDepth],
        disable_thinking: bool,
        final_response_json_mode: bool,
        cancel_token: CancelToken | None,
        steer_inbox: SteerInbox | None,
        detach_signal: DetachSignal | None,
    ) -> ExecutionOutcome:
        """Body of :meth:`execute_with_tools`. Runs inside the
        :func:`bind_detach_signal` context so tools executed during this
        run can observe the active :class:`DetachSignal` via
        :func:`current_detach_signal`."""
        token = cancel_token if cancel_token is not None else null_cancel_token()
        state = self.build_step_state(
            user_message=user_message,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            conversation_history=conversation_history,
        )
        self._current_messages = state.messages
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        while state.iteration < max_iterations:
            if await token.is_cancelled():
                return ExecutionOutcome(
                    status="cancelled",
                    content="",
                    iterations=state.iteration,
                )
            if steer_inbox is not None:
                await self.apply_steer_messages(state, steer_inbox)
            if detach_signal is not None and detach_signal.is_requested():
                return self._build_detached_outcome(state, detach_signal)
            step_outcome = await self.step_executor.execute_step(
                state=state,
                user_message=user_message,
                thinking_depth=depth,
                user_id=user_id,
                session_id=session_id,
                session_run_id=session_run_id,
                session_run_revision=session_run_revision,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
                execution_workspace=execution_workspace,
                orchestration_strategy=orchestration_strategy,
                llm_timeout_seconds=llm_timeout_seconds,
            )
            if step_outcome.status == "continue":
                # Flush any intermediate streamed text so the UI can close
                # the current bubble before tool execution continues.
                if get_stream_sink() is not None:
                    await emit_stream_event(LLMStreamEvent(kind="text_flush"))
                # --- context compaction check after each tool-use round ---
                await self._try_compact(state, system_prompt)
                continue
            if step_outcome.status == "completed":
                return ExecutionOutcome(
                    status="completed",
                    content=step_outcome.content,
                    tool_failures=list(state.tool_failures),
                    iterations=step_outcome.iteration,
                )
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason=step_outcome.failure_reason,
                tool_failures=list(state.tool_failures),
                iterations=step_outcome.iteration,
            )

        return await self._execute_fallback_final_response(
            state=state,
            thinking_depth=depth,
            user_id=user_id,
            session_id=session_id,
            session_run_id=session_run_id,
            session_run_revision=session_run_revision,
            turn_id=turn_id,
            intent=intent,
            execution_agent_id=execution_agent_id,
            execution_workspace=execution_workspace,
            orchestration_strategy=orchestration_strategy,
            llm_timeout_seconds=llm_timeout_seconds,
            final_response_json_mode=final_response_json_mode,
            cancel_token=token,
        )

    async def _try_compact(
        self,
        state: FunctionCallingStepState,
        system_prompt: str,
    ) -> None:
        """Check token usage and compact the message history if needed."""
        if not self._context_compactor.should_compact(state.messages):
            return
        result = await self._context_compactor.compact(state.messages, system_prompt)
        if result.compacted:
            state.messages[:] = result.messages

    async def apply_steer_messages(
        self,
        state: FunctionCallingStepState,
        steer_inbox: SteerInbox,
    ) -> None:
        """Drain ``steer_inbox`` and append each message to ``state.messages``.

        Public entry point used by the orchestrator's own tool loop and by
        chat execution handlers that drive the step executor directly.
        Each drained :class:`SteerMessage` becomes a single ``user`` message
        appended verbatim. Ordering matches the producer's push order.
        Empty-content messages are skipped to avoid polluting the history.
        """
        pending = await steer_inbox.drain()
        if not pending:
            return
        for message in pending:
            content = (message.content or "").strip()
            if not content:
                continue
            state.messages.append({"role": "user", "content": content})
            logger.info(
                "[FunctionCalling] Steer message injected at iteration=%s reason=%s",
                state.iteration,
                message.reason,
            )

    def _build_detached_outcome(
        self,
        state: FunctionCallingStepState,
        detach_signal: DetachSignal,
    ) -> ExecutionOutcome:
        """Assemble the ``detached`` :class:`ExecutionOutcome` at a boundary."""
        payload = detach_signal.payload
        reason = payload.reason if payload is not None else "detached"
        note = payload.note if payload is not None else ""
        snapshot = OrchestratorSnapshot(
            messages=[dict(msg) for msg in state.messages],
            iterations=state.iteration,
            reason=reason,
            note=note,
        )
        logger.info(
            "[FunctionCalling] Detach signal observed at iteration=%s reason=%s",
            state.iteration,
            reason,
        )
        return ExecutionOutcome(
            status="detached",
            content="",
            iterations=state.iteration,
            snapshot=snapshot,
        )

    async def _execute_fallback_final_response(
        self,
        *,
        state: FunctionCallingStepState,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        user_id: str,
        session_id: Optional[str],
        session_run_id: str | None,
        session_run_revision: int,
        turn_id: Optional[str],
        intent: str,
        execution_agent_id: str,
        execution_workspace: Optional[str],
        orchestration_strategy: Optional[Dict[str, Any]],
        llm_timeout_seconds: Optional[float],
        final_response_json_mode: bool,
        cancel_token: CancelToken | None = None,
    ) -> ExecutionOutcome:
        """Run the legacy no-tools fallback once the bounded step loop stops."""
        logger.info("[FunctionCalling] Reached max iterations, getting final response")
        token = cancel_token if cancel_token is not None else null_cancel_token()
        if await token.is_cancelled():
            return ExecutionOutcome(
                status="cancelled",
                content="",
                iterations=state.iteration,
            )
        await self._emit_loop_event(
            {
                "stage": "max_iterations_reached",
                "iteration": state.iteration,
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        try:
            final_system_prompt = self._build_final_response_system_prompt(state.effective_system_prompt)
            final_response = await self._call_llm_without_tools(
                system_prompt=final_system_prompt,
                messages=self._build_final_response_messages(state.messages),
                thinking_depth=thinking_depth,
                json_mode=final_response_json_mode,
                timeout_seconds=llm_timeout_seconds,
                session_id=session_id,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
            )
        except Exception as exc:
            error_text = self._format_exception_trace_text(exc)
            await self._complete_iteration_trace(
                turn_id=turn_id,
                iteration=state.iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=None,
                status="failed",
                error_text=error_text,
            )
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason=self._classify_exception_failure(exc),
                error_text=error_text,
                tool_failures=list(state.tool_failures),
                iterations=state.iteration,
            )

        # Some models return legacy <tool_call> blocks in fallback text-only responses.
        # Execute one bounded rescue pass so tool intents are not dropped silently.
        fallback_content = final_response.get("content", "")
        fallback_tool_calls = final_response.get("tool_calls") or []
        if fallback_tool_calls:
            logger.info(
                "[FunctionCalling] Fallback response returned %s tool call(s), executing rescue pass",
                len(fallback_tool_calls),
            )
            if fallback_content:
                self._append_message(state.messages, {"role": "assistant", "content": fallback_content})
            for tool_call in fallback_tool_calls:
                result = await self._execute_tool_call(
                    tool_call=tool_call,
                    user_id=user_id,
                    session_id=session_id,
                    session_run_id=session_run_id,
                    session_run_revision=session_run_revision,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                    execution_workspace=execution_workspace,
                    orchestration_strategy=orchestration_strategy,
                    user_message=None,
                )
                if not result.success:
                    state.tool_failures.append(
                        {
                            "tool_call_id": result.tool_call_id,
                            "tool_name": result.tool_name,
                            "error": result.error or "unknown error",
                            "error_code": result.error_code,
                            "execution_time": round(result.execution_time, 3),
                        }
                    )
                self._append_message(
                    state.messages,
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self.postprocessor.build_tool_message_payload(
                                tool_name=tool_call.name,
                                result=result,
                            ),
                            ensure_ascii=False,
                        ),
                    },
                )
                await self._persist_tool_trace(
                    turn_id=turn_id,
                    iteration=state.iteration,
                    execution_agent_id=execution_agent_id,
                    tool_call=tool_call,
                    result=result,
                )
            try:
                final_response = await self._call_llm_without_tools(
                    system_prompt=final_system_prompt,
                    messages=self._build_final_response_messages(state.messages, force_plain_text=True),
                    thinking_depth=thinking_depth,
                    json_mode=final_response_json_mode,
                    timeout_seconds=llm_timeout_seconds,
                    session_id=session_id,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                )
            except Exception as exc:
                error_text = self._format_exception_trace_text(exc)
                await self._complete_iteration_trace(
                    turn_id=turn_id,
                    iteration=state.iteration,
                    execution_agent_id=execution_agent_id,
                    started_at_ms=None,
                    status="failed",
                    error_text=error_text,
                )
                return ExecutionOutcome(
                    status="failed",
                    content="",
                    failure_reason=self._classify_exception_failure(exc),
                    error_text=error_text,
                    tool_failures=list(state.tool_failures),
                    iterations=state.iteration,
                )

        if final_response.get("tool_calls") and not str(final_response.get("content", "")).strip():
            logger.warning(
                "[FunctionCalling] Final no-tools response still returned tool calls; forcing plain-text retry"
            )
            await self._emit_loop_event(
                {
                    "stage": "fallback_forced_plain_text_retry",
                    "user_id": user_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "intent": intent,
                    "execution_agent_id": execution_agent_id,
                }
            )
            try:
                final_response = await self._call_llm_without_tools(
                    system_prompt=self._build_final_response_system_prompt(
                        state.effective_system_prompt,
                        strict_plain_text=True,
                    ),
                    messages=self._build_final_response_messages(state.messages, force_plain_text=True),
                    thinking_depth=ThinkingDepth.NONE,
                    json_mode=final_response_json_mode,
                    timeout_seconds=llm_timeout_seconds,
                    session_id=session_id,
                    turn_id=turn_id,
                    intent=intent,
                    execution_agent_id=execution_agent_id,
                )
            except Exception as exc:
                return ExecutionOutcome(
                    status="failed",
                    content="",
                    failure_reason=self._classify_exception_failure(exc),
                    error_text=self._format_exception_trace_text(exc),
                    tool_failures=list(state.tool_failures),
                    iterations=state.iteration,
                )

        await self._emit_loop_event(
            {
                "stage": "fallback_final_response",
                "response_preview": str(final_response.get("content", ""))[:500],
                "llm_trace": final_response.get("llm_trace"),
                "user_id": user_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "intent": intent,
                "execution_agent_id": execution_agent_id,
            }
        )
        await self._persist_llm_trace(
            turn_id=turn_id,
            iteration=state.iteration,
            stage="fallback_final_response",
            execution_agent_id=execution_agent_id,
            llm_trace=final_response.get("llm_trace"),
            response_preview=str(final_response.get("content", "")),
        )
        final_content = str(final_response.get("content", ""))
        if final_content.strip():
            await self._complete_iteration_trace(
                turn_id=turn_id,
                iteration=state.iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=None,
                status="completed",
                result_preview=final_content[:240],
            )
            return ExecutionOutcome(
                status="completed",
                content=final_content,
                tool_failures=list(state.tool_failures),
                iterations=state.iteration,
            )

        await self._complete_iteration_trace(
            turn_id=turn_id,
            iteration=state.iteration,
            execution_agent_id=execution_agent_id,
            started_at_ms=None,
            status="failed",
            error_text=self._classify_final_failure(state.tool_failures, state.all_tools_failed),
        )
        return ExecutionOutcome(
            status="failed",
            content="",
            failure_reason=self._classify_final_failure(state.tool_failures, state.all_tools_failed),
            tool_failures=list(state.tool_failures),
            iterations=state.iteration,
        )

    async def _emit_tool_result(
        self,
        user_id: str,
        session_id: Optional[str],
        turn_id: Optional[str],
        user_message: str,
        intent: str,
        iteration: int,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> None:
        """Emit tool execution result to external callback if provided."""
        if not self.tool_result_callback:
            return

        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "user_message": user_message,
            "intent": intent,
            "iteration": iteration,
            "tool_name": tool_call.name,
            "tool_call_id": tool_call.id,
            "arguments": tool_call.arguments,
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "error_code": result.error_code,
            "execution_time": result.execution_time,
        }

        try:
            callback_result = self.tool_result_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as e:
            logger.warning(f"[FunctionCalling] Tool result callback failed: {e}")

    async def _emit_loop_event(self, payload: Dict[str, Any]) -> None:
        """Emit function-calling loop stage event to external callback if provided."""
        if not self.loop_event_callback:
            return
        try:
            callback_result = self.loop_event_callback(payload)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception as e:
            logger.warning(f"[FunctionCalling] Loop event callback failed: {e}")

    async def _start_iteration_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
    ) -> int | None:
        normalized_turn_id = str(turn_id or "").strip()
        if self.runtime_trace_store is None or not normalized_turn_id:
            return None
        started_at_ms = int(time.time() * 1000)
        await self.runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="iteration",
                name=f"Iteration {iteration}",
                status="running",
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                started_at_ms=started_at_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=started_at_ms,
            )
        )
        return started_at_ms

    async def _complete_iteration_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
        started_at_ms: int | None,
        status: str,
        result_preview: str | None = None,
        error_text: str | None = None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self.runtime_trace_store is None or not normalized_turn_id or started_at_ms is None:
            return
        ended_at_ms = int(time.time() * 1000)
        await self.runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_root_span_id(normalized_turn_id),
                node_type="iteration",
                name=f"Iteration {iteration}",
                status=status,
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                result_preview=result_preview,
                error_text=error_text,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=max(0, ended_at_ms - started_at_ms),
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )

    async def _persist_llm_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        stage: str,
        execution_agent_id: str,
        llm_trace: Any,
        response_preview: str | None = None,
        request_preview: str | None = None,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self.runtime_trace_store is None or not normalized_turn_id or not isinstance(llm_trace, dict):
            return
        duration_ms = max(0, int(llm_trace.get("duration_ms") or 0))
        ended_at_ms = int(time.time() * 1000)
        started_at_ms = max(0, ended_at_ms - duration_ms)
        span_id = self._build_llm_span_id(normalized_turn_id, stage, iteration)
        await self.runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                node_type="llm_call",
                name="Function-calling LLM call",
                status="completed",
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                result_preview=(response_preview or "")[:240] or None,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self.runtime_trace_store.upsert_llm_call(
            TraceLlmCallRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                provider=str(llm_trace.get("provider") or "unknown"),
                model=str(llm_trace.get("model") or "unknown"),
                input_tokens=int(llm_trace.get("input_tokens") or 0),
                output_tokens=int(llm_trace.get("output_tokens") or 0),
                reasoning_tokens=int(llm_trace.get("reasoning_tokens") or 0),
                cache_read_tokens=int(llm_trace.get("cache_read_tokens") or 0),
                cache_write_tokens=int(llm_trace.get("cache_write_tokens") or 0),
                thinking_enabled=bool(llm_trace.get("thinking_enabled")),
                request_preview=(request_preview or "")[:240] or None,
                response_preview=(response_preview or "")[:240] or None,
            )
        )

    async def _persist_tool_trace(
        self,
        *,
        turn_id: str | None,
        iteration: int,
        execution_agent_id: str,
        tool_call: ToolCall,
        result: ToolCallResult,
    ) -> None:
        normalized_turn_id = str(turn_id or "").strip()
        if self.runtime_trace_store is None or not normalized_turn_id:
            return
        ended_at_ms = int(time.time() * 1000)
        duration_ms = max(0, int(round(float(result.execution_time or 0.0) * 1000)))
        started_at_ms = max(0, ended_at_ms - duration_ms)
        span_id = self._build_tool_span_id(normalized_turn_id, iteration, tool_call.id)
        result_preview = str(result.data or result.error or "")[:240] or None
        result_json_str: str | None = None
        if result.data is not None:
            try:
                result_json_str = json.dumps(result.data) if not isinstance(result.data, str) else result.data
            except (TypeError, ValueError):
                result_json_str = str(result.data)
        await self.runtime_trace_store.upsert_span(
            TraceSpanRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                parent_span_id=self._build_iteration_span_id(normalized_turn_id, iteration),
                node_type="tool_call",
                name=f"{tool_call.name} tool call",
                status="completed" if result.success else "failed",
                iteration=iteration,
                execution_agent_id=execution_agent_id,
                result_preview=result_preview,
                error_text=result.error,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                duration_ms=duration_ms,
                created_at_ms=started_at_ms,
                updated_at_ms=ended_at_ms,
            )
        )
        await self.runtime_trace_store.upsert_tool_call(
            TraceToolRecord(
                span_id=span_id,
                trace_id=self._build_trace_id(normalized_turn_id),
                turn_id=normalized_turn_id,
                tool_name=tool_call.name,
                tool_call_id=tool_call.id,
                arguments_json=json.dumps(tool_call.arguments),
                success=result.success,
                execution_time_ms=duration_ms,
                error_code=result.error_code,
                error_message=result.error,
                result_preview=result_preview,
                result_json=result_json_str,
            )
        )

    @staticmethod
    def _build_trace_id(turn_id: str) -> str:
        return f"trace:{turn_id}"

    @staticmethod
    def _build_root_span_id(turn_id: str) -> str:
        return f"{turn_id}:turn"

    @staticmethod
    def _build_iteration_span_id(turn_id: str, iteration: int) -> str:
        return f"{turn_id}:iteration:{iteration}"

    @staticmethod
    def _build_llm_span_id(turn_id: str, stage: str, iteration: int) -> str:
        return f"{turn_id}:llm_call:{stage}:{iteration}"

    @staticmethod
    def _build_tool_span_id(turn_id: str, iteration: int, tool_call_id: str) -> str:
        return f"{turn_id}:tool_call:{iteration}:{tool_call_id}"

    def _build_tools_parameter(self, selected_tools: List[str]) -> List[Dict]:
        return build_tools_parameter(self.tool_registry, selected_tools)

    _build_tool_description = staticmethod(build_tool_description)

    async def _call_llm_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        tools: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
    ) -> Dict[str, Any]:
        """
        Call LLM with tools parameter

        Returns dict with either:
        - content: str (text response)
        - tool_calls: List[ToolCall] (tool calls to execute)
        """
        import time
        import uuid

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        llm = self._resolve_llm()
        model_name = llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
            tool_count=len(tools),
            tool_names=[str(t.get("function", {}).get("name", "")) for t in tools],
        )

        try:
            streamed = False
            if get_stream_sink() is not None:
                stream_result: ToolStreamResult = await self._invoke_with_rate_limit_backoff(
                    lambda: self.provider_bridge.chat_with_tools_stream(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:tools",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_with_tools_stream",
                )
                provider_response = stream_result.provider_response
                streamed = not stream_result.has_tool_calls and stream_result.text_chunks_emitted > 0
            else:
                provider_response = await self._invoke_with_rate_limit_backoff(
                    lambda: self.provider_bridge.chat_with_tools(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:tools",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_with_tools",
                )

            duration_ms = int((time.time() - start_time) * 1000)
            result: Dict[str, Any] = {"content": provider_response.content}
            result["llm_trace"] = self._build_llm_trace(
                metadata=provider_response.metadata,
                thinking_depth=thinking_depth,
                duration_ms=duration_ms,
                model_name=model_name,
                provider_name=llm.provider_name,
            )
            self._context_compactor.record_input_tokens(
                int(result["llm_trace"].get("input_tokens") or 0)
            )
            context_usage = self._context_compactor.get_usage()
            if context_usage is not None:
                result["context_usage"] = context_usage
            if provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]
            if streamed:
                result["streamed"] = True

            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=json.dumps(result, ensure_ascii=False, default=str),
                success=True,
                duration_ms=duration_ms,
            )
            return result

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )
            logger.error(f"[FunctionCalling] LLM call failed: {e}")
            # Dump the tools schema once at error-time so provider 400s
            # (e.g. GLM 1210 "API 调用参数有误") can be diagnosed. ``tools``
            # is not in the default LLM request debug log because it can be
            # bulky; on failure the trade-off flips.
            try:
                tools_blob = json.dumps(tools, ensure_ascii=False, default=str)
                logger.error(
                    "[FunctionCalling] LLM call failed | request_id=%s | model=%s | tools=%s",
                    request_id,
                    model_name,
                    tools_blob if len(tools_blob) <= 8000 else tools_blob[:8000] + "…",
                )
            except Exception:  # pragma: no cover - logging must not mask the original error
                pass
            raise

    async def _call_llm_without_tools(
        self,
        system_prompt: str,
        messages: List[Dict],
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        json_mode: bool = False,
        timeout_seconds: Optional[float] = None,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
    ) -> Dict[str, Any]:
        """Call LLM without tools for final response"""
        import time
        import uuid

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        llm = self._resolve_llm()
        model_name = llm.model_name

        log_llm_request(
            llm_logger,
            request_id=request_id,
            model=model_name,
            system_prompt=system_prompt,
            messages=messages,
        )

        try:
            streamed = False
            if get_stream_sink() is not None and not json_mode:
                chunks: List[str] = []
                async for event in self.provider_bridge.chat_response_stream(
                    system_prompt=system_prompt,
                    messages=messages,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    temperature=0.7,
                    thinking_depth=thinking_depth,
                    timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                ):
                    if event.kind == "text_delta" and event.text:
                        chunks.append(event.text)
                content = "".join(chunks)
                streamed = True
                provider_response = None
            else:
                provider_response = await self._invoke_with_rate_limit_backoff(
                    lambda: self.provider_bridge.chat_response(
                        system_prompt=system_prompt,
                        messages=messages,
                        max_tokens=DEFAULT_MAX_TOKENS,
                        temperature=0.7,
                        thinking_depth=thinking_depth,
                        json_mode=json_mode,
                        timeout_seconds=self._resolve_llm_timeout(timeout_seconds, thinking_depth=thinking_depth),
                        event_context={
                            "request_id": request_id,
                            "request_kind": "function_calling:final_response",
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "agent_id": execution_agent_id,
                            "correlation_id": turn_id,
                            "intent": intent,
                        },
                    ),
                    label="chat_response",
                )
                content = provider_response.content

            duration_ms = int((time.time() - start_time) * 1000)
            metadata = dict((provider_response.metadata if provider_response else None) or {})
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response=content,
                success=True,
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
                **metadata,
            )
            result: Dict[str, Any] = {"content": content}
            result["llm_trace"] = self._build_llm_trace(
                metadata=provider_response.metadata if provider_response else None,
                thinking_depth=thinking_depth,
                duration_ms=duration_ms,
                model_name=model_name,
                provider_name=llm.provider_name,
            )
            self._context_compactor.record_input_tokens(
                int(result["llm_trace"].get("input_tokens") or 0)
            )
            context_usage = self._context_compactor.get_usage()
            if context_usage is not None:
                result["context_usage"] = context_usage
            if provider_response is not None and provider_response.assistant_message:
                result["assistant_message"] = provider_response.assistant_message
            if provider_response is not None and provider_response.tool_calls:
                result["tool_calls"] = [
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=tc.arguments,
                    )
                    for tc in provider_response.tool_calls
                ]
            if streamed:
                result["streamed"] = True
            return result
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            log_llm_response(
                llm_logger,
                request_id=request_id,
                response="",
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                fallback_reason="function_calling_final_response_without_tools",
            )
            raise

    @staticmethod
    def _resolve_llm_timeout(timeout_seconds: Optional[float], *, thinking_depth: ThinkingDepth = ThinkingDepth.NONE) -> Optional[float]:
        if timeout_seconds is not None:
            return timeout_seconds
        if thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW):
            return THINKING_LLM_TIMEOUT_SECONDS
        return None

    def _build_llm_trace(
        self,
        *,
        metadata: Dict[str, Any] | None,
        thinking_depth: ThinkingDepth = ThinkingDepth.NONE,
        duration_ms: int,
        model_name: str,
        provider_name: str,
    ) -> Dict[str, Any]:
        trace_metrics = dict((metadata or {}).get("trace_metrics") or {})
        trace_metrics.setdefault("provider", provider_name)
        trace_metrics.setdefault("model", model_name)
        trace_metrics.setdefault("input_tokens", 0)
        trace_metrics.setdefault("output_tokens", 0)
        trace_metrics.setdefault("total_tokens", 0)
        trace_metrics.setdefault("reasoning_tokens", 0)
        trace_metrics.setdefault("cache_read_tokens", 0)
        trace_metrics.setdefault("cache_write_tokens", 0)
        trace_metrics.setdefault("thinking_enabled", thinking_depth not in (ThinkingDepth.NONE, ThinkingDepth.LOW))
        trace_metrics.setdefault("thinking_depth", thinking_depth.value)
        trace_metrics.setdefault("duration_ms", duration_ms)
        return trace_metrics

    async def _execute_tool_call(
        self,
        tool_call: ToolCall,
        user_id: str,
        session_id: Optional[str],
        turn_id: Optional[str],
        intent: str,
        execution_agent_id: str,
        execution_workspace: Optional[str],
        orchestration_strategy: Optional[Dict[str, Any]],
        session_run_id: str | None = None,
        session_run_revision: int = 0,
        user_message: str | None = None,
    ) -> ToolCallResult:
        """
        Execute a single tool call

        Args:
            tool_call: Tool call to execute
            user_id: User id for context

        Returns:
            ToolCallResult
        """
        import time
        start_time = time.time()

        tool_name = tool_call.name
        arguments = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
        workspace_root = self._resolve_execution_workspace(execution_workspace)

        try:
            from ...tools.schema import ToolExecutionContext, ToolErrorCode

            # Check if it's a skill
            if tool_name.startswith("skill_"):
                skill_name = tool_name.replace("skill_", "")
                return await self._execute_skill(
                    skill_name=skill_name,
                    arguments=arguments,
                    user_id=user_id,
                    execution_workspace=execution_workspace,
                )

            # Regular tool
            arguments, guardrail_error = self._apply_worker_explore_guardrails(
                intent=intent,
                tool_name=tool_name,
                arguments=arguments,
                execution_workspace=execution_workspace,
                user_message=user_message,
            )
            if guardrail_error:
                guardrail_error_code = self._classify_guardrail_error_code(
                    tool_name=tool_name,
                    error_text=guardrail_error,
                )
                logger.warning(
                    "[FunctionCalling] Blocked by guardrail: %s | intent=%s | workspace=%s | args=%s | reason=%s",
                    tool_name,
                    intent,
                    workspace_root,
                    arguments,
                    guardrail_error,
                )
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=False,
                    error=guardrail_error,
                    error_code=guardrail_error_code,
                    execution_time=time.time() - start_time,
                )

            permissions = ["authenticated"]
            tool_info = self.tool_registry.get_tool_info(tool_name)
            if tool_info and tool_info.get("dangerous", False):
                permissions.append("dangerous_tools")
            normalized_session_id = str(session_id or "").strip()
            target_task_agent_id = normalized_session_id or user_id

            context = ToolExecutionContext(
                agent_id=execution_agent_id,
                workspace=workspace_root,
                env_vars={
                    "user_id": user_id,
                    "session_id": session_id or "",
                    "turn_id": turn_id or "",
                    "intent": intent,
                    "run_id": session_run_id or "",
                    "run_revision": str(session_run_revision),
                    "target_task_agent_type": "chat",
                    "target_task_agent_id": target_task_agent_id,
                },
                permissions=permissions,
            )

            if tool_name == "agent":
                arguments = self._normalize_agent_launch_arguments(
                    arguments=arguments,
                    orchestration_strategy=orchestration_strategy,
                )

            # Permission gateway — resolved in priority order:
            #   1. instance-level (explicit ctor kwarg; used by tests
            #      and bespoke wirings),
            #   2. the DI container binding set up by the control-plane
            #      bootstrap module in production.
            # When neither is available the call stays ungated, which
            # is the exact zero-behavior-change path the rest of the
            # codebase assumes.
            gateway = self.permission_gateway
            if gateway is None:
                try:
                    from ...core.runtime_bindings import require_permission_gateway

                    gateway = require_permission_gateway()
                except Exception:
                    gateway = None
            if gateway is not None:
                denied_result = await self._gate_tool_call(
                    tool_call=tool_call,
                    tool_name=tool_name,
                    arguments=arguments,
                    agent_id=execution_agent_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    workspace=context.workspace,
                    intent=intent,
                    start_time=start_time,
                    gateway=gateway,
                )
                if denied_result is not None:
                    return denied_result

            if tool_name in self._FILE_SCAN_TOOLS:
                logger.info(
                    "[FunctionCalling] Executing scan tool: %s | workspace=%s | path=%s | args=%s",
                    tool_name,
                    workspace_root,
                    self._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    arguments,
                )
            else:
                logger.info(f"[FunctionCalling] Executing: {tool_name} with args: {arguments}")
            result = await self.tool_registry.execute(tool_name, arguments, context)
            execution_time = time.time() - start_time
            if not result.success:
                logger.warning(
                    f"[FunctionCalling] Tool failed: {tool_name} | "
                    f"error={result.error} | code={result.error_code}"
                )
            if (
                tool_name in self._FILE_SCAN_TOOLS
                and execution_time >= self._SLOW_SCAN_WARNING_SECONDS
            ):
                logger.warning(
                    "[FunctionCalling] Slow scan tool: %s | workspace=%s | path=%s | elapsed_ms=%.1f | args=%s",
                    tool_name,
                    workspace_root,
                    self._resolve_scan_root_path(arguments.get("path"), execution_workspace),
                    execution_time * 1000,
                    arguments,
                )

            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=result.success,
                data=result.data,
                error=result.error,
                error_code=getattr(result, "error_code", None),
                execution_time=execution_time,
            )

        except Exception as e:
            logger.error(f"[FunctionCalling] Tool execution error: {e}")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def _gate_tool_call(
        self,
        *,
        tool_call: ToolCall,
        tool_name: str,
        arguments: Dict[str, Any],
        agent_id: str,
        session_id: Optional[str],
        turn_id: Optional[str],
        workspace: Optional[str],
        intent: str,
        start_time: float,
        gateway: Any = None,
    ) -> Optional[ToolCallResult]:
        """Run the permission gateway; return a failure result if blocked.

        Returns ``None`` when the gateway allows the call (the caller
        proceeds to registry execution); otherwise returns a populated
        :class:`ToolCallResult` whose error text the LLM will see.
        """
        try:
            from ..control.permission import (
                PermissionOutcome,
                ToolOrigin,
            )
            from ...tools.schema import ToolErrorCode
        except Exception as exc:  # defensive — should never fire post-wiring
            logger.error(f"[FunctionCalling] permission gateway import failed: {exc}")
            return None

        tool_info = self.tool_registry.get_tool_info(tool_name) or {}
        origin = (
            ToolOrigin.SUBAGENT
            if isinstance(intent, str) and intent.startswith("worker_")
            else ToolOrigin.CHAT
        )

        try:
            gate = gateway if gateway is not None else self.permission_gateway
            decision = await gate.gate(
                tool_name=tool_name,
                arguments=arguments,
                agent_id=agent_id,
                origin=origin,
                session_id=session_id,
                turn_id=turn_id,
                workspace=workspace,
                tool_is_dangerous=bool(tool_info.get("dangerous", False)),
            )
        except Exception as exc:
            logger.exception("[FunctionCalling] permission gateway raised")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                error=f"permission gateway error: {exc}",
                error_code=ToolErrorCode.PERMISSION_DENIED.value,
                execution_time=time.time() - start_time,
            )

        if decision.allowed:
            return None

        # Translate the decision into an LLM-visible error message.
        if decision.outcome is PermissionOutcome.KILL_LISTED:
            message = (
                f"This invocation is blocked by the system safety fuse: "
                f"{decision.reason or 'kill-listed pattern'}. Rephrase your "
                f"approach — do not retry this exact command."
            )
        elif decision.outcome is PermissionOutcome.TIMED_OUT:
            message = (
                "The user did not respond to the permission prompt in time; "
                "the call was not executed. Ask the user how they want to proceed."
            )
        elif decision.outcome is PermissionOutcome.DENIED:
            if decision.source == "plan_mode":
                message = (
                    decision.reason
                    or "plan mode is active: only read-only tools are allowed"
                )
            else:
                message = (
                    f"The user denied this tool invocation"
                    + (f": {decision.reason}" if decision.reason else "")
                    + ". Respect the decision and choose a different approach."
                )
        else:
            message = f"permission gateway blocked the call ({decision.outcome.value})"

        logger.info(
            "[FunctionCalling] permission blocked tool=%s outcome=%s source=%s",
            tool_name,
            decision.outcome.value,
            decision.source,
        )
        return ToolCallResult(
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            success=False,
            error=message,
            error_code=ToolErrorCode.PERMISSION_DENIED.value,
            execution_time=time.time() - start_time,
        )

    async def _execute_skill(
        self,
        skill_name: str,
        arguments: Dict[str, Any],
        user_id: str,
        execution_workspace: Optional[str] = None,
    ) -> ToolCallResult:
        """Execute a skill"""
        if not self.skill_runner:
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error="Skill runner not available",
            )

        workspace_root = self._resolve_execution_workspace(execution_workspace)
        skill_context = {
            "user_id": user_id,
            "session_id": f"session_{user_id}",
            "workspace": workspace_root,
            "env_vars": {
                "user": getpass.getuser(),
                "HOME": os.path.expanduser("~"),
                "PWD": workspace_root,
            },
        }

        try:
            # Convert arguments dict to list for the skill runner
            args_list = []
            if arguments:
                for key, value in arguments.items():
                    if isinstance(value, str):
                        args_list.append(value)
                    elif value is not None:
                        args_list.append(str(value))

            result = await self.skill_runner.execute(
                skill_name=skill_name,
                arguments=args_list,
                context=skill_context,
            )

            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=result.success,
                data=result.content,
                error=result.error,
            )

        except Exception as e:
            logger.error(f"[FunctionCalling] Skill execution error: {e}")
            return ToolCallResult(
                tool_call_id="",
                tool_name=skill_name,
                success=False,
                error=str(e),
            )
