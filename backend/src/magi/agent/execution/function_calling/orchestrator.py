"""Function calling orchestrator host class."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, cast

from ....config.models import LLMScenario, ThinkingDepth
from ....llm.base import LLMAdapter
from ....llm.provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from ....llm.streaming_events import LLMStreamEvent, emit_stream_event, get_stream_sink
from ....runtime_trace import RuntimeTraceStore
from ...cancel import CancelToken, null_cancel_token
from ...message_utils import append_latest_user_message
from ...run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    SteerInbox,
    bind_detach_signal,
)
from ..context_compactor import ContextCompactor
from .failures import FunctionCallingFailureMixin
from .fallback import FunctionCallingFallbackMixin
from .guardrails import FunctionCallingGuardrailsMixin
from .llm import FunctionCallingLlmMixin
from .messages import FunctionCallingMessageHistoryMixin
from .permission import FunctionCallingPermissionMixin
from .postprocessor import FunctionCallingPostprocessor
from .responses import FunctionCallingResponseMixin
from .step_executor import (
    FunctionCallingStepExecutor,
    FunctionCallingStepState,
)
from .tool_execution import FunctionCallingToolExecutionMixin
from .tools import (
    build_tool_description,
    build_tools_parameter,
)
from .tracing import FunctionCallingTracingMixin
from .types import ExecutionOutcome

if TYPE_CHECKING:
    from ....tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FunctionCallingOrchestrator(FunctionCallingFailureMixin):
    """
    Function Calling Orchestrator

    Manages tool execution using LLM's native function calling.
    Supports continuous tool calling with multi-turn conversations.
    """

    MAX_ITERATIONS = 30
    _RAW_TOOL_HISTORY_LIMIT = 4
    _FAILED_ITERATION_REPLAN_LIMIT = 2
    _RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)
    _NON_REPLAN_ERROR_CODES = {
        "ACCESS_DENIED",
        "AUTH_REQUIRED",
        "NO_PROVIDERS_CONFIGURED",
        "PERMISSION_DENIED",
        "POLICY_BLOCKED",
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
        Initialize the executor.

        Args:
            llm_adapter: LLM adapter.
            tool_registry: Tool registry.
            skill_runner: Optional skill runner for skill-based tools.
            scenario_llm_pool: ScenarioLLMPool for context compaction summariser.
            context_window: Context window size of the active model.
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
        self._operations = _FunctionCallingOperations(self)
        self.step_executor = FunctionCallingStepExecutor(self)
        self._current_messages: List[Dict[str, Any]] = []
        self._context_compactor = ContextCompactor(
            scenario_llm_pool=scenario_llm_pool,
            context_window=context_window,
            on_event=loop_event_callback,
        )

    def __getattr__(self, name: str) -> Any:
        operations = self.__dict__.get("_operations")
        if operations is not None:
            try:
                return object.__getattribute__(operations, name)
            except AttributeError:
                pass
        raise AttributeError(f"{type(self).__name__!s} object has no attribute {name!r}")

    def build_step_state(
        self,
        *,
        user_message: str,
        system_prompt: str,
        selected_tools: List[str],
        conversation_history: List[Dict[str, Any]] | None = None,
        session_summary: str | None = None,
        session_origin: str | None = None,
        allow_attachment_grounding: bool = False,
    ) -> FunctionCallingStepState:
        """Build the initial loop state for step-wise function calling."""
        messages = append_latest_user_message(
            conversation_history,
            user_message,
            session_summary=session_summary,
            session_origin=session_origin,
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
        return cast(
            List[Dict[str, Any]],
            append_latest_user_message(
                messages,
                reminder,
                history_limit=max(len(messages), 1) + 1,
                attachments=attachments,
                user_id=user_id,
                session_id=session_id,
            ),
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
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        session_summary: str | None = None,
        session_origin: str | None = None,
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
        """Execute with continuous tool calling."""
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
                session_summary=session_summary,
                session_origin=session_origin,
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
        intent: str,
        execution_agent_id: str,
        execution_workspace: Optional[str],
        orchestration_strategy: Optional[Dict[str, Any]],
        llm_timeout_seconds: Optional[float],
        conversation_history: Optional[List[Dict[str, Any]]],
        session_summary: str | None,
        session_origin: str | None,
        max_iterations: int,
        thinking_depth: Optional[ThinkingDepth],
        disable_thinking: bool,
        final_response_json_mode: bool,
        cancel_token: CancelToken | None,
        steer_inbox: SteerInbox | None,
        detach_signal: DetachSignal | None,
    ) -> ExecutionOutcome:
        token = cancel_token if cancel_token is not None else null_cancel_token()
        state = self.build_step_state(
            user_message=user_message,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            conversation_history=conversation_history,
            session_summary=session_summary,
            session_origin=session_origin,
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
                if get_stream_sink() is not None:
                    await emit_stream_event(LLMStreamEvent(kind="text_flush"))
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

        return cast(
            ExecutionOutcome,
            await self._execute_fallback_final_response(
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
            ),
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
        """Drain ``steer_inbox`` and append each message to ``state.messages``."""
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

    def _build_tools_parameter(self, selected_tools: List[str]) -> List[Dict]:
        return build_tools_parameter(self.tool_registry, selected_tools)

    _build_tool_description = staticmethod(build_tool_description)


class _FunctionCallingOperations(
    FunctionCallingFailureMixin,
    FunctionCallingFallbackMixin,
    FunctionCallingGuardrailsMixin,
    FunctionCallingLlmMixin,
    FunctionCallingMessageHistoryMixin,
    FunctionCallingPermissionMixin,
    FunctionCallingResponseMixin,
    FunctionCallingToolExecutionMixin,
    FunctionCallingTracingMixin,
):
    def __init__(self, host: FunctionCallingOrchestrator) -> None:
        self._host = host

    def __getattribute__(self, name: str) -> Any:
        if name not in {"_host", "__dict__", "__class__", "__getattribute__", "__getattr__"}:
            host = object.__getattribute__(self, "_host")
            override = host.__dict__.get(name)
            if override is not None:
                return override
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        host = object.__getattribute__(self, "_host")
        return object.__getattribute__(host, name)


__all__ = ["FunctionCallingOrchestrator"]
