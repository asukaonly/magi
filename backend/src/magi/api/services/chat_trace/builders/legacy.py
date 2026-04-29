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
    root = ExecutionTraceNode(
        id=f"{turn_id}:root",
        kind="root",
        label="Tool chain",
        status="running",
        started_at=started_at,
        ended_at=ended_at,
        metadata={"turn_id": turn_id, "orchestration_id": orchestration_id},
    )
    planning_node = ExecutionTraceNode(
        id=f"{turn_id}:planning",
        kind="planning",
        label="Task orchestration",
        status="running",
        started_at=started_at,
        ended_at=None,
        metadata={
            "planner": orchestration_state.get("planner") if isinstance(orchestration_state, dict) else None,
            "allow_parallel": bool(orchestration_state.get("allow_parallel", True)) if isinstance(orchestration_state, dict) else True,
        },
    )
    root.children.append(planning_node)

    tool_events_by_worker: dict[str, list[dict[str, Any]]] = {}
    worker_event_by_worker: dict[str, dict[str, Any]] = {}
    for item in events:
        payload = item.get("payload", {})
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id:
            continue
        worker_event_by_worker[worker_id] = item
        if item["type"] == "WORKER_AGENT_PROGRESS" and str(payload.get("stage") or "") == "tool_result":
            tool_events_by_worker.setdefault(worker_id, []).append(item)

    subtasks = []
    if isinstance(orchestration_state, dict):
        raw_subtasks = orchestration_state.get("subtasks")
        if isinstance(raw_subtasks, list):
            subtasks = [item for item in raw_subtasks if isinstance(item, dict)]

    if subtasks:
        group_nodes: dict[str, ExecutionTraceNode] = {}
        for subtask in subtasks:
            group_key = str(subtask.get("parallel_group") or "default").strip() or "default"
            group_node = group_nodes.get(group_key)
            if group_node is None:
                group_node = ExecutionTraceNode(
                    id=f"{turn_id}:group:{group_key}",
                    kind="parallel_group",
                    label=f"Parallel tasks {group_key}",
                    status="running",
                    started_at=started_at,
                    metadata={"parallel_group": group_key},
                )
                planning_node.children.append(group_node)
                group_nodes[group_key] = group_node
            worker_id = str(subtask.get("worker_id") or "").strip()
            worker_status = normalize_status(str(subtask.get("status") or "pending"))
            worker_result = subtask.get("worker_result") if isinstance(subtask.get("worker_result"), dict) else {}
            worker_node = ExecutionTraceNode(
                id=str(subtask.get("subtask_id") or f"{turn_id}:worker:{worker_id or group_key}"),
                kind="worker",
                label=str(subtask.get("description") or worker_id or "Worker"),
                status=worker_status,
                started_at=float(subtask.get("created_at") or started_at),
                ended_at=float(subtask.get("updated_at") or ended_at) if worker_status in {"completed", "failed"} else None,
                result_preview=str(worker_result.get("summary") or "").strip(),
                error=str(subtask.get("failure_reason") or "").strip() or None,
                metadata={
                    "worker_id": worker_id or None,
                    "subtask_id": subtask.get("subtask_id"),
                    "subagent_type": subtask.get("subagent_type"),
                    "parallel_group": group_key,
                },
            )
            for index, tool_event in enumerate(tool_events_by_worker.get(worker_id, []), start=1):
                worker_node.children.append(build_worker_tool_node(tool_event, index=index, turn_id=turn_id))
            group_node.children.append(worker_node)
        for group_node in group_nodes.values():
            group_node.status = derive_children_status(group_node.children)
            group_node.ended_at = ended_at if group_node.status in {"completed", "failed"} else None
        planning_node.status = derive_children_status(planning_node.children)
        planning_node.ended_at = ended_at if planning_node.status in {"completed", "failed"} else None
        return root

    worker_nodes: list[ExecutionTraceNode] = []
    for worker_id, item in worker_event_by_worker.items():
        payload = item.get("payload", {})
        worker_node = ExecutionTraceNode(
            id=f"{turn_id}:worker:{worker_id}",
            kind="worker",
            label=str(payload.get("worker_description") or worker_id),
            status=status_from_worker_event(item["type"], payload),
            started_at=float(payload.get("timestamp") or started_at),
            ended_at=float(payload.get("timestamp") or ended_at) if item["type"] != "WORKER_AGENT_PROGRESS" else None,
            result_preview=str(payload.get("result_preview") or "").strip(),
            error=str(payload.get("error") or payload.get("failure_reason") or "").strip() or None,
            metadata={
                "worker_id": worker_id,
                "subtask_id": payload.get("subtask_id"),
                "subagent_type": payload.get("worker_subagent_type"),
            },
        )
        for index, tool_event in enumerate(tool_events_by_worker.get(worker_id, []), start=1):
            worker_node.children.append(build_worker_tool_node(tool_event, index=index, turn_id=turn_id))
        worker_nodes.append(worker_node)

    if worker_nodes:
        planning_node.children.extend(worker_nodes)
        planning_node.status = derive_children_status(planning_node.children)
        planning_node.ended_at = ended_at if planning_node.status in {"completed", "failed"} else None
        return root

    return root


def build_function_root(
    *,
    turn_id: str,
    events: list[dict[str, Any]],
    started_at: float,
    ended_at: float,
) -> Optional[ExecutionTraceNode]:
    root = ExecutionTraceNode(
        id=f"{turn_id}:root",
        kind="root",
        label="Tool chain",
        status="running",
        started_at=started_at,
        ended_at=ended_at,
        metadata={"turn_id": turn_id},
    )
    iteration_nodes: dict[int, ExecutionTraceNode] = {}
    tool_events = [item for item in events if item["type"] in {"TOOL_INTERACTION", "TOOL_INVOKED"}]
    loop_events = [item for item in events if item["type"] == "CHAT_TOOL_LOOP_STEP"]
    for loop_event in loop_events:
        payload = loop_event.get("payload", {})
        iteration = safe_int(payload.get("iteration"), default=1)
        if iteration <= 0:
            continue
        iteration_nodes.setdefault(
            iteration,
            ExecutionTraceNode(
                id=f"{turn_id}:iteration:{iteration}",
                kind="iteration",
                label=f"Round {iteration}",
                status="running",
                started_at=float(payload.get("timestamp") or started_at),
                metadata={"iteration": iteration},
            ),
        )

    for index, tool_event in enumerate(tool_events, start=1):
        payload = tool_event.get("payload", {})
        iteration = safe_int(payload.get("iteration"), default=1)
        iteration_node = iteration_nodes.setdefault(
            iteration,
            ExecutionTraceNode(
                id=f"{turn_id}:iteration:{iteration}",
                kind="iteration",
                label=f"Round {iteration}",
                status="running",
                started_at=float(payload.get("timestamp") or started_at),
                metadata={"iteration": iteration},
            ),
        )
        iteration_node.children.append(
            ExecutionTraceNode(
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
        )

    if not iteration_nodes and not tool_events and not loop_events:
        return root

    ordered_iterations = sorted(iteration_nodes.values(), key=lambda item: safe_int(item.metadata.get("iteration"), default=1))
    for iteration_node in ordered_iterations:
        iteration_node.status = derive_children_status(iteration_node.children) if iteration_node.children else "running"
        iteration_node.ended_at = ended_at if iteration_node.status in {"completed", "failed"} else None
        root.children.append(iteration_node)
    return root


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