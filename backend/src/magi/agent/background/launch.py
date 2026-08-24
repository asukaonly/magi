"""Launch service + run-function factory for background tasks.

This is the last piece of the background-task runtime (phase 3c):

* :class:`BackgroundLaunchService` turns an :class:`ExecutionRequest`
  that the dispatcher flagged as BACKGROUND into a persisted
  :class:`BackgroundTask` via :class:`BackgroundTaskManager`, then
  returns a short ack :class:`ExecutionResult` so the chat turn can
  finalize its session-run immediately. No polling, no streaming — the
  UI is notified through a later completion handshake (phase 4).

* :func:`build_background_run_fn` returns a
  :class:`BackgroundTaskRunFn` closure that the manager invokes for
  each scheduled task. The closure is a thin bridge:
  :class:`BackgroundTask` + :class:`CancelToken` →
  :meth:`FunctionCallingOrchestrator.run` →
  :class:`BackgroundTaskRunResult`.

These two pieces are intentionally decoupled: the launch service does
not know how a task will actually run, and the run-fn factory does not
know how a task is dispatched. Phase 3d will call these from the chat
coordinator after the dispatcher's verdict.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable
from uuid import uuid4

import structlog

from ..cancel import CancelToken
from ...control.run_control import null_run_control
from ..turn_input import UserTurnInput
from ..execution.checkpoint import AgentRunCheckpoint
from ..execution.function_calling.run_input import AgentRunRequest
from ..execution.reasoning import ReasoningPolicy
from ..execution.run_plan_port import BoundRunPlanReader
from ..execution.task_budget import TaskExecutionBudgetStore, task_execution_budget_scope
from .contracts import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskTriggerSource,
)
from .executor import BackgroundTaskRunFn, BackgroundTaskRunResult
from .manager import BackgroundTaskManager

if TYPE_CHECKING:
    from magi_plugin_sdk.run_trigger import RunTrigger

    from ..task_agents.common.contracts import (
        ExecutionRequest,
        ExecutionResult,
    )

__all__ = [
    "BackgroundLaunchService",
    "build_background_run_fn",
    "build_spec_from_request",
    "default_ack_text",
]


logger = structlog.get_logger(__name__)


def default_ack_text(title: str) -> str:
    """Default acknowledgement string shown to the user in chat.

    Kept English per agents.md (AI-generated log/UX text). The real
    product-facing copy can be swapped by passing ``ack_builder`` to
    :class:`BackgroundLaunchService`.
    """
    clean = (title or "this task").strip() or "this task"
    return f"Started background task: {clean}. I'll let you know when it finishes."


# ---------------------------------------------------------------------
# Spec construction
# ---------------------------------------------------------------------


def _derive_title(user_message: str) -> str:
    text = (user_message or "").strip().splitlines()[0] if user_message else ""
    text = text.strip()
    if not text:
        return "background task"
    if len(text) <= 80:
        return text
    return text[:77].rstrip() + "..."


def build_spec_from_request(
    request: "ExecutionRequest",
    *,
    trigger_source: BackgroundTaskTriggerSource,
    trigger: "RunTrigger | None" = None,
    timeout_seconds: int | None = 1800,
    max_iterations: int = 50,
    agent_run_checkpoint: dict[str, Any] | None = None,
) -> BackgroundTaskSpec:
    """Construct a :class:`BackgroundTaskSpec` from a chat
    :class:`ExecutionRequest`.

    The spec captures the *intent snapshot* at dispatch time so a retry
    can rerun the same task without replaying the whole chat turn. The
    live chat history is intentionally not included — on retry the
    executor will rebuild its own prompt package.

    A detach-to-background handoff supplies the complete unified-loop
    checkpoint so the worker resumes governance state and model context
    together.
    """
    context = request.context
    latest_payload = getattr(context, "latest_payload", None)
    turn_id = getattr(latest_payload, "turn_id", None) or ""
    active_run = getattr(context, "active_run", None)
    task_budget_root_turn_id = (
        str(getattr(active_run, "root_turn_id", "") or "").strip()
        or str(getattr(latest_payload, "root_turn_id", "") or "").strip()
        or str(turn_id).strip()
        or None
    )
    workspace_path = str(getattr(latest_payload, "workspace_path", "") or "").strip() or None
    user_message = context.latest_user_message or ""
    return BackgroundTaskSpec(
        user_id=context.user_id,
        session_id=context.session_id or "",
        origin_turn_id=str(turn_id),
        title=_derive_title(user_message),
        goal=user_message,
        run_id=(
            str(agent_run_checkpoint.get("run_id") or "").strip()
            if agent_run_checkpoint is not None
            else ""
        )
        or uuid4().hex,
        selected_tools=list(request.tool_selection.tools or []),
        workspace_path=workspace_path,
        trigger_source=trigger_source,
        trigger=trigger,
        timeout_seconds=timeout_seconds,
        max_iterations=max_iterations,
        task_budget_root_turn_id=task_budget_root_turn_id,
        agent_run_checkpoint=(
            dict(agent_run_checkpoint) if agent_run_checkpoint is not None else None
        ),
    )


# ---------------------------------------------------------------------
# Launch service
# ---------------------------------------------------------------------


class BackgroundLaunchService:
    """Enqueue-a-background-task service for the chat runtime.

    The service is deliberately handler-agnostic: it returns a plain
    :class:`ExecutionResult` that any caller (phase 3d will wire the
    coordinator / AgentRunHandler) can forward as the turn's
    final result. The ack text is built via an injectable callback so
    product surfaces can localise it without touching runtime code.
    """

    def __init__(
        self,
        manager: BackgroundTaskManager,
        *,
        ack_builder: Callable[[BackgroundTaskSpec, BackgroundTask], str] | None = None,
    ) -> None:
        self._manager = manager
        self._ack_builder = ack_builder or (lambda spec, _task: default_ack_text(spec.title))

    async def enqueue_from_request(
        self,
        request: "ExecutionRequest",
        *,
        trigger_source: BackgroundTaskTriggerSource,
        trigger: "RunTrigger | None" = None,
        timeout_seconds: int | None = 1800,
        max_iterations: int = 50,
        agent_run_checkpoint: dict[str, Any] | None = None,
    ) -> "ExecutionResult":
        # Imported here to avoid a module-load-time cycle:
        # task_agents.common.contracts -> task_agents/__init__.py ->
        # chat handlers -> background.launch.
        from ..task_agents.common.contracts import ExecutionResult

        spec = build_spec_from_request(
            request,
            trigger_source=trigger_source,
            trigger=trigger,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
            agent_run_checkpoint=agent_run_checkpoint,
        )
        task = await self._manager.enqueue(spec)
        ack = self._ack_builder(spec, task)
        logger.info(
            "background task enqueued",
            task_id=task.task_id,
            user_id=spec.user_id,
            session_id=spec.session_id,
            trigger_source=trigger_source.value,
            title=spec.title,
        )
        turn_id = getattr(getattr(request.context, "latest_payload", None), "turn_id", None)
        return ExecutionResult(
            mode=request.mode,
            response_text=ack,
            message_payload={
                "background_task_id": task.task_id,
                "background_task_title": spec.title,
                "background_task_attempt": int(task.attempt_index),
            },
            root_user_message=request.context.latest_user_message,
            turn_id=turn_id,
            ux_plan=_serialize_ux_plan(request.intent),
        )


def _serialize_ux_plan(intent: Any) -> dict | None:
    plan = getattr(intent, "ux_plan", None)
    if plan is None:
        return None
    to_dict = getattr(plan, "to_dict", None)
    return to_dict() if callable(to_dict) else plan


# ---------------------------------------------------------------------
# Run-function factory
# ---------------------------------------------------------------------


def build_background_run_fn(
    *,
    function_calling_orchestrator: Any,
    chat_task_budget_store: TaskExecutionBudgetStore | None = None,
    background_task_budget_store: TaskExecutionBudgetStore | None = None,
    run_plan_store: Any,
    execution_agent_id_prefix: str = "background",
    intent_label: str = "background",
) -> BackgroundTaskRunFn:
    """Return a :class:`BackgroundTaskRunFn` bound to ``orchestrator``.

    The closure invokes
    :meth:`FunctionCallingOrchestrator.run` with the
    task's own spec + the provided :class:`CancelToken`, then wraps the
    outcome into :class:`BackgroundTaskRunResult`. ``system_prompt`` is
    left blank so the orchestrator falls back to its built-in scenario
    prompt — the spec.goal alone is sufficient once decoupled from the
    original chat turn.

    The ``execution_agent_id`` forwarded to the orchestrator is
    ``f"{execution_agent_id_prefix}:{task.task_id}"`` so runtime-trace
    rows can be filtered back to a single background task per the
    observability requirement in ``docs/dev/background-task-design.md``
    §15.
    """

    async def _run(task: BackgroundTask, cancel_token: CancelToken) -> BackgroundTaskRunResult:
        spec = task.spec
        execution_agent_id = f"{execution_agent_id_prefix}:{task.task_id}"
        checkpoint = (
            AgentRunCheckpoint.from_dict(spec.agent_run_checkpoint)
            if spec.agent_run_checkpoint is not None
            else None
        )
        async with _background_task_budget_scope(
            task=task,
            chat_store=chat_task_budget_store,
            background_store=background_task_budget_store,
        ):
            outcome = await function_calling_orchestrator.run(
                AgentRunRequest.headless(
                    turn=UserTurnInput(
                        text=spec.goal,
                        attachments=[],
                        user_id=spec.user_id,
                        session_id=spec.session_id or None,
                    ),
                    selected_tools=list(spec.selected_tools),
                    system_prompt=spec.system_prompt,
                    user_id=spec.user_id,
                    session_id=spec.session_id or None,
                    run_id=spec.run_id,
                    parent_run_id=spec.parent_run_id,
                    turn_id=spec.origin_turn_id or None,
                    max_iterations=spec.max_iterations,
                    execution_preset=spec.execution_preset or intent_label,
                    execution_agent_id=execution_agent_id,
                    execution_workspace=spec.workspace_path,
                    control=_background_run_control(cancel_token),
                    context_sources=spec.context_sources,
                    checkpoint=checkpoint,
                    run_plan_reader=BoundRunPlanReader(
                        store=run_plan_store,
                        session_id=spec.session_id,
                        run_id=spec.run_id,
                    ),
                    reasoning_policy=(
                        ReasoningPolicy.from_dict(spec.reasoning_policy)
                        if spec.reasoning_policy
                        else ReasoningPolicy()
                    ),
                    final_response_json_mode=spec.final_response_json_mode,
                )
            )
        summary = (outcome.content or "").strip()
        return BackgroundTaskRunResult(
            summary=summary,
            result_payload=outcome.to_dict(),
        )

    return _run


def _background_run_control(cancel_token: CancelToken):
    control = null_run_control()
    control.cancel_token = cancel_token
    return control


@asynccontextmanager
async def _background_task_budget_scope(
    *,
    task: BackgroundTask,
    chat_store: TaskExecutionBudgetStore | None,
    background_store: TaskExecutionBudgetStore | None,
) -> AsyncIterator[None]:
    root_turn_id = str(task.spec.task_budget_root_turn_id or "").strip()
    if root_turn_id:
        if chat_store is None:
            raise RuntimeError("Chat task budget store is unavailable for background continuation")
        async with task_execution_budget_scope(root_turn_id=root_turn_id, store=chat_store):
            yield
        return
    if background_store is None:
        async with task_execution_budget_scope():
            yield
        return
    async with task_execution_budget_scope(
        root_turn_id=task.task_id,
        store=background_store,
    ):
        yield
