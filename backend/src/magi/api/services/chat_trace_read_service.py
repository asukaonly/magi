"""Read-side aggregation service for per-turn execution traces."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ...core.logger import get_logger
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = "runtime_observations"
USER_EVENT_TYPES = ("UserMessage",)
AI_RESPONSE_EVENT_TYPES = ("AIResponse",)
WORKER_EVENT_TYPES = ("WORKER_AGENT_PROGRESS", "WORKER_AGENT_COMPLETED", "WORKER_AGENT_FAILED")
LEGACY_TRACE_EVENT_TYPES = ("CHAT_TOOL_LOOP_STEP", "TOOL_INTERACTION", "TOOL_INVOKED")
TURN_TRACE_EVENT_TYPES = ("TURN_TRACE_STARTED", "TURN_TRACE_COMPLETED", "TURN_TRACE_FAILED")
TRACE_NODE_EVENT_TYPES = ("TRACE_NODE_STARTED", "TRACE_NODE_COMPLETED", "TRACE_NODE_FAILED")
TRACE_EVENT_TYPES = WORKER_EVENT_TYPES + LEGACY_TRACE_EVENT_TYPES + TURN_TRACE_EVENT_TYPES + TRACE_NODE_EVENT_TYPES
FACT_DISPLAY_EVENT_TYPES = USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES


@dataclass(slots=True)
class ExecutionTraceNode:
    """One node in the UI-facing execution trace tree."""

    id: str
    kind: str
    label: str
    status: str
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    result_preview: str = ""
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["ExecutionTraceNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result_preview": self.result_preview,
            "error": self.error,
            "metadata": dict(self.metadata),
            "children": [child.to_dict() for child in self.children],
        }


@dataclass(slots=True)
class ExecutionTraceSummary:
    """Compact summary used by chat status cards and assistant chips."""

    turn_id: str
    mode: str
    status: str
    headline: str
    active_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    duration_seconds: float = 0.0
    trace_available: bool = False
    orchestration_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "mode": self.mode,
            "status": self.status,
            "headline": self.headline,
            "active_steps": self.active_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "duration_seconds": self.duration_seconds,
            "trace_available": self.trace_available,
            "orchestration_id": self.orchestration_id,
        }


@dataclass(slots=True)
class ExecutionTraceSnapshot:
    """Full turn snapshot returned to the frontend drawer."""

    turn_id: str
    user_id: str
    session_id: str
    status: str
    mode: str
    orchestration_id: Optional[str]
    started_at: Optional[float]
    ended_at: Optional[float]
    summary: ExecutionTraceSummary
    root: ExecutionTraceNode

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "mode": self.mode,
            "orchestration_id": self.orchestration_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "summary": self.summary.to_dict(),
            "root": self.root.to_dict(),
        }


class ChatTraceReadService:
    """Build per-turn execution snapshots from persisted events and orchestration state."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._orchestrations_path: Path = runtime_paths.data_dir / "task_orchestrations.json"

    def get_trace_snapshot(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            return None
        events = self._load_turn_events(user_id=user_id, session_id=session_id, turn_id=normalized_turn_id)
        if not events:
            return None
        snapshot = self._build_snapshot(
            user_id=user_id,
            session_id=session_id,
            turn_id=normalized_turn_id,
            events=events,
        )
        return snapshot.to_dict() if snapshot is not None else None

    def get_trace_summary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        snapshot = self.get_trace_snapshot(user_id=user_id, session_id=session_id, turn_id=turn_id)
        if not isinstance(snapshot, dict):
            return None
        summary = snapshot.get("summary")
        return summary if isinstance(summary, dict) else None

    def get_turn_activity_map(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        events = self._load_session_events(user_id=user_id, session_id=session_id)
        turn_ids = sorted(
            {
                str(item["payload"].get("turn_id") or "").strip()
                for item in events
                if isinstance(item.get("payload"), dict)
            }
        )
        activity: dict[str, dict[str, Any]] = {}
        for turn_id in turn_ids:
            if not turn_id:
                continue
            summary = self.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
            if summary is not None:
                activity[turn_id] = summary
        return activity

    def _build_snapshot(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        events: list[dict[str, Any]],
    ) -> Optional[ExecutionTraceSnapshot]:
        user_event = next((item for item in events if item["type"] in USER_EVENT_TYPES), None)
        response_event = next((item for item in reversed(events) if item["type"] in AI_RESPONSE_EVENT_TYPES), None)
        orchestration_id = self._extract_orchestration_id(events)
        orchestration_state = self._load_orchestration_state(orchestration_id) if orchestration_id else None
        has_worker_events = any(item["type"] in WORKER_EVENT_TYPES for item in events)
        has_tool_events = any(item["type"] in LEGACY_TRACE_EVENT_TYPES for item in events)
        fallback_started_at = float(user_event["timestamp"]) if user_event else float(events[0]["timestamp"])
        fallback_ended_at = float(response_event["timestamp"]) if response_event else float(events[-1]["timestamp"])

        root = self._build_normalized_trace_root(
            turn_id=turn_id,
            events=events,
            started_at=fallback_started_at,
            ended_at=fallback_ended_at,
        )
        if root is not None:
            started_at = root.started_at if root.started_at is not None else fallback_started_at
            ended_at = root.ended_at if root.ended_at is not None else fallback_ended_at
            mode = self._resolve_normalized_mode(
                root=root,
                orchestration_id=orchestration_id,
                orchestration_state=orchestration_state,
            )
        else:
            mode = "orchestration" if orchestration_state or has_worker_events else "function_calling"
            started_at = fallback_started_at
            ended_at = fallback_ended_at
            if mode == "orchestration":
                root = self._build_orchestration_root(
                    turn_id=turn_id,
                    events=events,
                    orchestration_id=orchestration_id,
                    orchestration_state=orchestration_state,
                    started_at=started_at,
                    ended_at=ended_at,
                )
            else:
                root = self._build_function_root(
                    turn_id=turn_id,
                    events=events,
                    started_at=started_at,
                    ended_at=ended_at,
                )

        if root is None:
            return None

        status = root.status if self._has_normalized_trace_events(events) else self._resolve_snapshot_status(
            root=root,
            response_event=response_event,
            orchestration_state=orchestration_state,
        )
        if status == "running" and response_event is not None:
            status = "completed"
        if status == "running":
            status = self._resolve_turn_trace_status(events, default=status)
        if status in {"completed", "failed"}:
            self._finalize_terminal_nodes(root, status=status, ended_at=ended_at)
        root.status = status
        root.ended_at = ended_at if status in {"completed", "failed"} else None

        active_steps, completed_steps, failed_steps = self._count_steps(root)
        summary = ExecutionTraceSummary(
            turn_id=turn_id,
            mode=mode,
            status=status,
            headline=self._build_headline(
                mode=mode,
                status=status,
                active_steps=active_steps,
                completed_steps=completed_steps,
                orchestration_state=orchestration_state,
            ),
            active_steps=active_steps,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            duration_seconds=round(max(0.0, ended_at - started_at), 3),
            trace_available=bool(root.children),
            orchestration_id=orchestration_id,
        )

        return ExecutionTraceSnapshot(
            turn_id=turn_id,
            user_id=user_id,
            session_id=session_id,
            status=status,
            mode=mode,
            orchestration_id=orchestration_id,
            started_at=started_at,
            ended_at=root.ended_at,
            summary=summary,
            root=root,
        )

    def _build_orchestration_root(
        self,
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
                worker_status = self._normalize_status(str(subtask.get("status") or "pending"))
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
                    worker_node.children.append(self._build_worker_tool_node(tool_event, index=index, turn_id=turn_id))
                group_node.children.append(worker_node)
            for group_node in group_nodes.values():
                group_node.status = self._derive_rollup_status(group_node.children)
                group_node.ended_at = ended_at if group_node.status in {"completed", "failed"} else None
            planning_node.status = self._derive_parent_status(planning_node.children)
            planning_node.ended_at = ended_at if planning_node.status in {"completed", "failed"} else None
            return root

        worker_nodes: list[ExecutionTraceNode] = []
        for worker_id, item in worker_event_by_worker.items():
            payload = item.get("payload", {})
            worker_node = ExecutionTraceNode(
                id=f"{turn_id}:worker:{worker_id}",
                kind="worker",
                label=str(payload.get("worker_description") or worker_id),
                status=self._status_from_worker_event(item["type"], payload),
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
                worker_node.children.append(self._build_worker_tool_node(tool_event, index=index, turn_id=turn_id))
            worker_nodes.append(worker_node)

        if worker_nodes:
            planning_node.children.extend(worker_nodes)
            planning_node.status = self._derive_parent_status(planning_node.children)
            planning_node.ended_at = ended_at if planning_node.status in {"completed", "failed"} else None
            return root

        return root

    def _build_function_root(
        self,
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
            iteration = self._safe_int(payload.get("iteration"), default=1)
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
            iteration = self._safe_int(payload.get("iteration"), default=1)
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
                    status=self._tool_event_status(payload),
                    started_at=float(payload.get("timestamp") or started_at),
                    ended_at=float(payload.get("timestamp") or ended_at),
                    result_preview=self._tool_event_result_preview(payload),
                    error=str(payload.get("error") or "").strip() or None,
                    metadata={
                        "tool_call_id": payload.get("tool_call_id"),
                        "arguments": self._tool_event_arguments(payload),
                        "execution_time": payload.get("execution_time") or payload.get("execution_time_ms"),
                        "iteration": iteration,
                    },
                )
            )

        if not iteration_nodes and not tool_events and not loop_events:
            return root

        ordered_iterations = sorted(iteration_nodes.values(), key=lambda item: self._safe_int(item.metadata.get("iteration"), default=1))
        for iteration_node in ordered_iterations:
            iteration_node.status = self._derive_rollup_status(iteration_node.children) if iteration_node.children else "running"
            iteration_node.ended_at = ended_at if iteration_node.status in {"completed", "failed"} else None
            root.children.append(iteration_node)
        return root

    def _build_normalized_trace_root(
        self,
        *,
        turn_id: str,
        events: list[dict[str, Any]],
        started_at: float,
        ended_at: float,
    ) -> Optional[ExecutionTraceNode]:
        span_payloads = self._collapse_trace_spans(events)
        if not span_payloads:
            return None

        node_by_span_id: dict[str, ExecutionTraceNode] = {}
        children_by_parent: dict[str | None, list[str]] = {}
        for span_id, payload in span_payloads.items():
            node_by_span_id[span_id] = self._build_trace_span_node(payload)
            parent_span_id = str(payload.get("parent_span_id") or "").strip() or None
            children_by_parent.setdefault(parent_span_id, []).append(span_id)

        for parent_span_id, child_ids in children_by_parent.items():
            if parent_span_id is None:
                continue
            parent = node_by_span_id.get(parent_span_id)
            if parent is None:
                continue
            ordered_children = sorted(
                (node_by_span_id[child_id] for child_id in child_ids if child_id in node_by_span_id),
                key=lambda item: (
                    float(item.started_at or 0.0),
                    item.id,
                ),
            )
            parent.children.extend(ordered_children)

        turn_span_id = f"{turn_id}:turn"
        turn_node = node_by_span_id.get(turn_span_id)
        top_level_nodes = [
            node_by_span_id[span_id]
            for span_id in children_by_parent.get(None, [])
            if span_id in node_by_span_id and span_id != turn_span_id
        ]
        top_level_nodes.sort(key=lambda item: (float(item.started_at or 0.0), item.id))

        root = ExecutionTraceNode(
            id=f"{turn_id}:root",
            kind="root",
            label="Tool chain",
            status=turn_node.status if turn_node is not None else self._derive_parent_status(top_level_nodes),
            started_at=turn_node.started_at if turn_node is not None else started_at,
            ended_at=turn_node.ended_at if turn_node is not None else ended_at,
            result_preview=turn_node.result_preview if turn_node is not None else "",
            error=turn_node.error if turn_node is not None else None,
            metadata={
                "turn_id": turn_id,
                "trace_id": str((turn_node.metadata if turn_node is not None else {}).get("trace_id") or f"trace:{turn_id}"),
                "normalized_trace": True,
            },
        )
        if turn_node is not None:
            root.children.extend(turn_node.children)
        root.children.extend(top_level_nodes)
        return root

    def _collapse_trace_spans(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        span_payloads: dict[str, dict[str, Any]] = {}
        for item in events:
            if item["type"] not in TRACE_NODE_EVENT_TYPES:
                continue
            payload = item.get("payload", {})
            if not isinstance(payload, dict):
                continue
            span_id = str(payload.get("span_id") or "").strip()
            if not span_id:
                continue
            current = span_payloads.setdefault(span_id, {})
            self._merge_trace_payload(current, payload)
        return span_payloads

    def _merge_trace_payload(self, current: dict[str, Any], incoming: dict[str, Any]) -> None:
        for key in (
            "trace_id",
            "turn_id",
            "span_id",
            "parent_span_id",
            "node_type",
            "name",
            "status",
            "attempt_index",
            "retry_count",
            "started_at_ms",
            "ended_at_ms",
            "duration_ms",
        ):
            value = incoming.get(key)
            if value is not None and value != "":
                current[key] = value

        for key in ("input", "output", "metrics", "tags"):
            incoming_value = incoming.get(key)
            if not isinstance(incoming_value, dict):
                continue
            merged = dict(current.get(key) or {})
            merged.update(incoming_value)
            current[key] = merged

        if incoming.get("error") is not None:
            current["error"] = incoming.get("error")

    def _build_trace_span_node(self, payload: dict[str, Any]) -> ExecutionTraceNode:
        span_id = str(payload.get("span_id") or "")
        node_type = str(payload.get("node_type") or "step")
        status = self._normalize_status(str(payload.get("status") or "running"))
        metadata = {
            "trace_id": payload.get("trace_id"),
            "span_id": span_id,
            "parent_span_id": payload.get("parent_span_id"),
            "node_type": node_type,
            "attempt_index": self._safe_int(payload.get("attempt_index"), default=1),
            "retry_count": self._safe_int(payload.get("retry_count"), default=0),
            "duration_ms": self._safe_int(payload.get("duration_ms"), default=0),
            "input": dict(payload.get("input") or {}) if isinstance(payload.get("input"), dict) else {},
            "output": dict(payload.get("output") or {}) if isinstance(payload.get("output"), dict) else {},
            "metrics": dict(payload.get("metrics") or {}) if isinstance(payload.get("metrics"), dict) else {},
            "tags": dict(payload.get("tags") or {}) if isinstance(payload.get("tags"), dict) else {},
        }
        return ExecutionTraceNode(
            id=span_id,
            kind=self._map_trace_kind(node_type),
            label=str(payload.get("name") or self._default_trace_label(node_type)),
            status=status,
            started_at=self._ms_to_seconds(payload.get("started_at_ms")),
            ended_at=self._ms_to_seconds(payload.get("ended_at_ms")),
            result_preview=self._trace_span_result_preview(payload),
            error=self._trace_span_error(payload),
            metadata=metadata,
        )

    def _map_trace_kind(self, node_type: str) -> str:
        mapping = {
            "intent_resolution": "intent",
            "llm_call": "llm",
            "tool_call": "tool",
            "worker_dispatch": "dispatch",
            "response_emit": "response",
        }
        return mapping.get(node_type, node_type or "step")

    def _default_trace_label(self, node_type: str) -> str:
        return str(node_type or "step").replace("_", " ").strip().title() or "Step"

    def _trace_span_result_preview(self, payload: dict[str, Any]) -> str:
        output = payload.get("output")
        if isinstance(output, dict):
            preview = self._compact_value(output.get("response_preview"))
            if preview:
                return preview
            preview = self._compact_value(output.get("result_preview"))
            if preview:
                return preview
            preview = self._compact_value(output.get("intent"))
            if preview:
                return preview
            preview = self._compact_value(output.get("result"))
            if preview:
                return preview
        return ""

    def _trace_span_error(self, payload: dict[str, Any]) -> Optional[str]:
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("failure_reason") or "").strip() or None
        return str(error or "").strip() or None

    def _resolve_normalized_mode(
        self,
        *,
        root: ExecutionTraceNode,
        orchestration_id: Optional[str],
        orchestration_state: Optional[dict[str, Any]],
    ) -> str:
        if orchestration_id or orchestration_state:
            return "orchestration"
        for node in self._walk_nodes(root):
            if node.kind in {"worker", "dispatch"}:
                return "orchestration"
            tags = node.metadata.get("tags") if isinstance(node.metadata, dict) else {}
            if isinstance(tags, dict) and str(tags.get("orchestration_id") or "").strip():
                return "orchestration"
        return "function_calling"

    def _resolve_turn_trace_status(self, events: list[dict[str, Any]], *, default: str) -> str:
        for item in reversed(events):
            if item["type"] not in TURN_TRACE_EVENT_TYPES:
                continue
            payload = item.get("payload", {})
            status = self._normalize_status(str(payload.get("status") or default))
            if status:
                return status
        return default

    def _has_normalized_trace_events(self, events: list[dict[str, Any]]) -> bool:
        return any(item["type"] in TRACE_NODE_EVENT_TYPES for item in events)

    def _ms_to_seconds(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return max(0.0, float(value) / 1000.0)
        except (TypeError, ValueError):
            return None

    def _tool_event_status(self, payload: dict[str, Any]) -> str:
        if "success" in payload:
            return "completed" if bool(payload.get("success")) else "failed"
        result = str(payload.get("result") or "").strip().lower()
        return "completed" if result == "success" else "failed" if result == "failed" else "running"

    def _tool_event_result_preview(self, payload: dict[str, Any]) -> str:
        if "data" in payload:
            return self._compact_value(payload.get("data"))
        result = str(payload.get("result") or "").strip()
        if result:
            return result
        return self._compact_value(payload.get("tool_params"))

    def _tool_event_arguments(self, payload: dict[str, Any]) -> dict[str, Any]:
        if isinstance(payload.get("arguments"), dict):
            return payload["arguments"]
        if isinstance(payload.get("tool_params"), dict):
            return payload["tool_params"]
        return {}

    def _build_worker_tool_node(
        self,
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

    def _resolve_snapshot_status(
        self,
        *,
        root: ExecutionTraceNode,
        response_event: Optional[dict[str, Any]],
        orchestration_state: Optional[dict[str, Any]],
    ) -> str:
        if response_event is not None:
            return "completed"
        derived = self._derive_parent_status(root.children) if root.children else "running"
        if isinstance(orchestration_state, dict):
            normalized = self._normalize_status(str(orchestration_state.get("status") or "running"))
            if normalized == "failed":
                return normalized
        if derived == "failed":
            return "failed"
        return "running"

    def _derive_parent_status(self, children: list[ExecutionTraceNode]) -> str:
        if not children:
            return "running"
        statuses = {child.status for child in children}
        if "running" in statuses or "pending" in statuses:
            return "running"
        if "completed" in statuses:
            return "completed"
        if "failed" in statuses:
            return "failed"
        return "completed"

    def _derive_rollup_status(self, children: list[ExecutionTraceNode]) -> str:
        if not children:
            return "running"
        statuses = {child.status for child in children}
        if "running" in statuses or "pending" in statuses:
            return "running"
        if "completed" in statuses:
            return "completed"
        if "failed" in statuses:
            return "failed"
        return "completed"

    def _count_steps(self, root: ExecutionTraceNode) -> tuple[int, int, int]:
        active = 0
        completed = 0
        failed = 0
        for node in self._walk_nodes(root):
            if node.kind == "planning":
                if node.status in {"running", "pending"}:
                    active += 1
                continue
            if node.kind in {"root", "parallel_group", "iteration"}:
                continue
            if node.status in {"running", "pending"}:
                active += 1
            elif node.status == "failed":
                failed += 1
            else:
                completed += 1
        return active, completed, failed

    def _build_headline(
        self,
        *,
        mode: str,
        status: str,
        active_steps: int,
        completed_steps: int,
        orchestration_state: Optional[dict[str, Any]],
    ) -> str:
        if status == "completed":
            return "Tool chain completed"
        if status == "failed":
            return "Tool chain failed"
        if mode == "orchestration" and completed_steps == 0:
            subtasks = orchestration_state.get("subtasks") if isinstance(orchestration_state, dict) else None
            if active_steps <= 1 and not subtasks:
                return "Orchestrating tasks"
        if active_steps > 0 or completed_steps > 0:
            return "Running tool chain"
        return "Thinking"

    def _extract_orchestration_id(self, events: list[dict[str, Any]]) -> Optional[str]:
        for item in events:
            payload = item.get("payload", {})
            orchestration_id = str(payload.get("orchestration_id") or "").strip()
            if orchestration_id:
                return orchestration_id
        return None

    def _load_turn_events(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> list[dict[str, Any]]:
        if not self._l1_db_path.exists():
            return []
        fact_items = self._query_table_events(
            table=FACT_EVENTS_TABLE,
            event_types=FACT_DISPLAY_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        trace_items = self._query_table_events(
            table=RUNTIME_OBSERVATIONS_TABLE,
            event_types=TRACE_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        return sorted(fact_items + trace_items, key=lambda item: float(item.get("timestamp", 0.0)))

    def _load_session_events(self, *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        if not self._l1_db_path.exists():
            return []
        fact_items = self._query_table_events(
            table=FACT_EVENTS_TABLE,
            event_types=FACT_DISPLAY_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=None,
        )
        trace_items = self._query_table_events(
            table=RUNTIME_OBSERVATIONS_TABLE,
            event_types=TRACE_EVENT_TYPES,
            user_id=user_id,
            session_id=session_id,
            turn_id=None,
        )
        return sorted(fact_items + trace_items, key=lambda item: float(item.get("timestamp", 0.0)))

    def _query_table_events(
        self,
        *,
        table: str,
        event_types: tuple[str, ...],
        user_id: str,
        session_id: str,
        turn_id: str | None,
    ) -> list[dict[str, Any]]:
        if not event_types:
            return []
        type_placeholders = ", ".join("?" for _ in event_types)
        query = f"""
            SELECT event_type, structured_payload, timestamp
            FROM {table}
            WHERE deleted_at IS NULL
              AND event_type IN ({type_placeholders})
              AND user_id = ?
              AND session_id = ?
        """
        params: list[Any] = [*event_types, user_id, session_id]
        if turn_id is not None:
            query += " AND json_extract(structured_payload, '$.turn_id') = ?"
            params.append(turn_id)
        query += " ORDER BY timestamp ASC"
        try:
            conn = sqlite3.connect(str(self._l1_db_path))
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to query trace events table=%s: %s", table, exc)
            return []

        items: list[dict[str, Any]] = []
        for event_type, raw_data, timestamp in rows:
            try:
                payload = json.loads(raw_data or "{}")
            except Exception:
                payload = {}
            items.append(
                {
                    "type": str(event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "timestamp": float(timestamp or 0.0),
                }
            )
        return items

    def _load_orchestration_state(self, orchestration_id: Optional[str]) -> Optional[dict[str, Any]]:
        normalized = str(orchestration_id or "").strip()
        if not normalized or not self._orchestrations_path.exists():
            return None
        try:
            payload = json.loads(self._orchestrations_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load orchestration store for trace read: %s", exc)
            return None
        orchestrations = payload.get("orchestrations", {}) if isinstance(payload, dict) else {}
        raw_state = orchestrations.get(normalized)
        return raw_state if isinstance(raw_state, dict) else None

    def _status_from_worker_event(self, event_type: str, payload: dict[str, Any]) -> str:
        if event_type == "WORKER_AGENT_COMPLETED":
            return "completed"
        if event_type == "WORKER_AGENT_FAILED":
            return "failed"
        stage = str(payload.get("stage") or "")
        if stage == "tool_result":
            return "completed" if bool(payload.get("success")) else "failed"
        return "running"

    def _normalize_status(self, status: str) -> str:
        lowered = str(status or "running").strip().lower()
        if lowered in {"completed", "success"}:
            return "completed"
        if lowered in {"failed", "error"}:
            return "failed"
        if lowered in {"pending"}:
            return "pending"
        return "running"

    def _walk_nodes(self, node: ExecutionTraceNode) -> list[ExecutionTraceNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes

    def _finalize_terminal_nodes(self, node: ExecutionTraceNode, *, status: str, ended_at: float) -> None:
        for child in node.children:
            self._finalize_terminal_nodes(child, status=status, ended_at=ended_at)
        if node.kind != "root" and node.status in {"running", "pending"}:
            node.status = "completed" if status == "completed" else "failed"
            node.metadata = {**node.metadata, "inferred_terminal": True}
        if node.status in {"completed", "failed"} and node.ended_at is None:
            node.ended_at = ended_at

    def _compact_value(self, value: Any) -> str:
        if isinstance(value, dict):
            summary = str(value.get("summary") or value.get("result_preview") or "").strip()
            if summary:
                return summary[:240]
            content_preview = str(value.get("content_preview") or value.get("stdout_preview") or "").strip()
            if content_preview:
                return content_preview[:240]
        if isinstance(value, list):
            return f"{len(value)} items"
        text = str(value or "").strip()
        return text[:240]

    def _safe_int(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


_chat_trace_read_service: Optional[ChatTraceReadService] = None


def get_chat_trace_read_service() -> ChatTraceReadService:
    """Get the shared ChatTraceReadService instance."""
    global _chat_trace_read_service
    if _chat_trace_read_service is None:
        _chat_trace_read_service = ChatTraceReadService()
    return _chat_trace_read_service
