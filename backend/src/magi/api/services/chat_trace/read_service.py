"""Read-side aggregation service for per-turn execution traces."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from ....core.logger import get_logger
from ....core.sqlite import connect_sqlite
from ....utils.runtime import get_runtime_paths
from .models import (
    ExecutionPlanStepSummary,
    ExecutionPlanSummary,
    ExecutionTraceNode,
    ExecutionTraceSnapshot,
    ExecutionTraceSummary,
)
from .runtime_rows import TraceRuntimeRowsMixin
from .builders.legacy import (
    build_function_root,
    build_orchestration_root,
    build_worker_tool_node,
)
from .builders.normalized import (
    build_normalized_trace_root,
    build_trace_span_node,
    collapse_trace_spans,
    merge_trace_payload,
)
from .builders.rows import (
    build_trace_row_node,
    resolve_result_preview,
)
from .tree import (
    build_runtime_trace_root,
    deduplicate_response_emit,
    reshape_orchestration_trace_root,
    with_dispatch_label,
)
from .utils import (
    compact_value,
    default_trace_label,
    derive_children_status,
    is_terminal_status,
    map_trace_kind,
    ms_to_seconds,
    normalize_status,
    optional_text,
    parse_json_object,
    parse_json_value,
    safe_int,
    status_from_worker_event,
    tool_event_arguments,
    tool_event_result_preview,
    tool_event_status,
    trace_span_error,
    trace_span_result_preview,
)

logger = get_logger(__name__)

FACT_EVENTS_TABLE = "fact_events"
RUNTIME_OBSERVATIONS_TABLE = FACT_EVENTS_TABLE
USER_EVENT_TYPES = ("UserMessage",)
AI_RESPONSE_EVENT_TYPES = ("AIResponse",)
FACT_DISPLAY_EVENT_TYPES = USER_EVENT_TYPES + AI_RESPONSE_EVENT_TYPES
WORKER_EVENT_TYPES = ("WORKER_AGENT_PROGRESS", "WORKER_AGENT_COMPLETED", "WORKER_AGENT_FAILED")
LEGACY_TRACE_EVENT_TYPES = ("TOOL_INTERACTION", "TOOL_INVOKED", "CHAT_TOOL_LOOP_STEP")
TURN_TRACE_EVENT_TYPES = ("TURN_TRACE_STARTED", "TURN_TRACE_COMPLETED", "TURN_TRACE_FAILED")
TRACE_NODE_EVENT_TYPES = ("TRACE_NODE_STARTED", "TRACE_NODE_COMPLETED", "TRACE_NODE_FAILED")
TRACE_EVENT_TYPES = WORKER_EVENT_TYPES + LEGACY_TRACE_EVENT_TYPES + TURN_TRACE_EVENT_TYPES + TRACE_NODE_EVENT_TYPES
MAX_PLAN_PREVIEW_STEPS = 3


class ChatTraceReadService(TraceRuntimeRowsMixin):
    """Build per-turn execution snapshots from persisted events and orchestration state."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path
        self._orchestrations_path: Path = runtime_paths.task_orchestrations_path

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
        turn = self._load_trace_turn(user_id=user_id, session_id=session_id, turn_id=normalized_turn_id)
        if turn is None:
            return None
        orchestration_id = str(turn.get("orchestration_id") or "").strip() or None
        orchestration_state = self._load_orchestration_state(orchestration_id) if orchestration_id else None
        spans = self._load_trace_spans(trace_id=str(turn.get("trace_id") or ""))
        llm_calls = self._load_detail_rows(table="trace_llm_calls", trace_id=str(turn.get("trace_id") or ""))
        tool_calls = self._load_detail_rows(table="trace_tools", trace_id=str(turn.get("trace_id") or ""))
        intent_resolutions = self._load_detail_rows(table="trace_intent_resolutions", trace_id=str(turn.get("trace_id") or ""))
        snapshot = self._build_snapshot_from_trace_rows(
            user_id=user_id,
            session_id=session_id,
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            intent_resolutions=intent_resolutions,
            orchestration_state=orchestration_state,
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

    async def aget_trace_snapshot(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        """Build a trace snapshot without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_trace_snapshot,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def aget_trace_summary(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> Optional[dict[str, Any]]:
        """Build a trace summary without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_trace_summary,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
        )

    async def aget_turn_activity_map(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Build turn activity without blocking the event loop."""
        return await asyncio.to_thread(
            self.get_turn_activity_map,
            user_id=user_id,
            session_id=session_id,
        )

    def get_turn_activity_map(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, dict[str, Any]]:
        activity: dict[str, dict[str, Any]] = {}
        for turn in self._load_session_turns(user_id=user_id, session_id=session_id):
            turn_id = str(turn.get("turn_id") or "").strip()
            summary = self.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
            if summary is not None:
                activity[turn_id] = summary
        return activity

    def _build_snapshot_from_trace_rows(
        self,
        *,
        user_id: str,
        session_id: str,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        intent_resolutions: list[dict[str, Any]],
        orchestration_state: Optional[dict[str, Any]],
    ) -> Optional[ExecutionTraceSnapshot]:
        turn_id = str(turn.get("turn_id") or "").strip()
        if not turn_id:
            return None
        root = self._build_runtime_trace_root(
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            intent_resolutions=intent_resolutions,
        )
        orchestration_id = str(turn.get("orchestration_id") or "").strip() or None
        mode = str(turn.get("mode") or self._resolve_normalized_mode(
            root=root,
            orchestration_id=orchestration_id,
            orchestration_state=orchestration_state,
        ))
        if mode == "orchestration":
            root = self._reshape_orchestration_trace_root(root)
        started_at = self._ms_to_seconds(turn.get("started_at_ms"))
        ended_at = self._ms_to_seconds(turn.get("ended_at_ms"))
        status = self._normalize_status(str(turn.get("status") or "running"))
        root.status = status
        root.started_at = root.started_at if root.started_at is not None else started_at
        root.ended_at = ended_at if self._is_terminal_status(status) else None
        active_steps, completed_steps, failed_steps = self._count_steps(root)
        total_input_tokens = sum(self._safe_int(lc.get("input_tokens"), default=0) for lc in llm_calls)
        total_output_tokens = sum(self._safe_int(lc.get("output_tokens"), default=0) for lc in llm_calls)
        total_reasoning_tokens = sum(self._safe_int(lc.get("reasoning_tokens"), default=0) for lc in llm_calls)
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
            duration_seconds=round(
                max(0.0, (ended_at or started_at or 0.0) - (started_at or 0.0)),
                3,
            ),
            trace_available=bool(root.children),
            orchestration_id=str(turn.get("orchestration_id") or "").strip() or None,
            plan_summary=self._build_plan_summary(orchestration_state),
            continued_from_turn_id=self._optional_text(turn.get("continued_from_turn_id")),
            continued_from_trace_id=self._optional_text(turn.get("continued_from_trace_id")),
            superseded_by_turn_id=self._optional_text(turn.get("superseded_by_turn_id")),
            supersession_reason=self._optional_text(turn.get("supersession_reason")),
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_reasoning_tokens=total_reasoning_tokens,
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
            continued_from_turn_id=self._optional_text(turn.get("continued_from_turn_id")),
            continued_from_trace_id=self._optional_text(turn.get("continued_from_trace_id")),
            superseded_by_turn_id=self._optional_text(turn.get("superseded_by_turn_id")),
            supersession_reason=self._optional_text(turn.get("supersession_reason")),
            summary=summary,
            root=root,
        )

    def _build_runtime_trace_root(
        self,
        *,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        intent_resolutions: list[dict[str, Any]],
    ) -> ExecutionTraceNode:
        return build_runtime_trace_root(
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
            intent_resolutions=intent_resolutions,
        )

    def _reshape_orchestration_trace_root(self, root: ExecutionTraceNode) -> ExecutionTraceNode:
        return reshape_orchestration_trace_root(root)

    def _with_dispatch_label(self, node: ExecutionTraceNode) -> ExecutionTraceNode:
        return with_dispatch_label(node)

    @staticmethod
    def _deduplicate_response_emit(root: ExecutionTraceNode) -> None:
        """Remove the response_emit node when its content duplicates the last iteration."""
        deduplicate_response_emit(root)

    def _build_trace_row_node(
        self,
        *,
        span: dict[str, Any],
        llm_call: dict[str, Any] | None,
        tool_call: dict[str, Any] | None,
        intent_resolution: dict[str, Any] | None = None,
    ) -> ExecutionTraceNode:
        return build_trace_row_node(
            span=span,
            llm_call=llm_call,
            tool_call=tool_call,
            intent_resolution=intent_resolution,
        )

    @staticmethod
    def _resolve_result_preview(
        *,
        span: dict[str, Any],
        llm_call: dict[str, Any] | None,
        tool_call: dict[str, Any] | None,
    ) -> str:
        return resolve_result_preview(span=span, llm_call=llm_call, tool_call=tool_call)

    @staticmethod
    def _parse_json_object(raw_value: Any) -> dict[str, Any]:
        return parse_json_object(raw_value)

    @staticmethod
    def _parse_json_value(raw_value: Any) -> Any:
        return parse_json_value(raw_value)

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
        if self._is_terminal_status(status):
            self._finalize_terminal_nodes(root, status=status, ended_at=ended_at)
        root.status = status
        root.ended_at = ended_at if self._is_terminal_status(status) else None

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
            plan_summary=self._build_plan_summary(orchestration_state),
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
        return build_orchestration_root(
            turn_id=turn_id,
            events=events,
            orchestration_id=orchestration_id,
            orchestration_state=orchestration_state,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _build_function_root(
        self,
        *,
        turn_id: str,
        events: list[dict[str, Any]],
        started_at: float,
        ended_at: float,
    ) -> Optional[ExecutionTraceNode]:
        return build_function_root(
            turn_id=turn_id,
            events=events,
            started_at=started_at,
            ended_at=ended_at,
        )

    def _build_normalized_trace_root(
        self,
        *,
        turn_id: str,
        events: list[dict[str, Any]],
        started_at: float,
        ended_at: float,
    ) -> Optional[ExecutionTraceNode]:
        return build_normalized_trace_root(
            turn_id=turn_id,
            events=events,
            started_at=started_at,
            ended_at=ended_at,
            trace_node_event_types=TRACE_NODE_EVENT_TYPES,
        )

    def _collapse_trace_spans(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return collapse_trace_spans(events, trace_node_event_types=TRACE_NODE_EVENT_TYPES)

    def _merge_trace_payload(self, current: dict[str, Any], incoming: dict[str, Any]) -> None:
        merge_trace_payload(current, incoming)

    def _build_trace_span_node(self, payload: dict[str, Any]) -> ExecutionTraceNode:
        return build_trace_span_node(payload)

    def _map_trace_kind(self, node_type: str) -> str:
        return map_trace_kind(node_type)

    def _default_trace_label(self, node_type: str) -> str:
        return default_trace_label(node_type)

    def _trace_span_result_preview(self, payload: dict[str, Any]) -> str:
        return trace_span_result_preview(payload)

    def _trace_span_error(self, payload: dict[str, Any]) -> Optional[str]:
        return trace_span_error(payload)

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
        return ms_to_seconds(value)

    def _tool_event_status(self, payload: dict[str, Any]) -> str:
        return tool_event_status(payload)

    def _tool_event_result_preview(self, payload: dict[str, Any]) -> str:
        return tool_event_result_preview(payload)

    def _tool_event_arguments(self, payload: dict[str, Any]) -> dict[str, Any]:
        return tool_event_arguments(payload)

    def _build_worker_tool_node(
        self,
        item: dict[str, Any],
        *,
        index: int,
        turn_id: str,
    ) -> ExecutionTraceNode:
        return build_worker_tool_node(item, index=index, turn_id=turn_id)

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
        return derive_children_status(children)

    def _derive_rollup_status(self, children: list[ExecutionTraceNode]) -> str:
        return derive_children_status(children)

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

    def _build_plan_summary(self, orchestration_state: Optional[dict[str, Any]]) -> Optional[ExecutionPlanSummary]:
        if not isinstance(orchestration_state, dict):
            return None
        raw_subtasks = orchestration_state.get("subtasks")
        if not isinstance(raw_subtasks, list):
            return None

        steps: list[ExecutionPlanStepSummary] = []
        for raw_subtask in raw_subtasks:
            if not isinstance(raw_subtask, dict):
                continue
            label = (
                self._optional_text(raw_subtask.get("description"))
                or self._optional_text(raw_subtask.get("title"))
                or self._optional_text(raw_subtask.get("subtask_id"))
            )
            if label is None:
                continue
            steps.append(
                ExecutionPlanStepSummary(
                    subtask_id=self._optional_text(raw_subtask.get("subtask_id")),
                    label=label,
                    status=self._normalize_status(str(raw_subtask.get("status") or "pending")),
                )
            )

        if not steps:
            return None

        preview_steps = steps[:MAX_PLAN_PREVIEW_STEPS]
        return ExecutionPlanSummary(
            planner=self._optional_text(orchestration_state.get("planner")),
            parallel_mode="parallel" if bool(orchestration_state.get("allow_parallel", True)) else "sequential",
            total_steps=len(steps),
            remaining_steps=max(0, len(steps) - len(preview_steps)),
            steps=preview_steps,
        )

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
            SELECT event_type, content, timestamp, turn_id
            FROM {table}
            WHERE deleted_at IS NULL
              AND event_type IN ({type_placeholders})
              AND user_id = ?
              AND session_id = ?
        """
        params: list[Any] = [*event_types, user_id, session_id]
        if turn_id is not None:
            query += " AND turn_id = ?"
            params.append(turn_id)
        query += " ORDER BY timestamp ASC"
        try:
            conn = connect_sqlite(self._l1_db_path, profile="hot_write", use_row_factory=False)
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("Failed to query trace events table=%s: %s", table, exc)
            return []

        items: list[dict[str, Any]] = []
        for event_type, raw_content, timestamp, raw_turn_id in rows:
            payload = self._build_event_payload(
                event_type=str(event_type),
                raw_content=raw_content,
                turn_id=raw_turn_id,
            )
            items.append(
                {
                    "type": str(event_type),
                    "payload": payload if isinstance(payload, dict) else {},
                    "timestamp": float(timestamp or 0.0),
                }
            )
        return items

    def _build_event_payload(
        self,
        *,
        event_type: str,
        raw_content: object,
        turn_id: object,
    ) -> dict[str, Any]:
        text = str(raw_content or "").strip()
        normalized_turn_id = str(turn_id or "").strip() or None
        if event_type in FACT_DISPLAY_EVENT_TYPES:
            payload: dict[str, Any] = {"content": text}
            if normalized_turn_id:
                payload["turn_id"] = normalized_turn_id
            return payload
        if not text:
            return {"turn_id": normalized_turn_id} if normalized_turn_id else {}
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"content": text}
        if not isinstance(payload, dict):
            payload = {"content": text}
        if normalized_turn_id and not payload.get("turn_id"):
            payload["turn_id"] = normalized_turn_id
        return payload

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
        return status_from_worker_event(event_type, payload)

    def _normalize_status(self, status: str) -> str:
        return normalize_status(status)

    def _walk_nodes(self, node: ExecutionTraceNode) -> list[ExecutionTraceNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk_nodes(child))
        return nodes

    def _finalize_terminal_nodes(self, node: ExecutionTraceNode, *, status: str, ended_at: float) -> None:
        for child in node.children:
            self._finalize_terminal_nodes(child, status=status, ended_at=ended_at)
        if node.kind != "root" and node.status in {"running", "pending"}:
            if status in {"completed", "failed"}:
                node.status = "completed" if status == "completed" else "failed"
            else:
                node.status = status
            node.metadata = {**node.metadata, "inferred_terminal": True}
        if self._is_terminal_status(node.status) and node.ended_at is None:
            node.ended_at = ended_at

    @staticmethod
    def _is_terminal_status(status: str) -> bool:
        return is_terminal_status(status)

    @staticmethod
    def _optional_text(value: Any) -> Optional[str]:
        return optional_text(value)

    def _compact_value(self, value: Any) -> str:
        return compact_value(value)

    def _safe_int(self, value: Any, *, default: int) -> int:
        return safe_int(value, default=default)


def get_chat_trace_read_service() -> ChatTraceReadService:
    """Get the shared ChatTraceReadService instance."""
    from .provider import (
        get_chat_trace_read_service as _get_chat_trace_read_service,
    )

    return _get_chat_trace_read_service()
