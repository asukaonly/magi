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
TRACE_EVENT_TYPES = WORKER_EVENT_TYPES + ("CHAT_TOOL_LOOP_STEP", "TOOL_INTERACTION", "TOOL_INVOKED")
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
        has_tool_events = any(item["type"] in {"CHAT_TOOL_LOOP_STEP", "TOOL_INTERACTION", "TOOL_INVOKED"} for item in events)
        mode = "orchestration" if orchestration_state or has_worker_events else "function_calling"
        started_at = float(user_event["timestamp"]) if user_event else float(events[0]["timestamp"])
        ended_at = float(response_event["timestamp"]) if response_event else float(events[-1]["timestamp"])

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

        status = self._resolve_snapshot_status(
            root=root,
            response_event=response_event,
            orchestration_state=orchestration_state,
        )
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
            duration_seconds=max(0.0, ended_at - started_at),
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
