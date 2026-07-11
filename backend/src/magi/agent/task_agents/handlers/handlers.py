"""Execution handlers for chat task-agent modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from ....core.logger import get_logger
from ....agent.background.launch import BackgroundLaunchService
from magi.control.run_control import null_run_control
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
from .checkpoint_loop import FunctionCallingCheckpointLoop
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
from .tool_exposure_policy import default_tool_exposure_policy
from .turn_route_resolver import TurnRouteResolver
from ...run.ports import AttachmentResolverPort, NullAttachmentResolver
from ....llm.model_context import ModelContextProfile
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
    model_context_provider: Callable[[], ModelContextProfile]
    # Resolves managed attachment payloads for a turn. Chat wires a
    # chat-backed resolver; defaults to a null resolver so tests / non-chat
    # callers can build dependencies without a chat read service.
    attachment_resolver: AttachmentResolverPort = field(default_factory=NullAttachmentResolver)
    session_run_coordinator: Any | None = None
    background_launch_service: BackgroundLaunchService | None = None
    persist_turn_supersessions: Callable[[list[Any], int], Awaitable[None]] | None = None
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
        start_specialized_orchestration=lambda request: _start_explore_task_agent(deps, request),
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


def _is_emotional_or_crisis(request: ExecutionRequest) -> bool:
    routing_hint = getattr(request.intent, "persona_routing_hint", None)
    routing_register = routing_hint.register if routing_hint is not None else None
    return routing_register in {"emotional", "crisis"}


class FunctionCallingHandler(FunctionCallingRuntimeControlMixin, BaseExecutionHandler):
    mode = ExecutionMode.FUNCTION_CALLING

    @property
    def _attachment_resolver(self) -> AttachmentResolverPort:
        # Duck-typed deps (e.g. test SimpleNamespace) may omit the field;
        # fall back to a null resolver so attachment resolution is a no-op
        # rather than touching chat.
        resolver = getattr(self._deps, "attachment_resolver", None)
        return resolver if resolver is not None else NullAttachmentResolver()

    def _build_checkpoint_loop(self) -> FunctionCallingCheckpointLoop:
        return FunctionCallingCheckpointLoop(
            deps=self._deps,
            attachment_resolver=self._attachment_resolver,
            cancel_token_factory=self._build_cancel_token,
            detached_result_builder=self._build_detached_chat_result,
            drain_pending_steer_turns=self._drain_pending_steer_turns,
        )

    async def build_request(self, request: ExecutionRequest) -> FunctionCallingRequest:
        prompt_package = await self._build_prompt_package(request)
        selected_tools = list(request.tool_selection.tools)
        system_prompt, selected_tools = self._apply_prompt_guidance(
            request=request,
            system_prompt=prompt_package.system_prompt,
            selected_tools=selected_tools,
        )
        selected_tools = self._resolve_execution_tools(request, selected_tools)
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

    async def _build_prompt_package(self, request: ExecutionRequest) -> Any:
        return await self._deps.context_service.build_prompt_package(
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

    def _apply_prompt_guidance(
        self,
        *,
        request: ExecutionRequest,
        system_prompt: str,
        selected_tools: list[str],
    ) -> tuple[str, list[str]]:
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
        if scope_guidance_block and not _is_emotional_or_crisis(request):
            system_prompt = f"{system_prompt}\n\n{scope_guidance_block}"

        attachment_guidance_block = _build_attachment_preparation_guidance_block(selected_tools)
        if attachment_guidance_block:
            system_prompt = f"{system_prompt}\n\n{attachment_guidance_block}"
        return system_prompt, selected_tools

    def _resolve_execution_tools(
        self,
        request: ExecutionRequest,
        selected_tools: list[str],
    ) -> list[str]:
        _orchestrator = getattr(self._deps, "function_calling_orchestrator", None)
        _registry = getattr(_orchestrator, "tool_registry", None)
        _route = getattr(request.intent, "route_decision", None)
        _policy = getattr(self._deps, "tool_exposure_policy", default_tool_exposure_policy)
        return TurnRouteResolver(tool_exposure_policy=_policy).resolve_execution_tools(
            requested_tools=selected_tools,
            route_decision=_route,
            tool_registry=_registry,
            session_key=(
                f"{getattr(request.context, 'agent_id', '')}:"
                f"{getattr(request.context, 'session_id', '')}"
            ),
        )

    async def execute(self, request: FunctionCallingRequest) -> ExecutionResult:
        execution_workspace = _resolve_execution_workspace(request)
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        detach_signal = self._build_detach_signal(session_id=session_id)
        steer_inbox = await self._build_steer_inbox(request)
        try:
            if self._can_use_checkpoint_loop(request):
                result = await self._execute_checkpoint_loop(
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
            context_control = (
                request.context.control if hasattr(request.context, "control") else None
            )
            control = self._build_run_control(context_control, cancel_token)
            route_decision = getattr(request.intent, "route_decision", None)
            execution_outcome = await self._execute_orchestrator_run(
                request,
                execution_workspace=execution_workspace,
                turn_id=turn_id,
                control=control,
                route_decision=route_decision,
            )

            fc_result = self._build_execution_result(
                request=request,
                execution_outcome=execution_outcome,
                turn_id=turn_id,
                streamed=streaming_enabled and execution_outcome.status == "completed",
            )
            handoff = await self._maybe_handoff_detached_outcome(request, fc_result)
            if handoff is not None:
                return handoff
            return fc_result
        finally:
            self._release_detach_signal(session_id=session_id, detach_signal=detach_signal)

    def _can_use_checkpoint_loop(self, request: FunctionCallingRequest) -> bool:
        return (
            self._deps.session_run_coordinator is not None
            and request.context.session_run_id
            and hasattr(self._deps.function_calling_orchestrator, "step_executor")
            and hasattr(self._deps.function_calling_orchestrator, "build_step_state")
        )

    async def _execute_checkpoint_loop(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        detach_signal: Any,
        steer_inbox: Any,
    ) -> FunctionCallingExecutionResult:
        return await self._build_checkpoint_loop().run(
            request,
            execution_workspace=execution_workspace,
            detach_signal=detach_signal,
            steer_inbox=steer_inbox,
        )

    @staticmethod
    def _build_run_control(context_control: Any, cancel_token: CancelToken) -> Any:
        # Overlay the locally-built cancel token so the legacy cancel-button
        # path continues to work with the context-owned RunControl bundle.
        control = context_control if context_control is not None else null_run_control()
        control.cancel_token = cancel_token
        return control

    async def _execute_orchestrator_run(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        turn_id: str | None,
        control: Any,
        route_decision: Any,
    ) -> Any:
        return await self._deps.function_calling_orchestrator.run(
            self._build_engine_run_input(
                request,
                execution_workspace=execution_workspace,
                turn_id=turn_id,
                control=control,
                route_decision=route_decision,
            )
        )

    def _build_engine_run_input(
        self,
        request: FunctionCallingRequest,
        *,
        execution_workspace: str | None,
        turn_id: str | None,
        control: Any,
        route_decision: Any,
    ) -> EngineRunInput:
        return EngineRunInput(
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
            control=control,
            route_decision=route_decision,
        )

    @staticmethod
    def _build_execution_result(
        *,
        request: FunctionCallingRequest,
        execution_outcome: Any,
        turn_id: str | None,
        streamed: bool,
    ) -> FunctionCallingExecutionResult:
        return FunctionCallingExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            attachments=list(getattr(execution_outcome, "attachments", []) or []),
            message_payload=dict(getattr(execution_outcome, "message_payload", {}) or {}),
            root_user_message=request.context.latest_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
            streamed=streamed,
        )


async def _start_explore_task_agent(
    deps: ChatHandlerDependencies,
    request: ExecutionRequest,
) -> Optional[ExecutionResult]:
    return await start_explore_task_agent(deps, request)
