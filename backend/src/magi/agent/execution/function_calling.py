"""
Function Calling Orchestrator - LLM native function calling support

Handles tool execution using LLM's native function calling capability:
1. Builds tools parameter in OpenAI/Claude format
2. Parses tool call responses from LLM
3. Executes tools (local or skill-based)
4. Supports continuous tool calling loop
"""
import getpass
import json
import logging
import os
from typing import Callable, Dict, Any, List, Optional, TYPE_CHECKING

from ...llm.base import LLMAdapter
from ...llm.provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from ...llm.streaming_events import LLMStreamEvent, emit_stream_event, get_stream_sink
from ...chat.workspace import get_default_chat_workspace_path
from ...config.models import LLMScenario, ThinkingDepth
from ..cancel import CancelToken, null_cancel_token
from ..message_utils import append_latest_user_message
from ..run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    SteerInbox,
    SteerMessage,
    bind_detach_signal,
)
from ...runtime_trace import RuntimeTraceStore
from .context_compactor import ContextCompactor
from .function_calling_failures import FunctionCallingFailureMixin
from .function_calling_guardrails import FunctionCallingGuardrailsMixin
from .function_calling_llm import FunctionCallingLlmMixin
from .function_calling_messages import FunctionCallingMessageHistoryMixin
from .function_calling_permission import FunctionCallingPermissionMixin
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
from .function_calling_tracing import FunctionCallingTracingMixin
from .function_calling_types import ExecutionOutcome, ToolCall, ToolCallResult

if TYPE_CHECKING:
    from ...tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FunctionCallingOrchestrator(
    FunctionCallingFailureMixin,
    FunctionCallingGuardrailsMixin,
    FunctionCallingLlmMixin,
    FunctionCallingMessageHistoryMixin,
    FunctionCallingPermissionMixin,
    FunctionCallingResponseMixin,
    FunctionCallingTracingMixin,
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
        permission_gateway_provider: Callable[[], Any] | None = None,
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
        self._permission_gateway_provider = permission_gateway_provider
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

    def _build_tools_parameter(self, selected_tools: List[str]) -> List[Dict]:
        return build_tools_parameter(self.tool_registry, selected_tools)

    _build_tool_description = staticmethod(build_tool_description)

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

            gateway = self._resolve_permission_gateway()
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
