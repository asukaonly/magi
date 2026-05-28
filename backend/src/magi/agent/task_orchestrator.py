"""Shared parent-task orchestration for task agents."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from .cancel import CancelToken, null_cancel_token
from .run_control import RunControl, null_run_control
from ..core.logger import get_logger
from ..llm.cancellable_client import CancellationRaised, RetractRaised
from ..agent.runtime.contracts import FactRecord
from ..events.events import Event, EventTypes
from ..events.domain_payloads import (
    SpanCompleted,
    TaskContext,
    ToolError,
)
from ..tools.registry import ToolRegistry
from .orchestration import (
    OrchestrationExecutionResult,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
    WorkerResult,
    get_orchestration_store,
)
from .task_orchestration_todos import TaskOrchestrationTodosMixin
from .task_orchestration_workers import TaskOrchestrationWorkerMixin
from .task_orchestration_workspace import TaskOrchestrationWorkspaceMixin

logger = get_logger(__name__)

WorkerPlanCallback = Callable[
    [str, list[dict[str, Any]], dict[str, Any], str, str, str | None, int],
    Awaitable[SubtaskPlan],
]
AggregateCallback = Callable[[TaskOrchestrationState], Awaitable[str]]
HistoryCallback = Callable[[str, str], None]
SessionWorkspaceProvider = Callable[..., Awaitable[str | None] | str | None]
ControlSessionStoreProvider = Callable[[], Any]

DEFAULT_WORKER_RETRY_BUDGET = 1


class _PlanningCancelled(RuntimeError):
    """Raised when orchestration planning is aborted by a cancel token."""


class TaskOrchestrator(
    TaskOrchestrationWorkerMixin,
    TaskOrchestrationTodosMixin,
    TaskOrchestrationWorkspaceMixin,
):
    """Runtime parent-task orchestrator shared by task agents."""

    WORKER_AGENT_EVENT_TYPES = {
        "WORKER_AGENT_PROGRESS",
        "WORKER_AGENT_COMPLETED",
        "WORKER_AGENT_FAILED",
    }

    def __init__(
        self,
        runtime_key: str,
        tool_registry: ToolRegistry,
        plan_subtasks: WorkerPlanCallback,
        aggregate_orchestration: AggregateCallback,
        register_user_message: HistoryCallback,
        parent_task_agent_type: str = "chat",
        session_workspace_provider: SessionWorkspaceProvider | None = None,
        control_session_store_provider: ControlSessionStoreProvider | None = None,
    ) -> None:
        self._runtime_key = runtime_key
        self._tool_registry = tool_registry
        self._plan_subtasks = plan_subtasks
        self._aggregate_orchestration = aggregate_orchestration
        self._register_user_message = register_user_message
        self._parent_task_agent_type = parent_task_agent_type
        self._session_workspace_provider = session_workspace_provider
        self._control_session_store_provider = control_session_store_provider
        self._orchestration_store = get_orchestration_store()

    @property
    def _event_bus(self):
        if not hasattr(self, "_event_bus_cached"):
            try:
                from ..core.container import get_container

                bus = get_container().message_bus()
            except Exception:
                bus = None
            if bus is None or type(bus).__name__ == "object":

                class _NoopBus:
                    async def publish(self, event):
                        return False

                bus = _NoopBus()
            self._event_bus_cached = bus
        return self._event_bus_cached

    async def _publish_task_lifecycle(
        self,
        *,
        state,
        status: str,
        summary: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        error: Optional[ToolError] = None,
    ) -> None:
        """Publish SpanCompleted(node_type='task_lifecycle') for terminal state.

        state must expose: orchestration_id, planner, created_at, updated_at,
        user_id, session_id, turn_id.
        """
        err_obj = error
        if err_obj is None and (error_type is not None or error_message is not None):
            err_obj = ToolError(
                type=error_type or "Error",
                message=(error_message or "")[:1000],
            )

        started_at_ms = int(state.created_at * 1000)
        ended_at_ms = int(state.updated_at * 1000)

        payload = SpanCompleted(
            span_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            parent_span_id=None,
            node_type="task_lifecycle",
            name=state.planner,
            status=status,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            duration_ms=ended_at_ms - started_at_ms,
            error=err_obj,
            result_preview=summary,
            turn_id=state.turn_id,
            attributes={
                "task_id": state.orchestration_id,
                "task_type": state.planner,
                "status": status,
                "summary": summary,
                "user_id": state.user_id,
                "session_id": state.session_id,
                "started_at": state.created_at,
                "finished_at": state.updated_at,
            },
        )
        try:
            await self._event_bus.publish(
                Event(
                    type=EventTypes.SPAN_COMPLETED,
                    data=payload,
                    source="task_orchestrator",
                    correlation_id=state.turn_id,
                )
            )
        except Exception:
            logger.exception("publish task_lifecycle SpanCompleted failed")

    def _build_task_context(self, state: TaskOrchestrationState) -> TaskContext:
        return TaskContext(
            session_id=state.session_id,
            turn_id=state.turn_id,
            task_id=state.orchestration_id,
            user_id=state.user_id,
        )

    async def _consume_startup_cancellation(
        self,
        *,
        cancel_token: CancelToken,
        session_id: str,
        run_id: str | None,
        run_revision: int,
        log_message: str,
        orchestration_id: str | None = None,
        cancel_persisted_run: bool = False,
    ) -> bool:
        """Return ``True`` after consuming a startup-time cancellation.

        The planner callback now has a transport-abort path, but cancellation
        can still arrive at later startup boundaries after planning completes.
        Re-check the shared cancel token before persisting or launching more
        orchestration work, and mark any persisted state as cancelled before
        the caller exits early.
        """
        if not await cancel_token.is_cancelled():
            return False
        logger.info(
            log_message,
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            orchestration_id=orchestration_id,
        )
        if cancel_persisted_run and run_id:
            await self.cancel_run(
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
            )
        return True

    async def _await_planning_result(
        self,
        *,
        cancel_token: CancelToken,
        session_id: str,
        run_id: str | None,
        run_revision: int,
        planning_operation: Awaitable[Any],
    ) -> Any:
        """Await the planner callback or cancel its task if the token fires.

        This is the transport-abort path for long planner LLM calls: the
        planning coroutine is promoted into its own task so a later cancel
        request can call ``task.cancel()`` and propagate cancellation down to
        the provider SDK / httpx await chain rather than waiting for the
        request to return and discarding the result afterwards.
        """
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

    async def start_orchestration(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        run_id: str | None = None,
        run_revision: int = 0,
        turn_id: Optional[str] = None,
        history: list[dict[str, Any]],
        history_key: str,
        correlation_id: Optional[str] = None,
        orchestration_strategy: dict[str, Any],
        persona_id: str | None = None,
        cancel_token: CancelToken | None = None,
        control: RunControl | None = None,
    ) -> OrchestrationExecutionResult:
        # Resolve the RunControl bundle.  If the caller supplies both
        # cancel_token (legacy path) and control (new path), control wins
        # and we overlay the legacy token onto it so both signals fire.
        if control is None:
            control = null_run_control()
            if cancel_token is not None:
                control.cancel_token = cancel_token
        resolved_cancel_token = control.cancel_token

        def _cancelled_result() -> OrchestrationExecutionResult:
            return OrchestrationExecutionResult(
                response="",
                skip_emit=True,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
            )

        workspace_root = await self._resolve_workspace_root(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
        )
        try:
            plan_payload = await self._await_planning_result(
                cancel_token=resolved_cancel_token,
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
                planning_operation=self._plan_subtasks(
                    user_message,
                    history,
                    orchestration_strategy,
                    user_id,
                    session_id,
                    run_id,
                    run_revision,
                    workspace_root=workspace_root,
                ),
            )
        except _PlanningCancelled:
            logger.info(
                "Aborted orchestration planner request after cancellation",
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
            )
            return _cancelled_result()
        except RetractRaised:
            logger.info(
                "Orchestration plan aborted by retract signal",
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
            )
            return OrchestrationExecutionResult(
                response="",
                skip_emit=True,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
                retracted=True,
            )
        except CancellationRaised:
            logger.info(
                "Orchestration plan aborted by cancellation (CancellableLLMClient)",
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
            )
            return _cancelled_result()
        if await self._consume_startup_cancellation(
            cancel_token=resolved_cancel_token,
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            log_message="Discarding orchestration plan after cancellation",
        ):
            return _cancelled_result()
        if not plan_payload.subtasks:
            return OrchestrationExecutionResult(
                response="Failed to generate worker subtasks for this request.",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
            )

        orchestration_id = f"orch_{uuid.uuid4().hex[:12]}"
        now = time.time()
        subtasks = [
            SubtaskDefinition(
                subtask_id=f"subtask_{uuid.uuid4().hex[:10]}",
                description=item.description,
                subagent_type=item.subagent_type,
                prompt=item.prompt,
                parallel_group=item.parallel_group,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            for item in plan_payload.subtasks
        ]
        if not subtasks:
            return OrchestrationExecutionResult(
                response="Failed to build execution-ready worker subtasks for this request.",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=correlation_id,
                turn_id=turn_id,
            )

        state = TaskOrchestrationState(
            orchestration_id=orchestration_id,
            user_id=user_id,
            session_id=session_id,
            root_user_message=user_message,
            turn_id=turn_id,
            planner=str(
                orchestration_strategy.get("planner", "task_agent") or "task_agent"
            ),
            workspace_root=workspace_root,
            status="running",
            retry_budget=DEFAULT_WORKER_RETRY_BUDGET,
            allow_parallel=bool(orchestration_strategy.get("allow_parallel", True)),
            created_at=now,
            updated_at=now,
            correlation_id=correlation_id,
            metadata={
                "run_id": run_id,
                "run_revision": run_revision,
                "persona_id": str(persona_id or "").strip() or None,
            },
            subtasks=subtasks,
        )
        await self._orchestration_store.save_orchestration(state)
        if await self._consume_startup_cancellation(
            cancel_token=resolved_cancel_token,
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            orchestration_id=state.orchestration_id,
            log_message="Cancelling orchestration before todo publish",
            cancel_persisted_run=True,
        ):
            return _cancelled_result()
        # Planner-owned todo list: publish the planned subtasks as the
        # session's todo list before any worker runs. Worker-side
        # ``todo_write`` is intentionally retired — the planner (i.e. this
        # orchestrator) is the single source of truth for todo lifecycle.
        await self._publish_session_todos(state)
        if await self._consume_startup_cancellation(
            cancel_token=resolved_cancel_token,
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            orchestration_id=state.orchestration_id,
            log_message="Cancelling orchestration after todo publish",
            cancel_persisted_run=True,
        ):
            return _cancelled_result()

        launch_error = await self._launch_workers(
            state,
            run_id=run_id,
            run_revision=run_revision,
        )
        if await self._consume_startup_cancellation(
            cancel_token=resolved_cancel_token,
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
            orchestration_id=state.orchestration_id,
            log_message="Cancelling orchestration after worker launch",
            cancel_persisted_run=True,
        ):
            return _cancelled_result()
        if launch_error:
            state.status = "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            await self._publish_task_lifecycle(
                state=state,
                status="error",
                error_type="LaunchError",
                error_message=str(launch_error)[:1000],
            )
            return OrchestrationExecutionResult(
                response=f"Failed to launch worker subtasks: {launch_error}",
                skip_emit=False,
                root_user_message=user_message,
                correlation_id=state.correlation_id,
                orchestration_id=state.orchestration_id,
                turn_id=state.turn_id,
            )

        self._register_user_message(history_key, user_message)
        return OrchestrationExecutionResult(
            response="",
            skip_emit=True,
            orchestration_id=orchestration_id,
            turn_id=turn_id,
        )

    async def process_worker_updates(
        self, batch_facts: list[Any]
    ) -> OrchestrationExecutionResult:
        from .task_agents.common.contracts import (
            WorkerUpdatePayload,
        )  # avoid circular import

        touched_states: dict[str, TaskOrchestrationState] = {}
        for fact in batch_facts:
            if (
                not isinstance(fact, FactRecord)
                or fact.event_type not in self.WORKER_AGENT_EVENT_TYPES
            ):
                continue

            payload = (
                WorkerUpdatePayload.from_dict(fact.payload, fallback_user_id="")
                if isinstance(fact.payload, dict)
                else None
            )
            orchestration_id = (
                str(payload.orchestration_id or "").strip() if payload else ""
            )
            subtask_id = str(payload.subtask_id or "").strip() if payload else ""
            if not orchestration_id or not subtask_id:
                continue

            state = touched_states.get(orchestration_id)
            if state is None:
                state = await self._orchestration_store.get_orchestration(
                    orchestration_id
                )
            if state is None or state.status in {"completed", "failed", "cancelled"}:
                continue

            subtask = state.get_subtask(subtask_id)
            if subtask is None:
                continue

            payload_worker_id = str(payload.worker_id or "").strip() if payload else ""
            if (
                payload_worker_id
                and subtask.worker_id
                and payload_worker_id != subtask.worker_id
            ):
                continue

            now = time.time()
            if fact.event_type == "WORKER_AGENT_PROGRESS":
                if subtask.status == "pending":
                    subtask.status = "running"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            if fact.event_type == "WORKER_AGENT_COMPLETED":
                worker_result = payload.worker_result if payload else None
                if worker_result is None and payload_worker_id:
                    worker_result = await self._orchestration_store.get_worker_result(
                        payload_worker_id
                    )
                if not isinstance(worker_result, WorkerResult):
                    subtask.status = "failed"
                    subtask.failure_reason = "INVALID_WORKER_RESULT"
                    subtask.failure_details = self._build_subtask_failure_details(payload)
                elif worker_result.result_status == "failed":
                    subtask.worker_result = worker_result
                    subtask.failure_reason = (
                        worker_result.failure_reason or "WORKER_REPORTED_FAILURE"
                    )
                    subtask.failure_details = self._build_subtask_failure_details(payload)
                    subtask.status = "failed"
                else:
                    subtask.worker_result = worker_result
                    subtask.failure_reason = None
                    subtask.failure_details = None
                    subtask.status = "completed"
                subtask.updated_at = now
                state.updated_at = now
                touched_states[state.orchestration_id] = state
                continue

            failure_reason = str(
                (payload.failure_reason if payload else None)
                or (payload.error if payload else None)
                or "WORKER_FAILED"
            ).strip()
            retried = await self._maybe_retry_subtask(state, subtask, failure_reason)
            if not retried:
                subtask.status = "failed"
                subtask.failure_reason = failure_reason
                subtask.failure_details = self._build_subtask_failure_details(payload)
            subtask.updated_at = now
            state.updated_at = now
            touched_states[state.orchestration_id] = state

        for state in touched_states.values():
            await self._orchestration_store.save_orchestration(state)
            await self._publish_session_todos(state)

        completed_payloads: list[OrchestrationExecutionResult] = []
        for state in touched_states.values():
            if not self._is_terminal(state):
                continue
            if state.status == "cancelling":
                self._mark_remaining_subtasks_cancelled(state)
                state.status = "cancelled"
                state.updated_at = time.time()
                await self._orchestration_store.save_orchestration(state)
                await self._publish_task_lifecycle(
                    state=state,
                    status="cancelled",
                    error_type="Cancelled",
                    error_message="Orchestration cancelled",
                )
                continue
            if state.status == "completed":
                continue
            state.status = "aggregating"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)

            # TODO(phase-B): thread RunControl into aggregate callback so
            # a retract during aggregation observes the signal directly
            # rather than completing the aggregate before the user-visible
            # cancellation propagates.
            final_response = await self._aggregate_orchestration(state)
            state.final_response = final_response
            state.status = "completed" if final_response.strip() else "failed"
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)

            if state.status == "completed":
                summary_text = (state.final_response or "")[:500] or None
                await self._publish_task_lifecycle(
                    state=state,
                    status="ok",
                    summary=summary_text,
                )
            else:
                await self._publish_task_lifecycle(
                    state=state,
                    status="error",
                    error_type="AggregationFailed",
                    error_message="Aggregator returned empty response",
                )

            if final_response.strip():
                completed_payloads.append(
                    OrchestrationExecutionResult(
                        response=final_response,
                        skip_emit=False,
                        root_user_message=state.root_user_message,
                        correlation_id=state.correlation_id,
                        orchestration_id=state.orchestration_id,
                        message_started_at=state.created_at,
                        turn_id=state.turn_id,
                        streamed=bool(state.metadata.get("aggregation_streamed")),
                    )
                )

        if not completed_payloads:
            return OrchestrationExecutionResult(response="", skip_emit=True)
        if len(completed_payloads) == 1:
            return completed_payloads[0]

        first = completed_payloads[0]
        return OrchestrationExecutionResult(
            response="\n\n".join(
                item.response
                for item in completed_payloads
                if str(item.response).strip()
            ),
            skip_emit=False,
            root_user_message=first.root_user_message,
            correlation_id=first.correlation_id,
            orchestration_id=",".join(
                str(item.orchestration_id or "")
                for item in completed_payloads
                if item.orchestration_id
            ),
            message_started_at=first.message_started_at,
            turn_id=first.turn_id,
            streamed=any(item.streamed for item in completed_payloads),
        )

    def _build_subtask_failure_details(self, payload: Any) -> dict[str, Any] | None:
        if payload is None:
            return None
        details: dict[str, Any] = {}
        error_text = str(
            getattr(payload, "error_text", None) or getattr(payload, "error", None) or ""
        ).strip()
        if error_text:
            details["error_text"] = error_text[:1000]
        tool_failures = getattr(payload, "tool_failures", None)
        if isinstance(tool_failures, list) and tool_failures:
            details["tool_failures"] = [
                self._compact_tool_failure_for_aggregation(item)
                for item in tool_failures[:5]
                if isinstance(item, dict)
            ]
        worker_result = getattr(payload, "worker_result", None)
        if isinstance(worker_result, WorkerResult):
            worker_payload = worker_result.to_dict()
            details["worker_result"] = {
                key: worker_payload.get(key)
                for key in ("summary", "gaps", "next_steps", "failure_reason")
                if worker_payload.get(key) not in (None, "", [], {})
            }
        return details or None

    @staticmethod
    def _compact_tool_failure_for_aggregation(item: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key in ("tool_name", "error_code", "error", "execution_time"):
            value = item.get(key)
            if value not in (None, "", [], {}):
                compact[key] = str(value)[:1000] if key == "error" else value
        diagnostics = item.get("diagnostics")
        if isinstance(diagnostics, dict):
            compact_diagnostics = {
                key: diagnostics[key]
                for key in (
                    "next_action",
                    "retryable",
                    "terminal",
                    "requested_provider",
                    "actual_provider",
                    "available_providers",
                    "supported_providers",
                    "fallback_reason",
                    "user_message_template",
                    "config_tool",
                )
                if key in diagnostics and diagnostics[key] not in (None, "", [], {})
            }
            if compact_diagnostics:
                compact["diagnostics"] = compact_diagnostics
        return compact

    async def cancel_run(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
    ) -> list[str]:
        """Cancel persisted orchestrations that belong to the specified run."""
        cancelled_ids: list[str] = []
        await self._cancel_live_workers(
            session_id=session_id,
            run_id=run_id,
            run_revision=run_revision,
        )
        candidate_states = await self._orchestration_store.list_orchestrations(
            session_id=session_id,
            statuses=["running", "aggregating", "cancelling"],
        )
        for state in candidate_states:
            if self._extract_run_id(state) != run_id:
                continue
            if self._extract_run_revision(state) != int(run_revision):
                continue
            self._mark_remaining_subtasks_cancelled(state)
            state.status = "cancelled"
            state.final_response = None
            state.updated_at = time.time()
            await self._orchestration_store.save_orchestration(state)
            await self._publish_task_lifecycle(
                state=state,
                status="cancelled",
                error_type="Cancelled",
                error_message="Orchestration cancelled",
            )
            cancelled_ids.append(state.orchestration_id)
        return cancelled_ids

    async def _cancel_live_workers(
        self,
        *,
        session_id: str,
        run_id: str,
        run_revision: int,
    ) -> list[str]:
        try:
            agent_tool = self._tool_registry.get_tool("agent")
            manager = getattr(agent_tool, "_manager", None)
            cancel_workers = getattr(manager, "cancel_run_workers", None)
            if not callable(cancel_workers):
                return []
            return await cancel_workers(
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
                reason="session_run_cancelled",
            )
        except (
            Exception
        ) as exc:  # noqa: BLE001 - cancellation must still mark orchestration state
            logger.warning(
                "Failed to cancel live worker tasks",
                session_id=session_id,
                run_id=run_id,
                run_revision=run_revision,
                error=str(exc),
            )
            return []

    @staticmethod
    def _extract_run_id(state: TaskOrchestrationState) -> str | None:
        metadata = getattr(state, "metadata", None)
        if isinstance(metadata, dict):
            run_id = str(metadata.get("run_id") or "").strip()
            return run_id or None
        return None

    @staticmethod
    def _extract_run_revision(state: TaskOrchestrationState) -> int:
        metadata = getattr(state, "metadata", None)
        if not isinstance(metadata, dict):
            return 0
        try:
            return int(metadata.get("run_revision") or 0)
        except (TypeError, ValueError):
            return 0

    def _mark_remaining_subtasks_cancelled(self, state: TaskOrchestrationState) -> None:
        now = time.time()
        for subtask in state.subtasks:
            if subtask.status in {"completed", "failed", "cancelled"}:
                continue
            subtask.status = "cancelled"
            subtask.updated_at = now

    def _is_terminal(self, state: TaskOrchestrationState) -> bool:
        return bool(state.subtasks) and all(
            item.status in {"completed", "failed", "cancelled"}
            for item in state.subtasks
        )
