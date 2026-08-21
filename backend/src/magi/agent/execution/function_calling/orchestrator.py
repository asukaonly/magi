"""Function calling orchestrator host class."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, cast

from ....config.models import ThinkingDepth
from ....llm.base import LLMAdapter
from ....llm.provider_bridge import LLMProviderBridge
from ....runtime_trace import RuntimeTraceStore
from ...cancel import CancelToken
from ...message_utils import append_latest_user_message
from ....context.window_budget import ContextWindowUsage, build_context_window_budget
from ....llm.model_context import ResolvedModel, unknown_model_context
from ....tools.system_tools import resolve_resident_system_tools
from ...run.ports import AttachmentResolverPort, NullAttachmentResolver
from ...turn_input import UserTurnInput
from magi.control.run_control import (
    DetachSignal,
    OrchestratorSnapshot,
    RetractSignal,
    RunControl,
    SteerInbox,
    SuspendSignal,
    bind_detach_signal,
    null_run_control,
)
from ..context_compactor import ContextCompactor
from ..task_budget import (
    release_prepaid_task_llm_calls,
    task_execution_budget_scope,
)
from .failures import FunctionCallingFailureMixin
from .fallback import FunctionCallingFallbackMixin
from .guardrails import FunctionCallingGuardrailsMixin
from .llm import FunctionCallingLlmMixin
from .loop_runner import FunctionCallingLoopRunner
from .messages import FunctionCallingMessageHistoryMixin
from .permission import FunctionCallingPermissionMixin
from .postprocessor import FunctionCallingPostprocessor
from .responses import FunctionCallingResponseMixin
from .run_input import EngineRunInput
from .step_executor import (
    FunctionCallingStepExecutor,
    FunctionCallingStepState,
)
from .tool_expansion import apply_tool_expansion_from_results
from .tool_execution import FunctionCallingToolExecutionMixin
from .tools import (
    build_tool_description,
    build_tools_parameter,
)
from .tracing import FunctionCallingTracingMixin
from .types import ExecutionOutcome

if TYPE_CHECKING:
    from ....tools.registry import ToolRegistry
    from ....tools.context_routing import RouteDecision

logger = logging.getLogger(__name__)


class FunctionCallingOrchestrator(FunctionCallingFailureMixin):
    """
    Function Calling Orchestrator

    Manages tool execution using LLM's native function calling.
    Supports continuous tool calling with multi-turn conversations.
    """

    MAX_ITERATIONS = 30
    # Tool history we feed back into the LLM verbatim. Anything older than the
    # last few rounds is summarized; raw payloads stay full-fidelity for recent
    # turns where the LLM is most likely to reference them.
    _RAW_TOOL_HISTORY_LIMIT = 4
    # Hysteresis high-water mark: only compact once raw tool blocks reach this,
    # then reduce back to _RAW_TOOL_HISTORY_LIMIT in one batch. Between triggers
    # the tool history is append-only, so the request prefix stays byte-stable
    # and the provider prompt-cache keeps hitting through the loop; most tool
    # loops never reach this and so never break the cache (#100/P2b).
    _COMPACT_TRIGGER = 12
    # How many failed iterations we tolerate before forcing a re-plan. Two
    # gives the LLM one opportunity to self-correct without loop-thrashing.
    _FAILED_ITERATION_REPLAN_LIMIT = 2
    _REPEATED_BLOCKER_LIMIT = 2
    _RATE_LIMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)
    _MAX_TOOL_EXPANSIONS_PER_TURN = 1
    _MAX_TOOLS_PER_EXPANSION = 2
    _MAX_TOTAL_TOOLS_PER_TURN = 6
    _NON_REPLAN_ERROR_CODES = {
        "ACCESS_DENIED",
        "AUTH_REQUIRED",
        "CONTENT_INSPECTION_FAILED",
        "NO_PROVIDERS_CONFIGURED",
        "PERMISSION_DENIED",
        "POLICY_BLOCKED",
        "PROVIDER_CHALLENGE",
        "PROVIDER_NOT_CONFIGURED",
        "READ_ONLY",
        "REPEATED_FAILED_TOOL_CALL",
        "REPEATED_TOOL_BLOCKER",
        "ROLE_NOT_ALLOWED",
    }
    _TERMINAL_TOOL_ERROR_CODES = {
        "NO_PROVIDERS_CONFIGURED",
        "PROVIDER_CHALLENGE",
        "PROVIDER_NOT_CONFIGURED",
        "REPEATED_TOOL_BLOCKER",
    }
    _TRANSIENT_BLOCKER_ERROR_CODES = {
        "CANCELLED",
        "LLM_RATE_LIMIT",
        "RATE_LIMITED",
        "TIMEOUT",
        "WORKER_TIMEOUT",
    }
    _SUPPRESS_TOOL_AFTER_ERROR_CODES = {
        "NO_PROVIDERS_CONFIGURED",
        "PROVIDER_CHALLENGE",
        "PROVIDER_NOT_CONFIGURED",
    }
    _SLOW_SCAN_WARNING_SECONDS = 5.0
    # Parent-context budget passed down to spawned sub-tasks. 20 messages /
    # 12k chars is a UX-driven cap: it keeps prompts well under the smallest
    # supported model context while preserving enough conversational ground
    # truth for the worker to disambiguate references.
    _PARENT_CONTEXT_MAX_MESSAGES = 20
    _PARENT_CONTEXT_MAX_CHARS = 12_000

    def __init__(
        self,
        tool_registry: "ToolRegistry",
        llm_adapter: Optional[LLMAdapter] = None,
        active_model_provider: Callable[[], ResolvedModel] | None = None,
        skill_runner=None,
        tool_result_callback=None,
        loop_event_callback=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        scenario_llm_pool=None,
        permission_gateway: Any = None,
        permission_gateway_provider: Callable[[], Any] | None = None,
        attachment_resolver: AttachmentResolverPort | None = None,
    ):
        """
        Initialize the executor.

        Args:
            llm_adapter: LLM adapter.
            tool_registry: Tool registry.
            skill_runner: Optional skill runner for skill-based tools.
            scenario_llm_pool: ScenarioLLMPool for context compaction summariser.
            active_model_provider: Resolves the adapter and limits for this run.
        """
        self.llm = llm_adapter
        self._active_model_provider = active_model_provider
        self._active_model_context = unknown_model_context(llm_adapter)
        self.provider_bridge = LLMProviderBridge(llm_adapter) if llm_adapter else None
        self.postprocessor = FunctionCallingPostprocessor()
        self.tool_registry = tool_registry
        self.skill_runner = skill_runner
        self.tool_result_callback = tool_result_callback
        self.loop_event_callback = loop_event_callback
        self.runtime_trace_store = runtime_trace_store
        self.permission_gateway = permission_gateway
        self._permission_gateway_provider = permission_gateway_provider
        # Resolves managed attachment payloads at message-build time. Chat
        # wires a chat-backed resolver; non-chat callers (workers, sub-agents,
        # background tasks) leave this as a null resolver, preserving their
        # current behavior of never touching a chat read service.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._operations = _FunctionCallingOperations(self)
        self.step_executor = FunctionCallingStepExecutor(self)
        self._loop_runner = FunctionCallingLoopRunner(self)
        self._current_messages: List[Dict[str, Any]] = []
        self._context_compactor = ContextCompactor(
            scenario_llm_pool=scenario_llm_pool,
            budget_provider=lambda: build_context_window_budget(self._active_model_context),
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
        turn: UserTurnInput,
        system_prompt: str,
        selected_tools: List[str],
        conversation_history: List[Dict[str, Any]] | None = None,
        session_summary: str | None = None,
        session_origin: str | None = None,
        reply_context: Any | None = None,
        allow_attachment_grounding: bool = False,
        ephemeral_context: str | None = None,
    ) -> FunctionCallingStepState:
        """Build the initial loop state for step-wise function calling."""
        self._resolve_llm()
        self._context_compactor.begin_run()
        normalized_selected_tools = list(dict.fromkeys(selected_tools))
        messages = append_latest_user_message(
            conversation_history,
            turn,
            resolver=self._attachment_resolver,
            history_token_budget=None,
            session_summary=session_summary,
            session_origin=session_origin,
            reply_context=reply_context,
        )
        ephemeral_context_message_index: int | None = None
        ephemeral_context_original_content: Any | None = None
        context_text = str(ephemeral_context or "").strip()
        if context_text and messages and messages[-1].get("role") == "user":
            ephemeral_context_message_index = len(messages) - 1
            ephemeral_context_original_content = messages[-1].get("content")
            messages[-1]["content"] = self._append_ephemeral_context_to_content(
                ephemeral_context_original_content,
                context_text,
            )
        return FunctionCallingStepState(
            messages=messages,
            effective_system_prompt=self._augment_system_prompt(system_prompt),
            tools=self._build_tools_parameter(normalized_selected_tools),
            selected_tool_names=normalized_selected_tools,
            allow_attachment_grounding=allow_attachment_grounding,
            ephemeral_context_message_index=ephemeral_context_message_index,
            ephemeral_context_original_content=ephemeral_context_original_content,
        )

    @staticmethod
    def _append_ephemeral_context_to_content(content: Any, context_text: str) -> Any:
        context_block = (
            "--- LAUNCH CONTEXT SNAPSHOT ---\n"
            "Use this snapshot only to understand why this run was started. "
            "For later tool-loop decisions, rely on the assigned task and observed tool results.\n\n"
            f"{context_text}\n"
            "--- END LAUNCH CONTEXT SNAPSHOT ---"
        )
        if isinstance(content, list):
            return [*content, {"type": "text", "text": context_block}]
        text = str(content or "").strip()
        if not text:
            return context_block
        return f"{text}\n\n{context_block}"

    def _apply_tool_expansion_from_results(
        self,
        *,
        state: FunctionCallingStepState,
        tool_results: list[Any],
    ) -> list[str]:
        return apply_tool_expansion_from_results(
            self,
            state=state,
            tool_results=tool_results,
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
                UserTurnInput(
                    text=reminder,
                    attachments=list(attachments),
                    user_id=user_id,
                    session_id=session_id,
                ),
                resolver=self._attachment_resolver,
                history_token_budget=None,
                history_limit=max(len(messages), 1) + 1,
            ),
        )

    def _resolve_llm(self) -> LLMAdapter:
        if self._active_model_provider is not None:
            resolved = self._active_model_provider()
            llm = resolved.adapter
            self._active_model_context = resolved.context
            if llm is not self.llm:
                self.llm = llm
                self.provider_bridge = LLMProviderBridge(llm)
        if self.llm is None or self.provider_bridge is None:
            raise ValueError("FunctionCallingOrchestrator requires an LLM adapter or llm_pool")
        return self.llm

    async def execute_with_tools(
        self,
        turn: UserTurnInput,
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
        reply_context: Any | None = None,
        ephemeral_context: str | None = None,
        max_iterations: int = MAX_ITERATIONS,
        disable_thinking: bool = True,
        intent: str = "unknown",
        execution_agent_id: str = "chat_agent",
        execution_workspace: Optional[str] = None,
        llm_timeout_seconds: Optional[float] = None,
        final_response_json_mode: bool = False,
        thinking_depth: ThinkingDepth | None = None,
        cancel_token: CancelToken | None = None,
        steer_inbox: SteerInbox | None = None,
        detach_signal: DetachSignal | None = None,
        control: RunControl | None = None,
        route_decision: "RouteDecision | None" = None,
    ) -> ExecutionOutcome:
        """Execute with continuous tool calling.

        Either pass a ``control`` bundle (preferred) or the legacy trio of
        ``cancel_token`` / ``steer_inbox`` / ``detach_signal`` kwargs.  When
        ``control`` is supplied it takes precedence and the legacy kwargs are
        ignored; when only legacy kwargs are supplied they are folded into a
        fresh :func:`null_run_control` bundle via :meth:`_resolve_control`.
        """
        async with task_execution_budget_scope():
            try:
                effective = self._resolve_control(
                    control=control,
                    cancel_token=cancel_token,
                    steer_inbox=steer_inbox,
                    detach_signal=detach_signal,
                )
                with bind_detach_signal(effective.detach_signal):
                    return await self._execute_with_tools_impl(
                        turn=turn,
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
                        llm_timeout_seconds=llm_timeout_seconds,
                        conversation_history=conversation_history,
                        session_summary=session_summary,
                        session_origin=session_origin,
                        reply_context=reply_context,
                        ephemeral_context=ephemeral_context,
                        max_iterations=max_iterations,
                        thinking_depth=thinking_depth,
                        disable_thinking=disable_thinking,
                        final_response_json_mode=final_response_json_mode,
                        control=effective,
                        route_decision=route_decision,
                    )
            finally:
                await release_prepaid_task_llm_calls()

    async def run(self, run_input: "EngineRunInput") -> ExecutionOutcome:
        """Engine front door (ADR-0004 P4): run one bounded LLM↔tool run from a
        single typed :class:`EngineRunInput`.

        A pure adapter over :meth:`execute_with_tools` — it forwards every field
        verbatim (the parity test in
        ``tests/agent/execution/test_engine_run_input.py`` guarantees the field
        set always matches the method signature), so behavior and call-kwarg
        expectations are unchanged. New surfaces should build an
        ``EngineRunInput`` (or ``EngineRunInput.headless(...)``) and call this
        instead of hand-wiring the keyword arguments.
        """
        return await self.execute_with_tools(**run_input.to_execute_kwargs())

    async def _execute_with_tools_impl(
        self,
        *,
        turn: UserTurnInput,
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
        llm_timeout_seconds: Optional[float],
        conversation_history: Optional[List[Dict[str, Any]]],
        session_summary: str | None,
        session_origin: str | None,
        reply_context: Any | None,
        ephemeral_context: str | None,
        max_iterations: int,
        thinking_depth: Optional[ThinkingDepth],
        disable_thinking: bool,
        final_response_json_mode: bool,
        control: RunControl,
        route_decision: "RouteDecision | None" = None,
    ) -> ExecutionOutcome:
        return await self._loop_runner.run(
            EngineRunInput(
                turn=turn,
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
                llm_timeout_seconds=llm_timeout_seconds,
                conversation_history=conversation_history,
                session_summary=session_summary,
                session_origin=session_origin,
                reply_context=reply_context,
                ephemeral_context=ephemeral_context,
                max_iterations=max_iterations,
                disable_thinking=disable_thinking,
                final_response_json_mode=final_response_json_mode,
                thinking_depth=thinking_depth,
                control=control,
                route_decision=route_decision,
            ),
            control=control,
        )

    async def _prepare_context_for_model(
        self,
        state: FunctionCallingStepState,
        *,
        include_tools: bool = True,
    ) -> ExecutionOutcome | None:
        """Compact and re-measure the full prompt before a provider request."""
        usage = self._measure_context_usage(state, include_tools=include_tools)
        if usage.requires_compaction:
            compacted_tool_messages = self._compact_existing_tool_messages(state)
            if compacted_tool_messages:
                self._context_compactor.invalidate_recorded_usage()
                usage = self._measure_context_usage(state, include_tools=include_tools)
                await self._emit_loop_event(
                    {
                        "stage": "tool_message_context_compacted",
                        "iteration": state.iteration,
                        "message_count": compacted_tool_messages,
                        "estimated_tokens": usage.estimated_tokens,
                    }
                )
            if usage.requires_compaction:
                result = await self._context_compactor.compact(
                    state.messages,
                    state.effective_system_prompt,
                    preserve_user_turns=state.iteration == 0,
                )
                if result.compacted:
                    state.messages[:] = result.messages
                usage = self._measure_context_usage(state, include_tools=include_tools)

        if usage.fits_input_capacity:
            return None

        removed_tools = (
            self._drop_lower_priority_optional_tools_until_fit(state) if include_tools else []
        )
        if removed_tools:
            usage = self._measure_context_usage(state, include_tools=True)
            await self._emit_loop_event(
                {
                    "stage": "tool_context_reduced",
                    "iteration": state.iteration,
                    "removed_tools": removed_tools,
                    "remaining_tool_count": len(state.selected_tool_names),
                    "estimated_tokens": usage.estimated_tokens,
                }
            )
            if usage.fits_input_capacity:
                return None

        logger.warning(
            "[FunctionCalling] Prompt remains over model input capacity after compaction "
            "(estimated=%d capacity=%d iteration=%d)",
            usage.estimated_tokens,
            usage.input_capacity,
            state.iteration,
        )
        await self._emit_loop_event(
            {
                "stage": "context_window_exceeded",
                "iteration": state.iteration,
                "estimated_tokens": usage.estimated_tokens,
                "input_capacity": usage.input_capacity,
            }
        )
        return ExecutionOutcome(
            status="failed",
            content="",
            failure_reason="Context window exceeded",
            error_text=(
                f"Prompt estimated at {usage.estimated_tokens} tokens exceeds the "
                f"active model input capacity of {usage.input_capacity} tokens."
            ),
            tool_failures=list(state.tool_failures),
            iterations=state.iteration,
        )

    def _measure_context_usage(
        self,
        state: FunctionCallingStepState,
        *,
        include_tools: bool = True,
    ) -> ContextWindowUsage:
        return self._context_compactor.measure_usage(
            state.messages,
            prompt_overhead={
                "system_prompt": state.effective_system_prompt,
                "tools": state.tools if include_tools else [],
            },
        )

    def _compact_existing_tool_messages(self, state: FunctionCallingStepState) -> int:
        compacted_count = 0
        for message in state.messages:
            if message.get("role") not in {"tool", "tool_result"}:
                continue
            compacted, changed = self.postprocessor.compact_tool_message_content(
                message.get("content")
            )
            if changed:
                message["content"] = compacted
                compacted_count += 1
        return compacted_count

    def _drop_lower_priority_optional_tools_until_fit(
        self,
        state: FunctionCallingStepState,
    ) -> list[str]:
        resident_tools = set(resolve_resident_system_tools(self.tool_registry))
        optional_tools = [name for name in state.selected_tool_names if name not in resident_tools]
        removed: list[str] = []
        while len(optional_tools) > 1:
            tool_name = optional_tools.pop()
            state.selected_tool_names.remove(tool_name)
            removed.append(tool_name)
            state.tools = self._build_tools_parameter(state.selected_tool_names)
            self._context_compactor.invalidate_recorded_usage()
            if self._measure_context_usage(state).fits_input_capacity:
                break
        return removed

    async def _drop_ephemeral_context(self, state: FunctionCallingStepState) -> None:
        """Remove launch-only context after the first tool iteration."""
        index = state.ephemeral_context_message_index
        if index is None:
            return
        if index < 0 or index >= len(state.messages):
            state.ephemeral_context_message_index = None
            state.ephemeral_context_original_content = None
            return
        message = state.messages[index]
        if message.get("role") == "user":
            message["content"] = state.ephemeral_context_original_content
            await self._emit_loop_event(
                {
                    "stage": "ephemeral_context_dropped",
                    "iteration": state.iteration,
                }
            )
        state.ephemeral_context_message_index = None
        state.ephemeral_context_original_content = None

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

    def _build_retracted_outcome(
        self,
        state: FunctionCallingStepState,
        retract_signal: RetractSignal,
    ) -> ExecutionOutcome:
        """Assemble the ``retracted`` :class:`ExecutionOutcome` at a boundary.

        The snapshot is preserved so the DeliveryRouter can roll back any
        partial output that was streamed to the channel before the retract
        signal was observed.
        """
        payload = retract_signal.payload
        reason = payload.reason if payload is not None else "user_retract"
        note = payload.note if payload is not None else ""
        snapshot = OrchestratorSnapshot(
            messages=[dict(msg) for msg in state.messages],
            iterations=state.iteration,
            reason=reason,
            note=note,
        )
        logger.info(
            "[FunctionCalling] Retract signal observed at iteration=%s reason=%s",
            state.iteration,
            reason,
        )
        return ExecutionOutcome(
            status="retracted",
            content="",
            iterations=state.iteration,
            snapshot=snapshot,
        )

    def _build_suspended_outcome(
        self,
        state: FunctionCallingStepState,
        suspend_signal: SuspendSignal,
    ) -> ExecutionOutcome:
        """Assemble the ``suspended`` :class:`ExecutionOutcome` at a boundary.

        The snapshot is preserved so the kernel can persist in-progress state
        and the user can reattach to resume from the same point (Task 8+).
        """
        payload = suspend_signal.payload
        reason = payload.reason if payload is not None else "window_closed"
        note = payload.note if payload is not None else ""
        snapshot = OrchestratorSnapshot(
            messages=[dict(msg) for msg in state.messages],
            iterations=state.iteration,
            reason=reason,
            note=note,
        )
        logger.info(
            "[FunctionCalling] Suspend signal observed at iteration=%s reason=%s",
            state.iteration,
            reason,
        )
        return ExecutionOutcome(
            status="suspended",
            content="",
            iterations=state.iteration,
            snapshot=snapshot,
        )

    @staticmethod
    def _resolve_control(
        *,
        control: RunControl | None,
        cancel_token: CancelToken | None,
        steer_inbox: SteerInbox | None,
        detach_signal: DetachSignal | None,
    ) -> RunControl:
        """Bridge the legacy 3-kwarg API to the new :class:`RunControl` bundle.

        If ``control`` is supplied, use it directly (legacy kwargs are
        ignored — the bundle is canonical). Otherwise, build a fresh
        :func:`null_run_control` and overlay any non-None legacy kwargs.
        """
        if control is not None:
            return control
        bundle = null_run_control()
        if cancel_token is not None:
            bundle.cancel_token = cancel_token
        if steer_inbox is not None:
            bundle.steer_inbox = steer_inbox
        if detach_signal is not None:
            bundle.detach_signal = detach_signal
        return bundle

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
        if name not in {
            "_host",
            "__dict__",
            "__class__",
            "__getattribute__",
            "__getattr__",
        }:
            host = object.__getattribute__(self, "_host")
            override = host.__dict__.get(name)
            if override is not None:
                return override
        return object.__getattribute__(self, name)

    def __getattr__(self, name: str) -> Any:
        host = object.__getattribute__(self, "_host")
        return object.__getattribute__(host, name)


__all__ = ["FunctionCallingOrchestrator"]
