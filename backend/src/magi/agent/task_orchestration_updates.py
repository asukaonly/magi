"""Worker update processing for task orchestration."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .runtime.contracts import FactRecord
from .orchestration import (
    OrchestrationExecutionResult,
    SubtaskDefinition,
    TaskOrchestrationState,
    WorkerResult,
)
from .task_orchestration_transitions import (
    is_terminal_state,
    mark_remaining_subtasks_cancelled,
)

WORKER_AGENT_EVENT_TYPES = {
    "WORKER_AGENT_PROGRESS",
    "WORKER_AGENT_COMPLETED",
    "WORKER_AGENT_FAILED",
}


@dataclass(frozen=True, slots=True)
class _WorkerUpdateContext:
    event_type: str
    payload: Any
    state: TaskOrchestrationState
    subtask: SubtaskDefinition
    payload_worker_id: str


class TaskOrchestrationUpdateProcessor:
    """Apply worker facts to orchestration state and emit completed results."""

    def __init__(self, host: Any) -> None:
        self._host = host

    async def process(self, batch_facts: list[Any]) -> OrchestrationExecutionResult:
        touched_states = await self._apply_batch_updates(batch_facts)
        await self._persist_touched_states(touched_states.values())
        completed_payloads = await self._finish_terminal_states(touched_states.values())
        return _combine_completed_payloads(completed_payloads)

    async def _apply_batch_updates(
        self,
        batch_facts: list[Any],
    ) -> dict[str, TaskOrchestrationState]:
        touched_states: dict[str, TaskOrchestrationState] = {}
        for fact in batch_facts:
            context = await self._load_update_context(fact, touched_states)
            if context is None:
                continue
            await self._apply_worker_update(context)
            touched_states[context.state.orchestration_id] = context.state
        return touched_states

    async def _load_update_context(
        self,
        fact: Any,
        touched_states: dict[str, TaskOrchestrationState],
    ) -> _WorkerUpdateContext | None:
        if not _is_worker_update_fact(fact):
            return None
        payload = _parse_worker_update_payload(fact.payload)
        orchestration_id = _clean_optional(payload.orchestration_id) if payload else ""
        subtask_id = _clean_optional(payload.subtask_id) if payload else ""
        if not orchestration_id or not subtask_id:
            return None

        state = await self._load_mutable_state(orchestration_id, touched_states)
        if state is None:
            return None
        subtask = state.get_subtask(subtask_id)
        if subtask is None:
            return None

        payload_worker_id = _clean_optional(payload.worker_id)
        if payload_worker_id and subtask.worker_id and payload_worker_id != subtask.worker_id:
            return None
        return _WorkerUpdateContext(
            event_type=fact.event_type,
            payload=payload,
            state=state,
            subtask=subtask,
            payload_worker_id=payload_worker_id,
        )

    async def _load_mutable_state(
        self,
        orchestration_id: str,
        touched_states: dict[str, TaskOrchestrationState],
    ) -> TaskOrchestrationState | None:
        state = touched_states.get(orchestration_id)
        if state is None:
            state = await self._host._orchestration_store.get_orchestration(orchestration_id)
        if state is None or state.status in {"completed", "failed", "cancelled"}:
            return None
        return state

    async def _apply_worker_update(self, context: _WorkerUpdateContext) -> None:
        if context.event_type == "WORKER_AGENT_PROGRESS":
            _mark_subtask_progress(context)
        elif context.event_type == "WORKER_AGENT_COMPLETED":
            await self._mark_subtask_completed(context)
        else:
            await self._mark_subtask_failed(context)

    async def _mark_subtask_completed(self, context: _WorkerUpdateContext) -> None:
        worker_result = context.payload.worker_result
        if worker_result is None and context.payload_worker_id:
            worker_result = await self._host._orchestration_store.get_worker_result(
                context.payload_worker_id
            )

        if not isinstance(worker_result, WorkerResult):
            context.subtask.status = "failed"
            context.subtask.failure_reason = "INVALID_WORKER_RESULT"
            context.subtask.failure_details = _build_subtask_failure_details(context.payload)
        elif not _worker_result_can_complete(context.subtask, worker_result):
            context.subtask.worker_result = worker_result
            context.subtask.status = "failed"
            context.subtask.failure_reason = "INVALID_WORKER_RESULT"
            context.subtask.failure_details = _build_subtask_failure_details(context.payload)
        elif worker_result.result_status == "failed":
            context.subtask.worker_result = worker_result
            context.subtask.failure_reason = (
                worker_result.failure_reason or "WORKER_REPORTED_FAILURE"
            )
            context.subtask.failure_details = _build_subtask_failure_details(context.payload)
            context.subtask.status = "failed"
        else:
            context.subtask.worker_result = worker_result
            context.subtask.failure_reason = None
            context.subtask.failure_details = None
            context.subtask.status = "completed"
        _touch_subtask_and_state(context)

    async def _mark_subtask_failed(self, context: _WorkerUpdateContext) -> None:
        failure_reason = str(
            context.payload.failure_reason or context.payload.error or "WORKER_FAILED"
        ).strip()
        retried = await self._host._maybe_retry_subtask(
            context.state,
            context.subtask,
            failure_reason,
        )
        if not retried:
            context.subtask.status = "failed"
            context.subtask.failure_reason = failure_reason
            context.subtask.failure_details = _build_subtask_failure_details(context.payload)
        _touch_subtask_and_state(context)

    async def _persist_touched_states(
        self,
        states: Iterable[TaskOrchestrationState],
    ) -> None:
        for state in states:
            await self._host._orchestration_store.save_orchestration(state)

    async def _finish_terminal_states(
        self,
        states: Iterable[TaskOrchestrationState],
    ) -> list[OrchestrationExecutionResult]:
        completed_payloads: list[OrchestrationExecutionResult] = []
        for state in states:
            if not is_terminal_state(state):
                continue
            if state.status == "cancelling":
                await self._finalize_cancelled_state(state)
                continue
            if state.status == "completed":
                continue
            completed = await self._aggregate_terminal_state(state)
            if completed is not None:
                completed_payloads.append(completed)
        return completed_payloads

    async def _finalize_cancelled_state(self, state: TaskOrchestrationState) -> None:
        mark_remaining_subtasks_cancelled(state)
        state.status = "cancelled"
        state.updated_at = time.time()
        await self._host._orchestration_store.save_orchestration(state)
        await self._host._publish_task_lifecycle(
            state=state,
            status="cancelled",
            error_type="Cancelled",
            error_message="Orchestration cancelled",
        )

    async def _aggregate_terminal_state(
        self,
        state: TaskOrchestrationState,
    ) -> OrchestrationExecutionResult | None:
        state.status = "aggregating"
        state.updated_at = time.time()
        await self._host._orchestration_store.save_orchestration(state)

        # TODO(phase-B): thread RunControl into aggregate callback so
        # a retract during aggregation observes the signal directly.
        final_response = await self._host._aggregate_orchestration(state)
        state.final_response = final_response
        state.status = "completed" if final_response.strip() else "failed"
        state.updated_at = time.time()
        await self._host._orchestration_store.save_orchestration(state)
        await self._publish_aggregation_lifecycle(state)
        return _completed_payload(state, final_response)

    async def _publish_aggregation_lifecycle(
        self,
        state: TaskOrchestrationState,
    ) -> None:
        if state.status == "completed":
            summary_text = (state.final_response or "")[:500] or None
            await self._host._publish_task_lifecycle(
                state=state,
                status="ok",
                summary=summary_text,
            )
            return
        await self._host._publish_task_lifecycle(
            state=state,
            status="error",
            error_type="AggregationFailed",
            error_message="Aggregator returned empty response",
        )


def _is_worker_update_fact(fact: Any) -> bool:
    return isinstance(fact, FactRecord) and fact.event_type in WORKER_AGENT_EVENT_TYPES


def _parse_worker_update_payload(payload: Any) -> Any | None:
    if not isinstance(payload, dict):
        return None
    from .task_agents.common.contracts import WorkerUpdatePayload

    return WorkerUpdatePayload.from_dict(payload, fallback_user_id="")


def _clean_optional(value: Any) -> str:
    return str(value or "").strip()


def _mark_subtask_progress(context: _WorkerUpdateContext) -> None:
    if context.subtask.status == "pending":
        context.subtask.status = "running"
    _touch_subtask_and_state(context)


def _worker_result_can_complete(
    subtask: SubtaskDefinition,
    worker_result: WorkerResult,
) -> bool:
    if worker_result.result_status not in {"success", "partial", "failed"}:
        return False
    if not worker_result.envelope_contract_valid or not worker_result.string_lists_valid:
        return False
    if not isinstance(worker_result.summary, str) or not worker_result.summary.strip():
        return False
    normalized_type = subtask.subagent_type.strip().casefold()
    if normalized_type in {"coding", "code"} and not worker_result.coding_contract_valid:
        return False
    if normalized_type == "plan" and (
        not worker_result.plan_contract_valid or not worker_result.subtasks
    ):
        return False
    if worker_result.result_status == "failed":
        return isinstance(worker_result.failure_reason, str) and bool(
            worker_result.failure_reason.strip()
        )
    if normalized_type == "plan":
        return True
    if normalized_type not in {"coding", "code"}:
        return True
    if not worker_result.artifacts or not worker_result.verification:
        return False
    if any(
        not isinstance(item.path, str)
        or not item.path.strip()
        or item.operation not in {"created", "modified", "deleted"}
        for item in worker_result.artifacts
    ):
        return False
    if any(
        not isinstance(item.command, str)
        or not item.command.strip()
        or item.status != "passed"
        or not isinstance(item.detail, str)
        or not item.detail.strip()
        for item in worker_result.verification
    ):
        return False
    if worker_result.result_status == "partial":
        return all(
            values and all(isinstance(item, str) and item.strip() for item in values)
            for values in (worker_result.gaps, worker_result.next_steps)
        )
    return True


def _touch_subtask_and_state(context: _WorkerUpdateContext) -> None:
    now = time.time()
    context.subtask.updated_at = now
    context.state.updated_at = now


def _build_subtask_failure_details(payload: Any) -> dict[str, Any] | None:
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
            _compact_tool_failure_for_aggregation(item)
            for item in tool_failures[:5]
            if isinstance(item, dict)
        ]
    _add_worker_result_failure_details(payload, details)
    return details or None


def _add_worker_result_failure_details(
    payload: Any,
    details: dict[str, Any],
) -> None:
    worker_result = getattr(payload, "worker_result", None)
    if not isinstance(worker_result, WorkerResult):
        return
    worker_payload = worker_result.to_dict()
    details["worker_result"] = {
        key: worker_payload.get(key)
        for key in ("summary", "gaps", "next_steps", "failure_reason")
        if worker_payload.get(key) not in (None, "", [], {})
    }


def _compact_tool_failure_for_aggregation(item: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in ("tool_name", "error_code", "error", "execution_time"):
        value = item.get(key)
        if value not in (None, "", [], {}):
            compact[key] = str(value)[:1000] if key == "error" else value
    _add_compact_diagnostics(item, compact)
    return compact


def _add_compact_diagnostics(
    item: dict[str, Any],
    compact: dict[str, Any],
) -> None:
    diagnostics = item.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return
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


def _completed_payload(
    state: TaskOrchestrationState,
    final_response: str,
) -> OrchestrationExecutionResult | None:
    if not final_response.strip():
        return None
    return OrchestrationExecutionResult(
        response=final_response,
        skip_emit=False,
        root_user_message=state.root_user_message,
        correlation_id=state.correlation_id,
        orchestration_id=state.orchestration_id,
        message_started_at=state.created_at,
        turn_id=state.turn_id,
        streamed=bool(state.metadata.get("aggregation_streamed")),
    )


def _combine_completed_payloads(
    completed_payloads: list[OrchestrationExecutionResult],
) -> OrchestrationExecutionResult:
    if not completed_payloads:
        return OrchestrationExecutionResult(response="", skip_emit=True)
    if len(completed_payloads) == 1:
        return completed_payloads[0]

    first = completed_payloads[0]
    return OrchestrationExecutionResult(
        response="\n\n".join(
            item.response for item in completed_payloads if str(item.response).strip()
        ),
        skip_emit=False,
        root_user_message=first.root_user_message,
        correlation_id=first.correlation_id,
        orchestration_id=",".join(
            str(item.orchestration_id or "") for item in completed_payloads if item.orchestration_id
        ),
        message_started_at=first.message_started_at,
        turn_id=first.turn_id,
        streamed=any(item.streamed for item in completed_payloads),
    )


__all__ = [
    "TaskOrchestrationUpdateProcessor",
    "WORKER_AGENT_EVENT_TYPES",
]
