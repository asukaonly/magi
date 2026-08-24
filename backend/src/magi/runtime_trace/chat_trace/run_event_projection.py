"""Project canonical agent-run events into chat execution read models."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from magi.agent.execution.contracts import AgentRunEvent, AgentRunEventType

from .models import (
    ExecutionPlanStepSummary,
    ExecutionPlanSummary,
    ExecutionTraceNode,
    ExecutionTraceSnapshot,
    ExecutionTraceSummary,
)

_TERMINAL_EVENT_STATUS = {
    AgentRunEventType.RUN_COMPLETED: "completed",
    AgentRunEventType.RUN_FAILED: "failed",
    AgentRunEventType.RUN_CANCELLED: "cancelled",
    AgentRunEventType.RUN_SUSPENDED: "suspended",
    AgentRunEventType.RUN_BLOCKED: "blocked",
}


def project_run_events(
    events: Iterable[AgentRunEvent | dict[str, Any]],
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    run_plan: dict[str, Any] | None = None,
) -> ExecutionTraceSnapshot | None:
    """Build all user-facing run state from one ordered event stream."""

    ordered = sorted((_coerce_event(item) for item in events), key=lambda item: item.sequence)
    if not ordered:
        return None
    run_id = ordered[0].run_id
    started_at_ms = ordered[0].created_at_ms
    terminal_event = next(
        (event for event in reversed(ordered) if event.event_type in _TERMINAL_EVENT_STATUS),
        None,
    )
    status = _TERMINAL_EVENT_STATUS.get(
        terminal_event.event_type if terminal_event is not None else None,
        "running",
    )
    ended_at_ms = terminal_event.created_at_ms if terminal_event is not None else None
    step_nodes = _project_step_nodes(ordered)
    plan_summary = _project_plan_summary(run_plan)
    metrics = _project_metrics(ordered, started_at_ms=started_at_ms, ended_at_ms=ended_at_ms)
    root = ExecutionTraceNode(
        id=f"run:{run_id}",
        kind="root",
        label="Agent run",
        status=status,
        started_at=started_at_ms / 1000,
        ended_at=(ended_at_ms / 1000 if ended_at_ms is not None else None),
        error=(
            str(terminal_event.payload.get("failure_reason") or "").strip() or None
            if status in {"failed", "blocked"} and terminal_event is not None
            else None
        ),
        metadata={
            "run_id": run_id,
            "canonical_run_events": True,
            "event_count": len(ordered),
        },
        children=step_nodes,
    )
    active_steps, completed_steps, failed_steps = _count_steps(step_nodes)
    summary = ExecutionTraceSummary(
        turn_id=turn_id,
        mode="agent_loop",
        status=status,
        headline=_headline(status=status, events=ordered),
        active_steps=active_steps,
        completed_steps=completed_steps,
        failed_steps=failed_steps,
        duration_seconds=round(
            max(0, (ended_at_ms or ordered[-1].created_at_ms) - started_at_ms) / 1000,
            3,
        ),
        trace_available=bool(step_nodes),
        plan_summary=plan_summary,
        total_input_tokens=int(metrics["input_tokens"]),
        total_output_tokens=int(metrics["output_tokens"]),
        total_reasoning_tokens=int(metrics["reasoning_tokens"]),
        runtime_metrics=metrics,
    )
    return ExecutionTraceSnapshot(
        turn_id=turn_id,
        user_id=user_id,
        session_id=session_id,
        status=status,
        mode="agent_loop",
        started_at=started_at_ms / 1000,
        ended_at=(ended_at_ms / 1000 if ended_at_ms is not None else None),
        continued_from_turn_id=None,
        continued_from_trace_id=None,
        superseded_by_turn_id=None,
        supersession_reason=None,
        summary=summary,
        root=root,
    )


def _project_step_nodes(events: list[AgentRunEvent]) -> list[ExecutionTraceNode]:
    by_step: dict[int, list[AgentRunEvent]] = defaultdict(list)
    run_level: list[AgentRunEvent] = []
    for event in events:
        if event.step_index is None:
            run_level.append(event)
        else:
            by_step[int(event.step_index)].append(event)
    nodes: list[ExecutionTraceNode] = []
    if run_level:
        run_children = _project_event_nodes(run_level)
        if run_children:
            nodes.extend(run_children)
    for step_index in sorted(by_step):
        step_events = by_step[step_index]
        children = _project_event_nodes(step_events)
        if not children:
            continue
        failed = any(child.status == "failed" for child in children)
        running = any(child.status in {"running", "pending"} for child in children)
        step_status = "failed" if failed else "running" if running else "completed"
        nodes.append(
            ExecutionTraceNode(
                id=f"step:{step_index}",
                kind="attempt",
                label=f"Step {step_index}",
                status=step_status,
                started_at=min(event.created_at_ms for event in step_events) / 1000,
                ended_at=(
                    None
                    if step_status == "running"
                    else max(event.created_at_ms for event in step_events) / 1000
                ),
                metadata={"step_index": step_index},
                children=children,
            )
        )
    exhausted_events = [
        event for event in events if event.event_type is AgentRunEventType.REPAIR_EXHAUSTED
    ]
    if exhausted_events:
        exhausted_at = max(event.created_at_ms for event in exhausted_events) / 1000
        for step in reversed(nodes):
            candidates = [step, *step.children]
            for child in reversed(candidates):
                if child.kind == "repair" and child.status == "running":
                    child.status = "failed"
                    child.ended_at = exhausted_at
                    child.error = "repair_exhausted"
                    if step.kind == "attempt":
                        step.status = "failed"
                        step.ended_at = exhausted_at
                    return nodes
    return nodes


def _project_event_nodes(events: list[AgentRunEvent]) -> list[ExecutionTraceNode]:
    nodes: list[ExecutionTraceNode] = []
    tool_nodes: dict[str, ExecutionTraceNode] = {}
    for event in events:
        payload = event.payload
        if event.event_type is AgentRunEventType.MODEL_OUTPUT:
            trace = payload.get("llm_trace") if isinstance(payload.get("llm_trace"), dict) else {}
            nodes.append(
                _node(
                    event,
                    kind="llm",
                    label="Model decision",
                    status="completed",
                    metadata={
                        "model": trace.get("model"),
                        "provider": trace.get("provider"),
                        "tool_call_count": len(payload.get("tool_calls") or []),
                    },
                )
            )
        elif event.event_type is AgentRunEventType.TOOL_CALL_REQUESTED:
            for raw in payload.get("tool_calls") or []:
                if not isinstance(raw, dict):
                    continue
                call_id = str(raw.get("id") or f"{event.event_id}:{len(tool_nodes)}")
                node = _node(
                    event,
                    node_id=f"tool:{call_id}",
                    kind="tool",
                    label=str(raw.get("name") or "Tool call"),
                    status="running",
                    metadata={
                        "tool_call_id": call_id,
                        "tool_name": raw.get("name"),
                        "arguments": raw.get("arguments"),
                    },
                )
                tool_nodes[call_id] = node
                nodes.append(node)
        elif event.event_type is AgentRunEventType.TOOL_RESULT:
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            call_id = str(metadata.get("tool_call_id") or "").strip()
            node = tool_nodes.get(call_id)
            if node is None:
                node = _node(
                    event,
                    node_id=f"tool:{call_id or event.event_id}",
                    kind="tool",
                    label=str(payload.get("source") or "Tool call"),
                    status="running",
                    metadata={"tool_call_id": call_id or None},
                )
                nodes.append(node)
            node.status = "completed" if payload.get("status") == "succeeded" else "failed"
            node.ended_at = event.created_at_ms / 1000
            node.error = str(metadata.get("error_code") or "").strip() or None
            node.metadata.update(
                {
                    "effect_class": metadata.get("effect_class"),
                    "replay_policy": metadata.get("replay_policy"),
                    "evidence_id": payload.get("evidence_id"),
                }
            )
        elif event.event_type in {
            AgentRunEventType.CHILD_STARTED,
            AgentRunEventType.CHILD_COMPLETED,
            AgentRunEventType.CHILD_CANCELLED,
        }:
            child_id = str(payload.get("child_run_id") or event.event_id)
            previous = next((item for item in nodes if item.id == f"child:{child_id}"), None)
            child_status = _child_status(event)
            if previous is None:
                nodes.append(
                    _node(
                        event,
                        node_id=f"child:{child_id}",
                        kind="worker",
                        label=str(payload.get("preset") or "Child run"),
                        status=child_status,
                        metadata=dict(payload),
                    )
                )
            else:
                previous.status = child_status
                previous.ended_at = (
                    event.created_at_ms / 1000 if child_status != "running" else None
                )
                previous.metadata.update(payload)
        elif event.event_type is AgentRunEventType.VALIDATION_COMPLETED:
            nodes.append(
                _node(
                    event,
                    kind="validation",
                    label="Validation",
                    status="completed" if bool(payload.get("success")) else "failed",
                    metadata=dict(payload),
                )
            )
        elif event.event_type is AgentRunEventType.REPAIR_STARTED:
            nodes.append(
                _node(
                    event,
                    kind="repair",
                    label="Repairing completion requirements",
                    status="running",
                    metadata=dict(payload),
                )
            )
        elif event.event_type is AgentRunEventType.REPAIR_EXHAUSTED:
            nodes.append(
                _node(
                    event,
                    kind="repair",
                    label="Repair budget exhausted",
                    status="failed",
                    error=str(payload.get("reason_code") or "repair_exhausted"),
                    metadata=dict(payload),
                )
            )
        elif event.event_type is AgentRunEventType.COMPLETION_REJECTED:
            nodes.append(
                _node(
                    event,
                    kind="validation",
                    label="Completion check",
                    status="failed" if not payload.get("repairable") else "pending",
                    error=str(payload.get("reason_code") or "").strip() or None,
                    metadata=dict(payload),
                )
            )
        elif event.event_type is AgentRunEventType.REASONING_DEPTH_CHANGED:
            nodes.append(
                _node(
                    event,
                    kind="reasoning",
                    label="Reasoning depth adjusted",
                    status="completed",
                    metadata=dict(payload),
                )
            )
    if any(event.event_type is AgentRunEventType.REPAIR_STEP_STARTED for event in events):
        for node in reversed(nodes):
            if node.kind == "repair" and node.status == "running":
                node.status = "completed"
                node.ended_at = max(event.created_at_ms for event in events) / 1000
                break
    return nodes


def _project_plan_summary(plan: dict[str, Any] | None) -> ExecutionPlanSummary | None:
    if not isinstance(plan, dict):
        return None
    raw_items = plan.get("items") if isinstance(plan.get("items"), list) else []
    steps = [
        ExecutionPlanStepSummary(
            subtask_id=str(item.get("id") or "").strip() or None,
            label=str(item.get("content") or item.get("title") or "").strip(),
            status=str(item.get("status") or "pending"),
        )
        for item in raw_items
        if isinstance(item, dict)
        and str(item.get("content") or item.get("title") or "").strip()
    ]
    if not steps:
        return None
    terminal = sum(step.status in {"completed", "blocked", "skipped", "cancelled"} for step in steps)
    return ExecutionPlanSummary(
        planner="main_model",
        parallel_mode="sequential",
        total_steps=len(steps),
        remaining_steps=max(0, len(steps) - terminal),
        steps=steps,
    )


def _project_metrics(
    events: list[AgentRunEvent],
    *,
    started_at_ms: int,
    ended_at_ms: int | None,
) -> dict[str, Any]:
    event_types = [event.event_type for event in events]
    model_events = [event for event in events if event.event_type is AgentRunEventType.MODEL_OUTPUT]
    tool_results = [event for event in events if event.event_type is AgentRunEventType.TOOL_RESULT]
    validations = [
        event for event in events if event.event_type is AgentRunEventType.VALIDATION_COMPLETED
    ]
    first_action = next(
        (
            event
            for event in events
            if event.event_type
            in {
                AgentRunEventType.MODEL_OUTPUT,
                AgentRunEventType.TOOL_CALL_REQUESTED,
                AgentRunEventType.CHILD_STARTED,
                AgentRunEventType.COMPLETION_REQUESTED,
            }
        ),
        None,
    )
    input_tokens = output_tokens = reasoning_tokens = 0
    for event in model_events:
        trace = event.payload.get("llm_trace")
        if not isinstance(trace, dict):
            continue
        input_tokens += _int_value(trace.get("input_tokens") or trace.get("prompt_tokens"))
        output_tokens += _int_value(trace.get("output_tokens") or trace.get("completion_tokens"))
        reasoning_tokens += _int_value(trace.get("reasoning_tokens"))
    return {
        "runtime_latency_ms": max(
            0,
            int((ended_at_ms or events[-1].created_at_ms) - started_at_ms),
        ),
        "first_action_latency_ms": (
            max(0, first_action.created_at_ms - started_at_ms)
            if first_action is not None
            else None
        ),
        "model_calls": len(model_events),
        "tool_calls": sum(
            len(event.payload.get("tool_calls") or [])
            for event in events
            if event.event_type is AgentRunEventType.TOOL_CALL_REQUESTED
        ),
        "tool_failures": sum(event.payload.get("status") != "succeeded" for event in tool_results),
        "tool_recovery_expansions": event_types.count(AgentRunEventType.CAPABILITIES_EXPANDED),
        "validation_attempts": len(validations),
        "validation_failures": sum(not bool(event.payload.get("success")) for event in validations),
        "repair_iterations": event_types.count(AgentRunEventType.REPAIR_STARTED),
        "repair_exhaustions": event_types.count(AgentRunEventType.REPAIR_EXHAUSTED),
        "reasoning_escalations": event_types.count(AgentRunEventType.REASONING_DEPTH_CHANGED),
        "child_fanout": event_types.count(AgentRunEventType.CHILD_STARTED),
        "child_cancellations": event_types.count(AgentRunEventType.CHILD_CANCELLED),
        "completion_gate_checks": event_types.count(AgentRunEventType.COMPLETION_REQUESTED),
        "completion_gate_rejections": event_types.count(AgentRunEventType.COMPLETION_REJECTED),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _headline(*, status: str, events: list[AgentRunEvent]) -> str:
    if status == "completed":
        return "Run completed"
    if status == "failed":
        return "Run failed"
    if status == "cancelled":
        return "Run cancelled"
    if status == "suspended":
        return "Run suspended"
    if status == "blocked":
        return "Run blocked"
    if any(event.event_type is AgentRunEventType.REPAIR_STARTED for event in events):
        return "Repairing and validating"
    if any(event.event_type is AgentRunEventType.CHILD_STARTED for event in events):
        return "Running child tasks"
    if any(event.event_type is AgentRunEventType.TOOL_CALL_REQUESTED for event in events):
        return "Running tools"
    return "Thinking"


def _node(
    event: AgentRunEvent,
    *,
    kind: str,
    label: str,
    status: str,
    node_id: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionTraceNode:
    terminal = status not in {"running", "pending"}
    return ExecutionTraceNode(
        id=node_id or event.event_id,
        kind=kind,
        label=label,
        status=status,
        started_at=event.created_at_ms / 1000,
        ended_at=(event.created_at_ms / 1000 if terminal else None),
        error=error,
        metadata=dict(metadata or {}),
    )


def _child_status(event: AgentRunEvent) -> str:
    if event.event_type is AgentRunEventType.CHILD_STARTED:
        return "running"
    if event.event_type is AgentRunEventType.CHILD_CANCELLED:
        return "cancelled"
    return "failed" if event.payload.get("status") == "failed" else "completed"


def _count_steps(nodes: list[ExecutionTraceNode]) -> tuple[int, int, int]:
    semantic = [node for node in _walk(nodes) if node.kind in {"attempt", "tool", "worker", "validation", "repair"}]
    active = sum(node.status in {"running", "pending"} for node in semantic)
    failed = sum(node.status == "failed" for node in semantic)
    return active, len(semantic) - active - failed, failed


def _walk(nodes: list[ExecutionTraceNode]) -> list[ExecutionTraceNode]:
    output: list[ExecutionTraceNode] = []
    for node in nodes:
        output.append(node)
        output.extend(_walk(node.children))
    return output


def _coerce_event(value: AgentRunEvent | dict[str, Any]) -> AgentRunEvent:
    return value if isinstance(value, AgentRunEvent) else AgentRunEvent.from_dict(value)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["project_run_events"]
