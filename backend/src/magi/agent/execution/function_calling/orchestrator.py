"""Function calling orchestrator host class."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, cast

from ....config.models import LLMScenario, ThinkingDepth
from ....llm.base import LLMAdapter
from ....llm.provider_bridge import LLMProviderBridge, _coerce_thinking_depth
from ....llm.streaming_events import LLMStreamEvent, emit_stream_event, get_stream_sink
from ....runtime_trace import RuntimeTraceStore
from ...cancel import CancelToken
from ...message_utils import append_latest_user_message
from ...run.ports import AttachmentResolverPort, NullAttachmentResolver
from ...turn_input import UserTurnInput
from ...run_control import (
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
    from ....tools.context_routing import RouteDecision
    from .run_input import EngineRunInput

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
        "ROLE_NOT_ALLOWED",
    }
    _TERMINAL_TOOL_ERROR_CODES = {
        "NO_PROVIDERS_CONFIGURED",
        "PROVIDER_CHALLENGE",
        "PROVIDER_NOT_CONFIGURED",
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
        llm_pool=None,
        skill_runner=None,
        tool_result_callback=None,
        loop_event_callback=None,
        runtime_trace_store: RuntimeTraceStore | None = None,
        scenario_llm_pool=None,
        context_window: int | None = None,
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
        # Resolves managed attachment payloads at message-build time. Chat
        # wires a chat-backed resolver; non-chat callers (workers, sub-agents,
        # background tasks) leave this as a null resolver, preserving their
        # current behavior of never touching a chat read service.
        self._attachment_resolver = attachment_resolver or NullAttachmentResolver()
        self._operations = _FunctionCallingOperations(self)
        self.step_executor = FunctionCallingStepExecutor(self)
        self._current_messages: List[Dict[str, Any]] = []
        self._context_compactor = ContextCompactor(
            scenario_llm_pool=scenario_llm_pool,
            context_window=context_window or self._resolve_context_window(scenario_llm_pool),
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

    @staticmethod
    def _resolve_context_window(scenario_llm_pool: Any | None) -> int | None:
        if scenario_llm_pool is None:
            return None
        resolver = getattr(scenario_llm_pool, "context_window_for", None)
        if not callable(resolver):
            return None
        try:
            value = resolver(LLMScenario.CORE)
        except Exception:
            return None
        return value if isinstance(value, int) and value > 0 else None

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
        normalized_selected_tools = list(dict.fromkeys(selected_tools))
        messages = append_latest_user_message(
            conversation_history,
            turn,
            resolver=self._attachment_resolver,
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
        if state.tool_expansion_count >= self._MAX_TOOL_EXPANSIONS_PER_TURN:
            return []
        if not tool_results:
            return []

        raw_append_tools: list[str] = []
        for result in tool_results:
            if not getattr(result, "success", False):
                continue
            data = getattr(result, "data", None)
            if not isinstance(data, dict):
                continue
            expansion = data.get("tool_expansion")
            if not isinstance(expansion, dict):
                continue
            append_tools = expansion.get("append_tools")
            if not isinstance(append_tools, list):
                continue
            raw_append_tools.extend(str(item or "").strip() for item in append_tools)

        if not raw_append_tools:
            return []

        available_slots = max(0, self._MAX_TOTAL_TOOLS_PER_TURN - len(state.selected_tool_names))
        if available_slots <= 0:
            return []
        max_additions = min(self._MAX_TOOLS_PER_EXPANSION, available_slots)

        resolve_tool_name = getattr(self.tool_registry, "resolve_tool_name", None)
        get_tool_info = getattr(self.tool_registry, "get_tool_info", None)
        is_skill = getattr(self.tool_registry, "is_skill", None)
        known_names = set(state.selected_tool_names)
        additions: list[str] = []
        for raw_name in raw_append_tools:
            if len(additions) >= max_additions:
                break
            name = str(raw_name or "").strip()
            if not name:
                continue
            skill_name = name.lstrip("/")
            normalized = (
                resolve_tool_name(name) if callable(resolve_tool_name) and not name.startswith("/") else skill_name
            )
            if normalized in known_names:
                continue
            known_tool = callable(get_tool_info) and get_tool_info(normalized) is not None
            known_skill = callable(is_skill) and is_skill(skill_name)
            if not known_tool and not known_skill:
                continue
            known_names.add(normalized)
            additions.append(normalized)

        if not additions:
            return []

        state.selected_tool_names.extend(additions)
        state.tools = self._build_tools_parameter(state.selected_tool_names)
        state.tool_expansion_count += 1
        return additions

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
                history_limit=max(len(messages), 1) + 1,
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
        state = self.build_step_state(
            turn=turn,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            conversation_history=conversation_history,
            session_summary=session_summary,
            session_origin=session_origin,
            reply_context=reply_context,
            ephemeral_context=ephemeral_context,
        )
        self._current_messages = state.messages
        depth = _coerce_thinking_depth(thinking_depth, disable_thinking)
        while state.iteration < max_iterations:
            # Poll signals in priority order:
            #   cancel  → stop immediately, no snapshot needed
            #   retract → stop + snapshot for DeliveryRouter rollback
            #   suspend → stop + snapshot for in-place resume
            #   steer   → drain follow-ups before next LLM call
            #   detach  → hand off to background worker with snapshot
            if await control.cancel_token.is_cancelled():
                return ExecutionOutcome(
                    status="cancelled",
                    content="",
                    iterations=state.iteration,
                )
            if control.retract_signal.is_requested():
                return self._build_retracted_outcome(state, control.retract_signal)
            if control.suspend_signal.is_requested():
                return self._build_suspended_outcome(state, control.suspend_signal)
            # Drain steer messages before checking detach so a steer that
            # arrived in the same tick is appended to state.messages before
            # the snapshot is taken.
            await self.apply_steer_messages(state, control.steer_inbox)
            if control.detach_signal.is_requested():
                return self._build_detached_outcome(state, control.detach_signal)
            step_outcome = await self.step_executor.execute_step(
                state=state,
                user_message=turn.text,
                thinking_depth=depth,
                user_id=user_id,
                session_id=session_id,
                session_run_id=session_run_id,
                session_run_revision=session_run_revision,
                turn_id=turn_id,
                intent=intent,
                execution_agent_id=execution_agent_id,
                execution_workspace=execution_workspace,
                llm_timeout_seconds=llm_timeout_seconds,
                cancel_token=control.cancel_token,
                control=control,
                route_decision=route_decision,
            )
            if step_outcome.status == "aborted":
                # CancellationRaised/RetractRaised was caught by step_executor.
                # Loop back so the top-of-loop signal poll returns the right outcome.
                continue
            if step_outcome.status == "continue":
                if get_stream_sink() is not None:
                    await emit_stream_event(LLMStreamEvent(kind="text_flush"))
                await self._drop_ephemeral_context(state)
                await self._try_compact(state, system_prompt)
                continue
            if step_outcome.status == "completed":
                return ExecutionOutcome(
                    status="completed",
                    content=step_outcome.content,
                    tool_failures=list(state.tool_failures),
                    # Pre-existing bug fix: state.chat_attachments
                    # accumulates tool-emitted attachments (image_gen,
                    # prepare_chat_attachments, …) across the FC loop,
                    # but the completed outcome wasn't forwarding them
                    # to the coordinator. Desktop still saw images
                    # because the chat UI reads chat_messages.payload_json
                    # directly; external channels (WeChat, Telegram)
                    # got the text body but no image because their
                    # deliver() path only sees DeliveryContent.attachments,
                    # which is sourced from this field.
                    attachments=list(state.chat_attachments),
                    message_payload=dict(state.message_payload or {}),
                    iterations=step_outcome.iteration,
                )
            if step_outcome.status == "cancelled":
                return ExecutionOutcome(
                    status="cancelled",
                    content="",
                    tool_failures=list(state.tool_failures),
                    iterations=step_outcome.iteration,
                )
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason=step_outcome.failure_reason,
                error_text=step_outcome.error_text,
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
                llm_timeout_seconds=llm_timeout_seconds,
                final_response_json_mode=final_response_json_mode,
                cancel_token=control.cancel_token,
                control=control,
                route_decision=route_decision,
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
