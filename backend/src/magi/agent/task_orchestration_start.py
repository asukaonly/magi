"""Startup flow for parent-task orchestration."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Optional

from magi.control.run_control import RunControl, null_run_control

from ..core.logger import get_logger
from ..llm.cancellable_client import CancellationRaised, RetractRaised
from .cancel import CancelToken
from .orchestration import (
    OrchestrationExecutionResult,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
)
from .orchestration_plan import OrchestrationPlan

logger = get_logger(__name__)

DEFAULT_WORKER_RETRY_BUDGET = 1


class _PlanningCancelled(RuntimeError):
    """Raised when orchestration planning is aborted by a cancel token."""


@dataclass(frozen=True, slots=True)
class TaskOrchestrationStartRequest:
    user_id: str
    session_id: str
    user_message: str
    run_id: str | None
    run_revision: int
    turn_id: Optional[str]
    root_turn_id: Optional[str]
    upstream_task_agent_type: Optional[str]
    upstream_task_agent_id: Optional[str]
    user_message_generation: int | None
    history: list[dict[str, Any]]
    history_key: str
    correlation_id: Optional[str]
    orchestration_plan: OrchestrationPlan
    persona_id: str | None
    cancel_token: CancelToken | None
    control: RunControl | None


class TaskOrchestrationStarter:
    """Start a parent orchestration without expanding TaskOrchestrator itself."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def start(
        self,
        request: TaskOrchestrationStartRequest,
    ) -> OrchestrationExecutionResult:
        cancel_token = _resolve_control(
            control=request.control,
            cancel_token=request.cancel_token,
        ).cancel_token
        workspace_root = await self._resolve_workspace_root(request)
        state = await self._create_running_state(
            request,
            cancel_token=cancel_token,
            workspace_root=workspace_root,
        )
        if isinstance(state, OrchestrationExecutionResult):
            return state

        todo_result = await self._persist_and_publish_todos(
            request,
            cancel_token=cancel_token,
            state=state,
        )
        if todo_result is not None:
            return todo_result

        launch_result = await self._launch_workers(
            request,
            cancel_token=cancel_token,
            state=state,
        )
        if launch_result is not None:
            return launch_result

        self._host._register_user_message(request.history_key, request.user_message)
        return _started_result(request, state)

    async def _resolve_workspace_root(
        self,
        request: TaskOrchestrationStartRequest,
    ) -> str | None:
        return await self._host._resolve_workspace_root(
            user_id=request.user_id,
            session_id=request.session_id,
            user_message=request.user_message,
        )

    async def _create_running_state(
        self,
        request: TaskOrchestrationStartRequest,
        *,
        cancel_token: CancelToken,
        workspace_root: str | None,
    ) -> TaskOrchestrationState | OrchestrationExecutionResult:
        plan_payload = await self._plan_subtasks(
            request,
            cancel_token=cancel_token,
            workspace_root=workspace_root,
        )
        if isinstance(plan_payload, OrchestrationExecutionResult):
            return plan_payload
        if await _consume_startup_cancellation(
            self._host,
            request,
            cancel_token=cancel_token,
            log_message="Discarding orchestration plan after cancellation",
        ):
            return _cancelled_result(request)
        if not plan_payload.subtasks:
            return _planning_failed_result(
                request,
                response="Failed to generate worker subtasks for this request.",
            )

        state = _build_orchestration_state(
            request,
            plan_payload=plan_payload,
            workspace_root=workspace_root,
        )
        if not state.subtasks:
            return _planning_failed_result(
                request,
                response="Failed to build execution-ready worker subtasks for this request.",
            )
        return state

    async def _persist_and_publish_todos(
        self,
        request: TaskOrchestrationStartRequest,
        *,
        cancel_token: CancelToken,
        state: TaskOrchestrationState,
    ) -> OrchestrationExecutionResult | None:
        await self._host._orchestration_store.save_orchestration(state)
        if await self._cancel_at_startup_boundary(
            request,
            cancel_token=cancel_token,
            state=state,
            log_message="Cancelling orchestration before todo publish",
        ):
            return _cancelled_result(request)

        if await self._cancel_at_startup_boundary(
            request,
            cancel_token=cancel_token,
            state=state,
            log_message="Cancelling orchestration after state persistence",
        ):
            return _cancelled_result(request)

        return None

    async def _launch_workers(
        self,
        request: TaskOrchestrationStartRequest,
        *,
        cancel_token: CancelToken,
        state: TaskOrchestrationState,
    ) -> OrchestrationExecutionResult | None:
        launch_error = await self._host._launch_workers(
            state,
            run_id=request.run_id,
            run_revision=request.run_revision,
        )
        if await self._cancel_at_startup_boundary(
            request,
            cancel_token=cancel_token,
            state=state,
            log_message="Cancelling orchestration after worker launch",
        ):
            return _cancelled_result(request)
        if launch_error:
            return await self._handle_launch_error(state, launch_error)

        return None

    async def _plan_subtasks(
        self,
        request: TaskOrchestrationStartRequest,
        *,
        cancel_token: CancelToken,
        workspace_root: str | None,
    ) -> SubtaskPlan | OrchestrationExecutionResult:
        try:
            return await _await_planning_result(
                cancel_token=cancel_token,
                session_id=request.session_id,
                run_id=request.run_id,
                run_revision=request.run_revision,
                planning_operation=self._host._plan_subtasks(
                    request.user_message,
                    request.history,
                    request.orchestration_plan,
                    request.user_id,
                    request.session_id,
                    request.run_id,
                    request.run_revision,
                    workspace_root=workspace_root,
                ),
            )
        except _PlanningCancelled:
            return _planning_cancelled_result(request)
        except RetractRaised:
            return _retracted_result(request)
        except CancellationRaised:
            return _llm_cancelled_result(request)

    async def _cancel_at_startup_boundary(
        self,
        request: TaskOrchestrationStartRequest,
        *,
        cancel_token: CancelToken,
        state: TaskOrchestrationState,
        log_message: str,
    ) -> bool:
        return await _consume_startup_cancellation(
            self._host,
            request,
            cancel_token=cancel_token,
            orchestration_id=state.orchestration_id,
            log_message=log_message,
            cancel_persisted_run=True,
        )

    async def _handle_launch_error(
        self,
        state: TaskOrchestrationState,
        launch_error: Exception,
    ) -> OrchestrationExecutionResult:
        state.status = "failed"
        state.updated_at = time.time()
        await self._host._orchestration_store.save_orchestration(state)
        await self._host._publish_task_lifecycle(
            state=state,
            status="error",
            error_type="LaunchError",
            error_message=str(launch_error)[:1000],
        )
        return OrchestrationExecutionResult(
            response=f"Failed to launch worker subtasks: {launch_error}",
            skip_emit=False,
            root_user_message=state.root_user_message,
            correlation_id=state.correlation_id,
            orchestration_id=state.orchestration_id,
            turn_id=state.turn_id,
        )


def _resolve_control(
    *,
    control: RunControl | None,
    cancel_token: CancelToken | None,
) -> RunControl:
    if control is not None:
        return control
    control = null_run_control()
    if cancel_token is not None:
        control.cancel_token = cancel_token
    return control


async def _await_planning_result(
    *,
    cancel_token: CancelToken,
    session_id: str,
    run_id: str | None,
    run_revision: int,
    planning_operation: Awaitable[Any],
) -> Any:
    planning_task = asyncio.create_task(
        planning_operation,
        name=f"task-orchestrator-plan:{session_id}:{run_id or 'none'}:{run_revision}",
    )
    cancel_wait_task = asyncio.create_task(
        cancel_token.wait(),
        name=f"task-orchestrator-plan-cancel:{session_id}:{run_id or 'none'}:{run_revision}",
    )
    try:
        done, pending = await asyncio.wait(
            {planning_task, cancel_wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_wait_task in done:
            planning_task.cancel()
            try:
                await planning_task
            except asyncio.CancelledError:
                pass
            raise _PlanningCancelled(cancel_token.reason or "cancelled")
        for task in pending:
            task.cancel()
        return await planning_task
    finally:
        if not cancel_wait_task.done():
            cancel_wait_task.cancel()
        try:
            await cancel_wait_task
        except asyncio.CancelledError:
            pass


async def _consume_startup_cancellation(
    host: Any,
    request: TaskOrchestrationStartRequest,
    *,
    cancel_token: CancelToken,
    log_message: str,
    orchestration_id: str | None = None,
    cancel_persisted_run: bool = False,
) -> bool:
    if not await cancel_token.is_cancelled():
        return False
    logger.info(
        log_message,
        session_id=request.session_id,
        run_id=request.run_id,
        run_revision=request.run_revision,
        orchestration_id=orchestration_id,
    )
    if cancel_persisted_run and request.run_id:
        await host.cancel_run(
            session_id=request.session_id,
            run_id=request.run_id,
            run_revision=request.run_revision,
        )
    return True


def _build_orchestration_state(
    request: TaskOrchestrationStartRequest,
    *,
    plan_payload: SubtaskPlan,
    workspace_root: str | None,
) -> TaskOrchestrationState:
    orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
    now = time.time()
    return TaskOrchestrationState(
        orchestration_id=orchestration_id,
        user_id=request.user_id,
        session_id=request.session_id,
        root_user_message=request.user_message,
        turn_id=request.turn_id,
        user_message_generation=request.user_message_generation,
        planner=str(request.orchestration_plan.planner or "task_agent"),
        workspace_root=workspace_root,
        status="running",
        retry_budget=DEFAULT_WORKER_RETRY_BUDGET,
        allow_parallel=bool(request.orchestration_plan.allow_parallel),
        created_at=now,
        updated_at=now,
        correlation_id=request.correlation_id,
        metadata={
            "run_id": request.run_id,
            "run_revision": request.run_revision,
            "root_turn_id": request.root_turn_id,
            "upstream_task_agent_type": request.upstream_task_agent_type,
            "upstream_task_agent_id": request.upstream_task_agent_id,
            "persona_id": str(request.persona_id or "").strip() or None,
        },
        subtasks=_build_subtask_definitions(plan_payload, created_at=now),
    )


def _build_subtask_definitions(
    plan_payload: SubtaskPlan,
    *,
    created_at: float,
) -> list[SubtaskDefinition]:
    return [
        SubtaskDefinition(
            subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
            description=item.description,
            subagent_type=item.subagent_type,
            prompt=item.prompt,
            parallel_group=item.parallel_group,
            status="pending",
            created_at=created_at,
            updated_at=created_at,
        )
        for item in plan_payload.subtasks
    ]


def _planning_failed_result(
    request: TaskOrchestrationStartRequest,
    *,
    response: str,
) -> OrchestrationExecutionResult:
    return OrchestrationExecutionResult(
        response=response,
        skip_emit=False,
        root_user_message=request.user_message,
        correlation_id=request.correlation_id,
        turn_id=request.turn_id,
    )


def _planning_cancelled_result(
    request: TaskOrchestrationStartRequest,
) -> OrchestrationExecutionResult:
    logger.info(
        "Aborted orchestration planner request after cancellation",
        session_id=request.session_id,
        run_id=request.run_id,
        run_revision=request.run_revision,
    )
    return _cancelled_result(request)


def _retracted_result(
    request: TaskOrchestrationStartRequest,
) -> OrchestrationExecutionResult:
    logger.info(
        "Orchestration plan aborted by retract signal",
        session_id=request.session_id,
        run_id=request.run_id,
        run_revision=request.run_revision,
    )
    return OrchestrationExecutionResult(
        response="",
        skip_emit=True,
        root_user_message=request.user_message,
        correlation_id=request.correlation_id,
        turn_id=request.turn_id,
        retracted=True,
    )


def _llm_cancelled_result(
    request: TaskOrchestrationStartRequest,
) -> OrchestrationExecutionResult:
    logger.info(
        "Orchestration plan aborted by cancellation (CancellableLLMClient)",
        session_id=request.session_id,
        run_id=request.run_id,
        run_revision=request.run_revision,
    )
    return _cancelled_result(request)


def _started_result(
    request: TaskOrchestrationStartRequest,
    state: TaskOrchestrationState,
) -> OrchestrationExecutionResult:
    return OrchestrationExecutionResult(
        response="",
        skip_emit=True,
        orchestration_id=state.orchestration_id,
        turn_id=request.turn_id,
    )


def _cancelled_result(
    request: TaskOrchestrationStartRequest,
) -> OrchestrationExecutionResult:
    return OrchestrationExecutionResult(
        response="",
        skip_emit=True,
        root_user_message=request.user_message,
        correlation_id=request.correlation_id,
        turn_id=request.turn_id,
    )


__all__ = [
    "TaskOrchestrationStartRequest",
    "TaskOrchestrationStarter",
]
