"""Fallback builders for legacy chat trace event streams."""

from __future__ import annotations

from typing import Any, Optional

from ..models import ExecutionTraceNode
from ..utils import (
    derive_children_status,
    normalize_status,
    safe_int,
    status_from_worker_event,
    tool_event_arguments,
    tool_event_result_preview,
    tool_event_status,
)


def build_orchestration_root(
    *,
    turn_id: str,
    events: list[dict[str, Any]],
    orchestration_id: Optional[str],
    orchestration_state: Optional[dict[str, Any]],
    started_at: float,
    ended_at: float,
) -> Optional[ExecutionTraceNode]:
    root = _tool_chain_root(
        turn_id=turn_id,
        started_at=started_at,
        ended_at=ended_at,
        metadata={"turn_id": turn_id, "orchestration_id": orchestration_id},
    )
    planning_node = _planning_node(
        turn_id=turn_id,
        orchestration_state=orchestration_state,
        started_at=started_at,
    )
    root.children.append(planning_node)

    tool_events_by_worker, worker_event_by_worker = _partition_worker_events(events)
    subtasks = _subtasks_from_state(orchestration_state)
    if subtasks:
        _append_subtask_groups(
            planning_node=planning_node,
            subtasks=subtasks,
            tool_events_by_worker=tool_events_by_worker,
            turn_id=turn_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        _finish_planning_node(planning_node, ended_at)
        return root

    worker_nodes = _worker_nodes_from_events(
        worker_event_by_worker=worker_event_by_worker,
        tool_events_by_worker=tool_events_by_worker,
        turn_id=turn_id,
        started_at=started_at,
        ended_at=ended_at,
    )
    if worker_nodes:
        planning_node.children.extend(worker_nodes)
        _finish_planning_node(planning_node, ended_at)
        return root

    return root


def _tool_chain_root(
    *,
    turn_id: str,
    started_at: float,
    ended_at: float,
    metadata: dict[str, Any],
) -> ExecutionTraceNode:
    return ExecutionTraceNode(
        id=f"{turn_id}:root",
        kind="root",
        label="Tool chain",
        status="running",
        started_at=started_at,
        ended_at=ended_at,
        metadata=metadata,
    )


def _planning_node(
    *,
    turn_id: str,
    orchestration_state: Optional[dict[str, Any]],
    started_at: float,
) -> ExecutionTraceNode:
    state = orchestration_state if isinstance(orchestration_state, dict) else {}
    return ExecutionTraceNode(
        id=f"{turn_id}:planning",
        kind="planning",
        label="Task orchestration",
        status="running",
        started_at=started_at,
        ended_at=None,
        metadata={
            "planner": state.get("planner"),
            "allow_parallel": bool(state.get("allow_parallel", True)),
        },
    )


def _partition_worker_events(
    events: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    tool_events_by_worker: dict[str, list[dict[str, Any]]] = {}
    worker_event_by_worker: dict[str, dict[str, Any]] = {}
    for item in events:
        payload = item.get("payload", {})
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id:
            continue
        worker_event_by_worker[worker_id] = item
        if (
            item["type"] == "WORKER_AGENT_PROGRESS"
            and str(payload.get("stage") or "") == "tool_result"
        ):
            tool_events_by_worker.setdefault(worker_id, []).append(item)
    return tool_events_by_worker, worker_event_by_worker


def _subtasks_from_state(
    orchestration_state: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    subtasks = []
    if isinstance(orchestration_state, dict):
        raw_subtasks = orchestration_state.get("subtasks")
        if isinstance(raw_subtasks, list):
            subtasks = [item for item in raw_subtasks if isinstance(item, dict)]
    return subtasks


def _group_node(
    *,
    turn_id: str,
    group_key: str,
    started_at: float,
) -> ExecutionTraceNode:
    return ExecutionTraceNode(
        id=f"{turn_id}:group:{group_key}",
        kind="parallel_group",
        label=f"Parallel tasks {group_key}",
        status="running",
        started_at=started_at,
        metadata={"parallel_group": group_key},
    )


def _subtask_worker_node(
    *,
    subtask: dict[str, Any],
    turn_id: str,
    group_key: str,
    started_at: float,
    ended_at: float,
) -> tuple[ExecutionTraceNode, str]:
    worker_id = str(subtask.get("worker_id") or "").strip()
    worker_status = normalize_status(str(subtask.get("status") or "pending"))
    raw_worker_result = subtask.get("worker_result")
    worker_result: dict[str, Any] = raw_worker_result if isinstance(raw_worker_result, dict) else {}
    return (
        ExecutionTraceNode(
            id=str(subtask.get("subtask_id") or f"{turn_id}:worker:{worker_id or group_key}"),
            kind="worker",
            label=str(subtask.get("description") or worker_id or "Worker"),
            status=worker_status,
            started_at=float(subtask.get("created_at") or started_at),
            ended_at=(
                float(subtask.get("updated_at") or ended_at)
                if worker_status in {"completed", "failed"}
                else None
            ),
            result_preview=str(worker_result.get("summary") or "").strip(),
            error=str(subtask.get("failure_reason") or "").strip() or None,
            metadata={
                "worker_id": worker_id or None,
                "subtask_id": subtask.get("subtask_id"),
                "subagent_type": subtask.get("subagent_type"),
                "parallel_group": group_key,
            },
        ),
        worker_id,
    )


def _append_worker_tool_nodes(
    *,
    worker_node: ExecutionTraceNode,
    tool_events: list[dict[str, Any]],
    turn_id: str,
) -> None:
    for index, tool_event in enumerate(tool_events, start=1):
        worker_node.children.append(
            build_worker_tool_node(tool_event, index=index, turn_id=turn_id)
        )


def _append_subtask_groups(
    *,
    planning_node: ExecutionTraceNode,
    subtasks: list[dict[str, Any]],
    tool_events_by_worker: dict[str, list[dict[str, Any]]],
    turn_id: str,
    started_at: float,
    ended_at: float,
) -> None:
    group_nodes: dict[str, ExecutionTraceNode] = {}
    for subtask in subtasks:
        group_key = str(subtask.get("parallel_group") or "default").strip() or "default"
        group_node = group_nodes.get(group_key)
        if group_node is None:
            group_node = _group_node(
                turn_id=turn_id,
                group_key=group_key,
                started_at=started_at,
            )
            planning_node.children.append(group_node)
            group_nodes[group_key] = group_node
        worker_node, worker_id = _subtask_worker_node(
            subtask=subtask,
            turn_id=turn_id,
            group_key=group_key,
            started_at=started_at,
            ended_at=ended_at,
        )
        _append_worker_tool_nodes(
            worker_node=worker_node,
            tool_events=tool_events_by_worker.get(worker_id, []),
            turn_id=turn_id,
        )
        group_node.children.append(worker_node)
    for group_node in group_nodes.values():
        group_node.status = derive_children_status(group_node.children)
        group_node.ended_at = ended_at if group_node.status in {"completed", "failed"} else None


def _worker_node_from_event(
    *,
    worker_id: str,
    item: dict[str, Any],
    turn_id: str,
    started_at: float,
    ended_at: float,
) -> ExecutionTraceNode:
    payload = item.get("payload", {})
    return ExecutionTraceNode(
        id=f"{turn_id}:worker:{worker_id}",
        kind="worker",
        label=str(payload.get("worker_description") or worker_id),
        status=status_from_worker_event(item["type"], payload),
        started_at=float(payload.get("timestamp") or started_at),
        ended_at=(
            float(payload.get("timestamp") or ended_at)
            if item["type"] != "WORKER_AGENT_PROGRESS"
            else None
        ),
        result_preview=str(payload.get("result_preview") or "").strip(),
        error=str(payload.get("error") or payload.get("failure_reason") or "").strip() or None,
        metadata={
            "worker_id": worker_id,
            "subtask_id": payload.get("subtask_id"),
            "subagent_type": payload.get("worker_subagent_type"),
        },
    )


def _worker_nodes_from_events(
    *,
    worker_event_by_worker: dict[str, dict[str, Any]],
    tool_events_by_worker: dict[str, list[dict[str, Any]]],
    turn_id: str,
    started_at: float,
    ended_at: float,
) -> list[ExecutionTraceNode]:
    worker_nodes = []
    for worker_id, item in worker_event_by_worker.items():
        worker_node = _worker_node_from_event(
            worker_id=worker_id,
            item=item,
            turn_id=turn_id,
            started_at=started_at,
            ended_at=ended_at,
        )
        _append_worker_tool_nodes(
            worker_node=worker_node,
            tool_events=tool_events_by_worker.get(worker_id, []),
            turn_id=turn_id,
        )
        worker_nodes.append(worker_node)
    return worker_nodes


def _finish_planning_node(planning_node: ExecutionTraceNode, ended_at: float) -> None:
    planning_node.status = derive_children_status(planning_node.children)
    planning_node.ended_at = ended_at if planning_node.status in {"completed", "failed"} else None


def build_function_root(
    *,
    turn_id: str,
    events: list[dict[str, Any]],
    started_at: float,
    ended_at: float,
) -> Optional[ExecutionTraceNode]:
    root = _tool_chain_root(
        turn_id=turn_id,
        started_at=started_at,
        ended_at=ended_at,
        metadata={"turn_id": turn_id},
    )
    iteration_nodes: dict[int, ExecutionTraceNode] = {}
    tool_events, loop_events = _function_trace_events(events)
    _seed_loop_iteration_nodes(
        iteration_nodes=iteration_nodes,
        loop_events=loop_events,
        turn_id=turn_id,
        started_at=started_at,
    )
    _append_function_tool_nodes(
        iteration_nodes=iteration_nodes,
        tool_events=tool_events,
        turn_id=turn_id,
        started_at=started_at,
        ended_at=ended_at,
    )

    if not iteration_nodes and not tool_events and not loop_events:
        return root

    _append_ordered_iterations(
        root=root,
        iteration_nodes=iteration_nodes,
        ended_at=ended_at,
    )
    return root


def _function_trace_events(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tool_events = [item for item in events if item["type"] in {"TOOL_INTERACTION", "TOOL_INVOKED"}]
    loop_events = [item for item in events if item["type"] == "CHAT_TOOL_LOOP_STEP"]
    return tool_events, loop_events


def _iteration_node(
    *,
    turn_id: str,
    iteration: int,
    timestamp: Any,
    started_at: float,
) -> ExecutionTraceNode:
    return ExecutionTraceNode(
        id=f"{turn_id}:iteration:{iteration}",
        kind="iteration",
        label=f"Round {iteration}",
        status="running",
        started_at=float(timestamp or started_at),
        metadata={"iteration": iteration},
    )


def _ensure_iteration_node(
    *,
    iteration_nodes: dict[int, ExecutionTraceNode],
    turn_id: str,
    iteration: int,
    timestamp: Any,
    started_at: float,
) -> ExecutionTraceNode:
    return iteration_nodes.setdefault(
        iteration,
        _iteration_node(
            turn_id=turn_id,
            iteration=iteration,
            timestamp=timestamp,
            started_at=started_at,
        ),
    )


def _seed_loop_iteration_nodes(
    *,
    iteration_nodes: dict[int, ExecutionTraceNode],
    loop_events: list[dict[str, Any]],
    turn_id: str,
    started_at: float,
) -> None:
    for loop_event in loop_events:
        payload = loop_event.get("payload", {})
        iteration = safe_int(payload.get("iteration"), default=1)
        if iteration <= 0:
            continue
        _ensure_iteration_node(
            iteration_nodes=iteration_nodes,
            turn_id=turn_id,
            iteration=iteration,
            timestamp=payload.get("timestamp"),
            started_at=started_at,
        )


def _function_tool_node(
    *,
    payload: dict[str, Any],
    turn_id: str,
    index: int,
    iteration: int,
    started_at: float,
    ended_at: float,
) -> ExecutionTraceNode:
    return ExecutionTraceNode(
        id=str(payload.get("tool_call_id") or f"{turn_id}:tool:{index}"),
        kind="tool",
        label=str(payload.get("tool_name") or f"Tool {index}"),
        status=tool_event_status(payload),
        started_at=float(payload.get("timestamp") or started_at),
        ended_at=float(payload.get("timestamp") or ended_at),
        result_preview=tool_event_result_preview(payload),
        error=str(payload.get("error") or "").strip() or None,
        metadata={
            "tool_call_id": payload.get("tool_call_id"),
            "arguments": tool_event_arguments(payload),
            "execution_time": payload.get("execution_time") or payload.get("execution_time_ms"),
            "iteration": iteration,
        },
    )


def _append_function_tool_nodes(
    *,
    iteration_nodes: dict[int, ExecutionTraceNode],
    tool_events: list[dict[str, Any]],
    turn_id: str,
    started_at: float,
    ended_at: float,
) -> None:
    for index, tool_event in enumerate(tool_events, start=1):
        payload = tool_event.get("payload", {})
        iteration = safe_int(payload.get("iteration"), default=1)
        iteration_node = _ensure_iteration_node(
            iteration_nodes=iteration_nodes,
            turn_id=turn_id,
            iteration=iteration,
            timestamp=payload.get("timestamp"),
            started_at=started_at,
        )
        iteration_node.children.append(
            _function_tool_node(
                payload=payload,
                turn_id=turn_id,
                index=index,
                iteration=iteration,
                started_at=started_at,
                ended_at=ended_at,
            )
        )


def _append_ordered_iterations(
    *,
    root: ExecutionTraceNode,
    iteration_nodes: dict[int, ExecutionTraceNode],
    ended_at: float,
) -> None:
    ordered_iterations = sorted(
        iteration_nodes.values(),
        key=lambda item: safe_int(item.metadata.get("iteration"), default=1),
    )
    for iteration_node in ordered_iterations:
        iteration_node.status = (
            derive_children_status(iteration_node.children)
            if iteration_node.children
            else "running"
        )
        iteration_node.ended_at = (
            ended_at if iteration_node.status in {"completed", "failed"} else None
        )
        root.children.append(iteration_node)


def build_worker_tool_node(
    item: dict[str, Any],
    *,
    index: int,
    turn_id: str,
) -> ExecutionTraceNode:
    payload = item.get("payload", {})
    return ExecutionTraceNode(
        id=f"{turn_id}:worker-tool:{payload.get('worker_id')}:{index}",
        kind="tool",
        label=str(payload.get("tool_name") or f"Tool {index}"),
        status="completed" if bool(payload.get("success")) else "failed",
        started_at=float(payload.get("timestamp") or item["timestamp"]),
        ended_at=float(payload.get("timestamp") or item["timestamp"]),
        result_preview=str(payload.get("result_preview") or "").strip(),
        error=str(payload.get("error") or "").strip() or None,
        metadata={
            "worker_id": payload.get("worker_id"),
            "execution_time": payload.get("execution_time"),
            "tool_name": payload.get("tool_name"),
        },
    )
