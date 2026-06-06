"""Execution handlers for chat task-agent modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from ....core.logger import get_logger
from ....agent.background.dispatcher import (
    BackgroundDispatcher,
)
from ....agent.background.launch import BackgroundLaunchService
from magi.control.run_control import (
    DetachSignal,
    SteerInbox,
    bind_detach_signal,
    null_run_control,
)
from ....agent.turn_input import UserTurnInput
from ....agent.execution.function_calling import EngineRunInput
from ....context.service import ContextAssemblyService
from ....context.scenarios import Scenario
from ..common import (
    BaseExecutionHandler,
    CommonHandlerDependencies,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    FunctionCallingExecutionResult,
    FunctionCallingRequest,
)
from ..common.service_protocols import (
    HistoryServiceProtocol,
    PromptServiceProtocol,
)
from .explore_render import start_explore_task_agent
from .runtime_control import FunctionCallingRuntimeControlMixin
from .handler_helpers import (
    MEMORY_QUERY_GUIDANCE_BLOCK,
    build_attachment_preparation_guidance_block as _build_attachment_preparation_guidance_block,
    build_scope_guidance_block as _build_scope_guidance_block,
    resolve_execution_workspace as _resolve_execution_workspace,
    resolve_turn_workspace_path as _resolve_turn_workspace_path,
    serialize_ux_plan as _serialize_ux_plan,
)
from .attachment_context import resolve_effective_turn_attachments
from ...run.ports import AttachmentResolverPort, NullAttachmentResolver
from ...task_orchestrator import TaskOrchestrator

logger = get_logger(__name__)


@dataclass(slots=True)
class ChatHandlerDependencies:
    """Shared dependencies passed to chat execution handlers."""

    context_service: ContextAssemblyService
    # Ring-2 protocols (see common.service_protocols): the generic handlers
    # only touch a small, stable surface of these collaborators, so the bundle
    # is typed against the protocol rather than the concrete chat service. The
    # concrete ``ChatPromptService`` / ``ChatContextAssembler`` still satisfy
    # these structurally and are passed unchanged at construction sites.
    prompt_service: PromptServiceProtocol
    # Not touched by ring-2 handler code (only carried for other consumers);
    # left untyped so the bundle stays free of concrete chat service classes.
    planning_service: Any
    function_calling_orchestrator: any
    task_orchestrator: TaskOrchestrator
    context_assembler: HistoryServiceProtocol
    agent_id: str
    get_task_agent_manager: callable
    # Resolves managed attachment payloads for a turn. Chat wires a
    # chat-backed resolver; defaults to a null resolver so tests / non-chat
    # callers can build dependencies without a chat read service.
    attachment_resolver: AttachmentResolverPort = field(
        default_factory=NullAttachmentResolver
    )
    session_run_coordinator: Any | None = None
    background_dispatcher: BackgroundDispatcher | None = None
    background_launch_service: BackgroundLaunchService | None = None
    persist_turn_supersessions: Callable[[list[Any], int], Awaitable[None]] | None = (
        None
    )
    # Phase G+1: Optional reference to the ChatExecutionCoordinator so the
    # streaming-path handler can route ``text_delta`` chunks through
    # ``coordinator.dispatch_stream_chunk`` (multi-channel fanout). Optional
    # so legacy tests can build dependencies without wiring a coordinator.
    coordinator: Any | None = None


def build_common_handler_dependencies(
    deps: ChatHandlerDependencies,
):
    return CommonHandlerDependencies(
        task_orchestrator=deps.task_orchestrator,
        start_specialized_orchestration=lambda request: _start_explore_task_agent(
            deps, request
        ),
        build_cancel_token=lambda request: _build_common_cancel_token(deps, request),
    )


def _build_common_cancel_token(
    deps: ChatHandlerDependencies,
    request: ExecutionRequest,
) -> CancelToken:
    coordinator = deps.session_run_coordinator
    session_id = str(request.context.session_id or "").strip()
    run_id = str(getattr(request.context, "session_run_id", None) or "").strip()
    if coordinator is None or not session_id or not run_id:
        return null_cancel_token()
    revision = int(getattr(request.context, "session_run_revision", 0) or 0)
    return SessionRunCancelToken(
        coordinator=coordinator,
        session_id=session_id,
        run_id=run_id,
        revision=revision,
    )


class FunctionCallingHandler(FunctionCallingRuntimeControlMixin, BaseExecutionHandler):
    mode = ExecutionMode.FUNCTION_CALLING

    @property
    def _attachment_resolver(self) -> AttachmentResolverPort:
        # Duck-typed deps (e.g. test SimpleNamespace) may omit the field;
        # fall back to a null resolver so attachment resolution is a no-op
        # rather than touching chat.
        resolver = getattr(self._deps, "attachment_resolver", None)
        return resolver if resolver is not None else NullAttachmentResolver()

    async def build_request(self, request: ExecutionRequest) -> FunctionCallingRequest:
        prompt_package = await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=resolve_effective_turn_attachments(
                request.context, resolver=self._attachment_resolver
            ),
            task_category=request.intent.intent,
            tools=request.tool_selection.tools,
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
            persona_id=getattr(request.context, "active_persona_id", None),
            persona_routing_hint=getattr(request.intent, "persona_routing_hint", None),
        )
        selected_tools = list(request.tool_selection.tools)
        system_prompt = prompt_package.system_prompt
        # Scope guidance is task-routing language (target locality, web-vs-local
        # resolution order). It is wrong-register for emotional / crisis turns
        # where there is no "scope decision" to make. Memory guidance stays
        # register-agnostic because memory recall in casual chat ("你还记得
        # 我说过...") is common and the guidance is already opt-in via
        # memory_query being in the selected tools.
        _routing_register = (
            request.intent.persona_routing_hint.register
            if getattr(request.intent, "persona_routing_hint", None)
            else None
        )
        _emotional_or_crisis = _routing_register in {"emotional", "crisis"}

        if "memory_query" in selected_tools:
            # Attach the don't-paraphrase guidance whenever memory_query is in
            # the selected tools, regardless of how the upstream router
            # classified the turn (memory_route). Originally this was gated on
            # memory_route == "explicit_query"; turns where the selector pulled
            # in memory_query through other routes (low-confidence routing,
            # selector LLM picking it directly, future route values) got the
            # tool without the guidance — reintroducing the paraphrase bug.
            if request.intent.memory_route == "explicit_query":
                selected_tools = ["memory_query"] + [
                    tool for tool in selected_tools if tool != "memory_query"
                ]
            system_prompt = f"{system_prompt}\n\n{MEMORY_QUERY_GUIDANCE_BLOCK}"
        scope_guidance_block = _build_scope_guidance_block(
            getattr(request.tool_selection, "task_hint", None)
            or getattr(request.intent, "task_hint", None)
        )
        if scope_guidance_block and not _emotional_or_crisis:
            system_prompt = f"{system_prompt}\n\n{scope_guidance_block}"
        attachment_guidance_block = _build_attachment_preparation_guidance_block(
            selected_tools
        )
        if attachment_guidance_block:
            system_prompt = f"{system_prompt}\n\n{attachment_guidance_block}"
        # ADR-0005 §4: runtime-control / system tools are RESIDENT on the main
        # loop. The router only filters capability tools (and never sees these);
        # they are appended here — AFTER the execution shape was derived from the
        # capability tools — so they let the model switch its own state (plan
        # mode, ask-user, detach, tool discovery) mid-loop without ever turning a
        # reply into a tool_loop.
        from magi.tools.system_tools import resolve_resident_system_tools

        _orchestrator = getattr(self._deps, "function_calling_orchestrator", None)
        _registry = getattr(_orchestrator, "tool_registry", None)
        if _registry is not None:
            for _resident_tool in resolve_resident_system_tools(_registry):
                if _resident_tool not in selected_tools:
                    selected_tools.append(_resident_tool)
        # P3 (ADR-0005): when the router permits in-loop escalation
        # (needs_orchestration == "maybe"), expose the `agent` tool so the model
        # can fan out to workers on its own, mid-loop — instead of orchestration
        # being decided only up front. Conditional (not resident) so ordinary
        # tool loops don't carry fanout power they shouldn't.
        _route = getattr(request.intent, "route_decision", None)
        if (
            _registry is not None
            and getattr(_route, "needs_orchestration", "none") == "maybe"
            and "agent" not in selected_tools
            and "agent" in set(_registry.list_tools())
        ):
            selected_tools.append("agent")
        return FunctionCallingRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=self._deps.prompt_service.augment_system_prompt_with_reply_context(
                system_prompt=system_prompt,
                reply_context=getattr(request.context, "reply_context", None),
                recent_tool_state=getattr(request.context, "recent_tool_state", None),
            ),
            selected_tools=selected_tools,
            thinking_depth=request.intent.thinking_depth,
        )

    async def execute(self, request: FunctionCallingRequest) -> ExecutionResult:
        background_result = await self._maybe_dispatch_to_background(request)
        if background_result is not None:
            return background_result
        execution_workspace = _resolve_execution_workspace(request)
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        detach_signal = self._build_detach_signal(session_id=session_id)
        steer_inbox = await self._build_steer_inbox(request)
        try:
            if (
                self._deps.session_run_coordinator is not None
                and request.context.session_run_id
                and hasattr(self._deps.function_calling_orchestrator, "step_executor")
                and hasattr(
                    self._deps.function_calling_orchestrator, "build_step_state"
                )
            ):
                result = await self._execute_with_session_checkpoints(
                    request,
                    execution_workspace=execution_workspace,
                    detach_signal=detach_signal,
                    steer_inbox=steer_inbox,
                )
                result.streamed = streaming_enabled
                handoff = await self._maybe_handoff_detached_outcome(request, result)
                if handoff is not None:
                    return handoff
                return result

            cancel_token = self._build_cancel_token(request)
            # Build the RunControl bundle from context (Task 8 ensures it is
            # always present on ChatRuntimeContext). Overlay the locally-built
            # cancel_token so the legacy cancel-button path continues to work.
            _ctx_control = (
                request.context.control
                if hasattr(request.context, "control")
                else None
            )
            control = _ctx_control if _ctx_control is not None else null_run_control()
            control.cancel_token = cancel_token
            route_decision = getattr(request.intent, "route_decision", None)
            execution_outcome = await self._deps.function_calling_orchestrator.run(
                EngineRunInput(
                    turn=UserTurnInput(
                        text=request.context.latest_user_message,
                        attachments=resolve_effective_turn_attachments(
                            request.context, resolver=self._attachment_resolver
                        ),
                        user_id=request.context.user_id,
                        session_id=request.context.session_id,
                    ),
                    system_prompt=request.system_prompt,
                    selected_tools=request.selected_tools,
                    user_id=request.context.user_id,
                    session_id=request.context.session_id,
                    session_run_id=request.context.session_run_id,
                    session_run_revision=request.context.session_run_revision,
                    turn_id=turn_id,
                    conversation_history=request.context.history,
                    session_summary=getattr(request.context, "session_summary", None),
                    session_origin=getattr(request.context, "session_origin", None),
                    reply_context=getattr(request.context, "reply_context", None),
                    thinking_depth=request.thinking_depth,
                    intent=request.intent.intent,
                    execution_agent_id=request.context.runtime_key,
                    execution_workspace=execution_workspace,
                    orchestration_strategy=(
                        request.intent.route_decision.to_legacy_strategy_dict()
                        if request.intent.route_decision is not None
                        else None
                    ),
                    control=control,
                    route_decision=route_decision,
                )
            )

            streamed = streaming_enabled and execution_outcome.status == "completed"

            fc_result = FunctionCallingExecutionResult(
                mode=request.mode,
                response_text=execution_outcome.content,
                attachments=list(getattr(execution_outcome, "attachments", []) or []),
                message_payload=dict(
                    getattr(execution_outcome, "message_payload", {}) or {}
                ),
                root_user_message=request.context.latest_user_message,
                execution_outcome=execution_outcome.to_dict(),
                turn_id=turn_id,
                ux_plan=_serialize_ux_plan(request.intent),
                streamed=streamed,
            )
            handoff = await self._maybe_handoff_detached_outcome(request, fc_result)
            if handoff is not None:
                return handoff
            return fc_result
        finally:
            self._release_detach_signal(
                session_id=session_id, detach_signal=detach_signal
            )

    async def _execute_with_session_checkpoints(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        detach_signal: DetachSignal | None = None,
        steer_inbox: SteerInbox | None = None,
    ) -> ExecutionResult:
        orchestrator = self._deps.function_calling_orchestrator
        session_run_coordinator = self._deps.session_run_coordinator
        current_user_message = request.context.latest_user_message
        current_revision = int(getattr(request.context, "session_run_revision", 0) or 0)
        current_turn_id = getattr(request.context.latest_payload, "turn_id", None)
        cancel_token = self._build_cancel_token(request)

        def _build_turn(text: str) -> UserTurnInput:
            return UserTurnInput(
                text=text,
                attachments=resolve_effective_turn_attachments(
                    request.context, resolver=self._attachment_resolver
                ),
                user_id=request.context.user_id,
                session_id=request.context.session_id,
            )

        step_state = orchestrator.build_step_state(
            turn=_build_turn(current_user_message),
            system_prompt=request.system_prompt,
            selected_tools=request.selected_tools,
            conversation_history=request.context.history,
            session_summary=getattr(request.context, "session_summary", None),
            session_origin=getattr(request.context, "session_origin", None),
            reply_context=getattr(request.context, "reply_context", None),
            allow_attachment_grounding=(
                bool(
                    getattr(
                        request.context, "allow_media_grounding_for_conversation", False
                    )
                )
                and bool(getattr(request.context, "core_model_supports_vision", False))
            ),
        )
        max_iterations = int(getattr(orchestrator, "MAX_ITERATIONS", 10) or 10)

        with bind_detach_signal(detach_signal):
            while step_state.iteration < max_iterations:
                if await cancel_token.is_cancelled():
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text="",
                        attachments=list(
                            getattr(step_state, "chat_attachments", []) or []
                        ),
                        message_payload=dict(
                            getattr(step_state, "message_payload", {}) or {}
                        ),
                        root_user_message=current_user_message,
                        execution_outcome={
                            "status": "cancelled",
                            "content": "",
                            "failure_reason": None,
                            "attachments": list(
                                getattr(step_state, "chat_attachments", []) or []
                            ),
                            "message_payload": dict(
                                getattr(step_state, "message_payload", {}) or {}
                            ),
                            "tool_failures": list(
                                getattr(step_state, "tool_failures", [])
                            ),
                            "iterations": step_state.iteration,
                        },
                        turn_id=current_turn_id,
                        ux_plan=_serialize_ux_plan(request.intent),
                    )
                if detach_signal is not None and detach_signal.is_requested():
                    return self._build_detached_chat_result(
                        request=request,
                        step_state=step_state,
                        detach_signal=detach_signal,
                        current_user_message=current_user_message,
                        current_turn_id=current_turn_id,
                    )
                await self._drain_pending_steer_turns(
                    session_id=request.context.session_id,
                    revision=current_revision,
                    steer_inbox=steer_inbox,
                    step_state=step_state,
                    latest_fact_timestamp=getattr(
                        request.context.latest_payload, "timestamp", None
                    ),
                )
                step_outcome = await orchestrator.step_executor.execute_step(
                    state=step_state,
                    user_message=current_user_message,
                    thinking_depth=request.thinking_depth,
                    user_id=request.context.user_id,
                    session_id=request.context.session_id,
                    session_run_id=request.context.session_run_id,
                    session_run_revision=current_revision,
                    turn_id=current_turn_id,
                    intent=request.intent.intent,
                    execution_agent_id=request.context.runtime_key,
                    execution_workspace=execution_workspace,
                    orchestration_strategy=(
                        request.intent.route_decision.to_legacy_strategy_dict()
                        if request.intent.route_decision is not None
                        else None
                    ),
                    cancel_token=cancel_token,
                )
                if step_outcome.status == "completed":
                    execution_outcome = {
                        "status": "completed",
                        "content": step_outcome.content,
                        "failure_reason": None,
                        "tool_failures": list(getattr(step_state, "tool_failures", [])),
                        "iterations": step_outcome.iteration,
                    }
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text=step_outcome.content,
                        attachments=list(
                            getattr(step_state, "chat_attachments", []) or []
                        ),
                        message_payload=dict(
                            getattr(step_state, "message_payload", {}) or {}
                        ),
                        root_user_message=current_user_message,
                        execution_outcome=execution_outcome,
                        turn_id=current_turn_id,
                        ux_plan=_serialize_ux_plan(request.intent),
                    )
                if step_outcome.status == "cancelled":
                    return FunctionCallingExecutionResult(
                        mode=request.mode,
                        response_text="",
                        attachments=list(
                            getattr(step_state, "chat_attachments", []) or []
                        ),
                        message_payload=dict(
                            getattr(step_state, "message_payload", {}) or {}
                        ),
                        root_user_message=current_user_message,
                        execution_outcome={
                            "status": "cancelled",
                            "content": "",
                            "failure_reason": None,
                            "tool_failures": list(
                                getattr(step_state, "tool_failures", [])
                            ),
                            "iterations": step_outcome.iteration,
                        },
                        turn_id=current_turn_id,
                        ux_plan=_serialize_ux_plan(request.intent),
                    )
                if step_outcome.status == "failed":
                    # Instead of returning an empty response, let the LLM
                    # generate a final answer using the error context.
                    break

                # Re-check detach after the tool batch runs so a tool that
                # flipped the signal this iteration exits before the next
                # LLM call.
                if detach_signal is not None and detach_signal.is_requested():
                    return self._build_detached_chat_result(
                        request=request,
                        step_state=step_state,
                        detach_signal=detach_signal,
                        current_user_message=current_user_message,
                        current_turn_id=current_turn_id,
                    )

                active_run = session_run_coordinator.get_active_run(
                    request.context.session_id
                )
                if active_run is not None and active_run.revision != current_revision:
                    current_revision = active_run.revision
                    current_user_message = str(
                        active_run.root_user_message or current_user_message
                    )
                    current_turn_id = active_run.root_turn_id or current_turn_id
                    step_state = orchestrator.build_step_state(
                        turn=_build_turn(current_user_message),
                        system_prompt=request.system_prompt,
                        selected_tools=request.selected_tools,
                        conversation_history=request.context.history,
                        session_summary=getattr(
                            request.context, "session_summary", None
                        ),
                        session_origin=getattr(request.context, "session_origin", None),
                        reply_context=getattr(request.context, "reply_context", None),
                        allow_attachment_grounding=(
                            bool(
                                getattr(
                                    request.context,
                                    "allow_media_grounding_for_conversation",
                                    False,
                                )
                            )
                            and bool(
                                getattr(
                                    request.context, "core_model_supports_vision", False
                                )
                            )
                        ),
                    )
                    if steer_inbox is not None:
                        # Pending STEER turns from the prior revision are no
                        # longer relevant once the run is rebuilt from a new
                        # root, so drop anything still queued in-process.
                        await steer_inbox.drain()
                    continue

                checkpoint = session_run_coordinator.consume_checkpoint(
                    request.context.session_id
                )
                if checkpoint.pending_turns:
                    current_user_message = str(
                        checkpoint.visible_user_message or current_user_message
                    )
                    current_turn_id = (
                        checkpoint.pending_turns[-1].turn_id or current_turn_id
                    )
                    step_state = orchestrator.build_step_state(
                        turn=_build_turn(current_user_message),
                        system_prompt=request.system_prompt,
                        selected_tools=request.selected_tools,
                        conversation_history=request.context.history,
                        session_summary=getattr(
                            request.context, "session_summary", None
                        ),
                        session_origin=getattr(request.context, "session_origin", None),
                        reply_context=getattr(request.context, "reply_context", None),
                        allow_attachment_grounding=(
                            bool(
                                getattr(
                                    request.context,
                                    "allow_media_grounding_for_conversation",
                                    False,
                                )
                            )
                            and bool(
                                getattr(
                                    request.context, "core_model_supports_vision", False
                                )
                            )
                        ),
                    )
                    continue

            _fallback_ctx_control = (
                request.context.control
                if hasattr(request.context, "control")
                else None
            )
            _fallback_control = (
                _fallback_ctx_control
                if _fallback_ctx_control is not None
                else null_run_control()
            )
            _fallback_control.cancel_token = cancel_token
            execution_outcome = await orchestrator._execute_fallback_final_response(
                state=step_state,
                thinking_depth=request.thinking_depth,
                user_id=request.context.user_id,
                session_id=request.context.session_id,
                session_run_id=request.context.session_run_id,
                session_run_revision=current_revision,
                turn_id=current_turn_id,
                intent=request.intent.intent,
                execution_agent_id=request.context.runtime_key,
                execution_workspace=execution_workspace,
                orchestration_strategy=(
                    request.intent.route_decision.to_legacy_strategy_dict()
                    if request.intent.route_decision is not None
                    else None
                ),
                llm_timeout_seconds=None,
                final_response_json_mode=False,
                cancel_token=cancel_token,
                control=_fallback_control,
            )
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            attachments=list(getattr(execution_outcome, "attachments", []) or []),
            message_payload=dict(
                getattr(execution_outcome, "message_payload", {}) or {}
            ),
            root_user_message=current_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=current_turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )


async def _start_explore_task_agent(
    deps: ChatHandlerDependencies,
    request: ExecutionRequest,
) -> Optional[ExecutionResult]:
    return await start_explore_task_agent(deps, request)
