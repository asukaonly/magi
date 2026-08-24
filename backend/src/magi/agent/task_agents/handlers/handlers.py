"""Execution handlers for chat task-agent modes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable

from ....agent.cancel import CancelToken, SessionRunCancelToken, null_cancel_token
from ....core.logger import get_logger
from ....events.first_context import build_first_context_runtime_guidance
from ....agent.background.launch import BackgroundLaunchService
from magi.control.run_control import null_run_control
from ....agent.turn_input import UserTurnInput
from ....agent.execution.function_calling import AgentRunRequest
from ....agent.execution.reasoning import ReasoningPolicy
from ....agent.execution.run_plan_port import BoundRunPlanReader
from ....context.service import ContextAssemblyService
from ....context.scenarios import Scenario
from ..common import (
    BaseExecutionHandler,
    CommonHandlerDependencies,
    ExecutionRequest,
    ExecutionResult,
    AgentRunExecutionResult,
    PreparedAgentRunRequest,
)
from ..common.service_protocols import (
    HistoryServiceProtocol,
    PromptServiceProtocol,
)
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
from .recall_feedback import (
    build_recall_feedback_message_payload,
    build_recall_feedback_prompt,
)
from ...execution.attachment_resolver import AttachmentResolverPort, NullAttachmentResolver
from ....llm.model_context import ModelContextProfile

logger = get_logger(__name__)


def _build_inline_skill_prompt(request: ExecutionRequest) -> str:
    payload = getattr(request.context, "latest_payload", None)
    invocation = getattr(payload, "skill_invocation", None)
    if not isinstance(invocation, dict):
        return ""
    name = str(invocation.get("name") or "").strip()
    rendered_prompt = str(invocation.get("rendered_prompt") or "").strip()
    content_hash = str(invocation.get("content_hash") or "").strip()
    if not name or not rendered_prompt or not content_hash:
        raise ValueError("Inline skill context is incomplete")
    return (
        "# Explicit Skill Context\n"
        f"The user explicitly invoked the enabled skill `{name}`. Apply the "
        "following trusted skill instructions to this run while preserving all "
        "runtime permission and completion policies.\n\n"
        f'<skill name="{name}" sha256="{content_hash}">\n'
        f"{rendered_prompt}\n"
        "</skill>"
    )


def _build_context_sources(
    request: ExecutionRequest,
    prompt_context: Any,
) -> tuple[dict[str, Any], ...]:
    """Snapshot bounded context owners represented in the effective prompt."""

    sources: list[dict[str, Any]] = []
    self_memory = getattr(prompt_context, "self_memory", None)
    retrieval = getattr(self_memory, "retrieval_memory", None)
    if retrieval is not None:
        sources.append(
            {
                "provider": "memory",
                "snapshot": asdict(retrieval) if is_dataclass(retrieval) else {},
                "availability": "available",
            }
        )
    persona_plan = getattr(self_memory, "persona_turn_plan", None)
    if persona_plan is not None:
        sources.append(
            {
                "provider": "persona",
                "snapshot": asdict(persona_plan) if is_dataclass(persona_plan) else {},
            }
        )
    sources.append(
        {
            "provider": "continuity",
            "recent_tool_errors": list(getattr(request.context, "recent_tool_errors", None) or [])[
                :3
            ],
            "recent_tool_state": list(getattr(request.context, "recent_tool_state", None) or [])[
                :3
            ],
            "pending_interaction": bool(getattr(request.context, "recall_feedback", None)),
        }
    )
    latest_payload = getattr(request.context, "latest_payload", None)
    skill_invocation = getattr(latest_payload, "skill_invocation", None)
    if isinstance(skill_invocation, dict):
        sources.append(
            {
                "provider": "skill",
                "name": str(skill_invocation.get("name") or ""),
                "arguments": list(skill_invocation.get("arguments") or []),
                "invocation_text": str(skill_invocation.get("invocation_text") or ""),
                "rendered_prompt": str(skill_invocation.get("rendered_prompt") or ""),
                "content_hash": str(skill_invocation.get("content_hash") or ""),
                "context_mode": "inline",
                "allowed_tools": list(skill_invocation.get("allowed_tools") or []),
            }
        )
    return tuple(sources)


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
    function_calling_orchestrator: Any
    context_assembler: HistoryServiceProtocol
    agent_id: str
    model_context_provider: Callable[[], ModelContextProfile]
    run_plan_store: Any
    # Resolves managed attachment payloads for a turn. Chat wires a
    # chat-backed resolver; defaults to a null resolver so tests / non-chat
    # callers can build dependencies without a chat read service.
    attachment_resolver: AttachmentResolverPort = field(default_factory=NullAttachmentResolver)
    session_run_coordinator: Any | None = None
    background_launch_service: BackgroundLaunchService | None = None
    # Phase G+1: Optional reference to the ChatExecutionCoordinator so the
    # streaming-path handler can route ``text_delta`` chunks through
    # ``coordinator.dispatch_stream_chunk`` (multi-channel fanout). Optional
    # so legacy tests can build dependencies without wiring a coordinator.
    coordinator: Any | None = None


def build_common_handler_dependencies(
    deps: ChatHandlerDependencies,
):
    return CommonHandlerDependencies(
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


class AgentRunHandler(FunctionCallingRuntimeControlMixin, BaseExecutionHandler):
    """Prepare and execute every ordinary user turn through the unified loop."""

    mode = None

    @property
    def _attachment_resolver(self) -> AttachmentResolverPort:
        # Duck-typed deps (e.g. test SimpleNamespace) may omit the field;
        # fall back to a null resolver so attachment resolution is a no-op
        # rather than touching chat.
        resolver = getattr(self._deps, "attachment_resolver", None)
        return resolver if resolver is not None else NullAttachmentResolver()

    async def build_request(self, request: ExecutionRequest) -> PreparedAgentRunRequest:
        prompt_package = await self._build_prompt_package(request)
        selected_tools = list(request.tool_selection.tools)
        system_prompt, selected_tools = self._apply_prompt_guidance(
            request=request,
            system_prompt=prompt_package.system_prompt,
            selected_tools=selected_tools,
        )
        system_prompt = self._deps.prompt_service.augment_system_prompt_with_reply_context(
            system_prompt=system_prompt,
            reply_context=getattr(request.context, "reply_context", None),
            recent_tool_state=getattr(request.context, "recent_tool_state", None),
        )
        latest_payload = getattr(request.context, "latest_payload", None)
        first_context_guidance = build_first_context_runtime_guidance(
            {
                "interaction_kind": getattr(latest_payload, "interaction_kind", None),
                "first_context": getattr(latest_payload, "first_context", None),
            }
        )
        if first_context_guidance:
            system_prompt = f"{system_prompt}\n\n{first_context_guidance}"
        context_sources = _build_context_sources(request, prompt_package.prompt_context)
        return PreparedAgentRunRequest(
            mode=request.mode,
            context=request.context,
            intent=request.intent,
            tool_selection=request.tool_selection,
            prompt_context=prompt_package.prompt_context,
            system_prompt=system_prompt,
            selected_tools=selected_tools,
            reasoning_policy=ReasoningPolicy.from_preference(request.intent.reasoning_preference),
            context_sources=context_sources,
        )

    async def _build_prompt_package(self, request: ExecutionRequest) -> Any:
        return await self._deps.context_service.build_prompt_package(
            user_id=request.context.user_id,
            session_id=request.context.session_id,
            user_message=request.context.latest_user_message,
            attachments=resolve_effective_turn_attachments(
                request.context, resolver=self._attachment_resolver
            ),
            task_category="general",
            tools=request.tool_selection.tools,
            persona_action_tools=[],
            scenario=Scenario.CHAT,
            recent_tool_errors=request.context.recent_tool_errors,
            workspace_path=_resolve_turn_workspace_path(request.context),
            persona_id=getattr(request.context, "active_persona_id", None),
            allow_implicit_memory=getattr(request.context, "recall_feedback", None) is None,
        )

    def _apply_prompt_guidance(
        self,
        *,
        request: ExecutionRequest,
        system_prompt: str,
        selected_tools: list[str],
    ) -> tuple[str, list[str]]:
        if "memory_query" in selected_tools:
            # Keep retrieval observations verbatim whenever the resident
            # memory capability is exposed to the model.
            system_prompt = f"{system_prompt}\n\n{MEMORY_QUERY_GUIDANCE_BLOCK}"

        scope_guidance_block = _build_scope_guidance_block(
            getattr(request.tool_selection, "task_hint", None)
            or getattr(request.intent, "task_hint", None)
        )
        if scope_guidance_block:
            system_prompt = f"{system_prompt}\n\n{scope_guidance_block}"

        attachment_guidance_block = _build_attachment_preparation_guidance_block(selected_tools)
        if attachment_guidance_block:
            system_prompt = f"{system_prompt}\n\n{attachment_guidance_block}"
        recall_feedback_prompt = build_recall_feedback_prompt(
            getattr(request.context, "recall_feedback", None)
        )
        if recall_feedback_prompt:
            system_prompt = f"{system_prompt}\n\n{recall_feedback_prompt}"
        skill_prompt = _build_inline_skill_prompt(request)
        if skill_prompt:
            system_prompt = f"{system_prompt}\n\n{skill_prompt}"
        return system_prompt, selected_tools

    async def execute(self, request: PreparedAgentRunRequest) -> ExecutionResult:
        execution_workspace = _resolve_execution_workspace(request)
        streaming_enabled = getattr(request.context, "streaming_chat_enabled", False)
        turn_id = getattr(request.context.latest_payload, "turn_id", None)
        session_id = str(getattr(request.context, "session_id", "") or "").strip()
        detach_signal = self._build_detach_signal(session_id=session_id)
        cancel_token = self._build_cancel_token(request)
        context_control = request.context.control if hasattr(request.context, "control") else None
        control = self._build_run_control(
            context_control,
            cancel_token,
            detach_signal=detach_signal,
        )
        try:
            execution_outcome = await self._execute_orchestrator_run(
                request,
                execution_workspace=execution_workspace,
                turn_id=turn_id,
                control=control,
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

    @staticmethod
    def _build_run_control(
        context_control: Any,
        cancel_token: CancelToken,
        *,
        detach_signal: Any = None,
    ) -> Any:
        """Overlay live controls while preserving the context-owned input queue."""

        control = context_control if context_control is not None else null_run_control()
        control.cancel_token = cancel_token
        if detach_signal is not None:
            control.detach_signal = detach_signal
        return control

    async def _execute_orchestrator_run(
        self,
        request: PreparedAgentRunRequest,
        *,
        execution_workspace: str | None,
        turn_id: str | None,
        control: Any,
    ) -> Any:
        return await self._deps.function_calling_orchestrator.run(
            self._build_agent_run_request(
                request,
                execution_workspace=execution_workspace,
                turn_id=turn_id,
                control=control,
            )
        )

    def _build_agent_run_request(
        self,
        request: PreparedAgentRunRequest,
        *,
        execution_workspace: str | None,
        turn_id: str | None,
        control: Any,
    ) -> AgentRunRequest:
        run_id = str(request.context.session_run_id or "").strip()
        if not run_id:
            raise RuntimeError("Chat agent run requires a canonical run_id")
        return AgentRunRequest(
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
            run_id=run_id,
            session_id=request.context.session_id,
            run_revision=request.context.session_run_revision,
            turn_id=turn_id,
            conversation_history=request.context.history,
            session_summary=getattr(request.context, "session_summary", None),
            session_origin=getattr(request.context, "session_origin", None),
            reply_context=getattr(request.context, "reply_context", None),
            reasoning_policy=request.reasoning_policy,
            execution_preset="chat",
            execution_agent_id=request.context.runtime_key,
            execution_workspace=execution_workspace,
            control=control,
            context_sources=request.context_sources,
            capability_resolution=(
                request.intent.capability_resolution.to_event_payload()
                if request.intent.capability_resolution is not None
                else {}
            ),
            run_plan_reader=BoundRunPlanReader(
                store=self._deps.run_plan_store,
                session_id=request.context.session_id,
                run_id=run_id,
            ),
        )

    @staticmethod
    def _build_execution_result(
        *,
        request: PreparedAgentRunRequest,
        execution_outcome: Any,
        turn_id: str | None,
        streamed: bool,
    ) -> AgentRunExecutionResult:
        return AgentRunExecutionResult(
            mode=request.mode,
            response_text=execution_outcome.content,
            attachments=list(getattr(execution_outcome, "attachments", []) or []),
            message_payload={
                **dict(getattr(execution_outcome, "message_payload", {}) or {}),
                **build_recall_feedback_message_payload(
                    getattr(request.context, "recall_feedback", None)
                ),
            },
            context_usage=(
                dict(execution_outcome.context_usage)
                if isinstance(getattr(execution_outcome, "context_usage", None), dict)
                else None
            ),
            root_user_message=request.context.latest_user_message,
            execution_outcome=execution_outcome.to_dict(),
            turn_id=turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
            streamed=streamed,
        )
