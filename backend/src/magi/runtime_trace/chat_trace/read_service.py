"""Read-side aggregation service for per-turn execution traces."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Optional

from ...core.logger import get_logger
from ...utils.runtime import get_runtime_paths
from .models import (
    ExecutionTraceNode,
)
from .runtime_rows import TraceRuntimeRowsMixin
from .run_event_projection import project_run_events
from .snapshot_builder import TraceSnapshotBuilderMixin
from .tree import build_runtime_trace_root
from .utils import (
    compact_value,
    is_terminal_status,
    ms_to_seconds,
    normalize_status,
    optional_text,
    safe_int,
)

logger = get_logger(__name__)


class ChatTraceReadService(TraceSnapshotBuilderMixin, TraceRuntimeRowsMixin):
    """Build per-turn execution snapshots from persisted runtime events."""

    def __init__(self) -> None:
        runtime_paths = get_runtime_paths()
        self._l1_db_path: Path = runtime_paths.l1_memory_db_path
        self._runtime_trace_db_path: Path = runtime_paths.runtime_trace_db_path

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
        run_events, run_plan = self._load_latest_run_state(
            user_id=user_id,
            session_id=session_id,
            turn_id=normalized_turn_id,
        )
        if run_events:
            projection = project_run_events(
                run_events,
                user_id=user_id,
                session_id=session_id,
                turn_id=normalized_turn_id,
                run_plan=run_plan,
            )
            if projection is not None:
                return projection.to_dict()
        turn = self._load_trace_turn(user_id=user_id, session_id=session_id, turn_id=normalized_turn_id)
        if turn is None:
            return None
        spans = self._load_trace_spans(trace_id=str(turn.get("trace_id") or ""))
        llm_calls = self._load_detail_rows(table="trace_llm_calls", trace_id=str(turn.get("trace_id") or ""))
        tool_calls = self._load_detail_rows(table="trace_tools", trace_id=str(turn.get("trace_id") or ""))
        snapshot = self._build_snapshot_from_trace_rows(
            user_id=user_id,
            session_id=session_id,
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
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
        for turn_id in self._load_session_run_turn_ids(
            user_id=user_id,
            session_id=session_id,
        ):
            summary = self.get_trace_summary(
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
            )
            if summary is not None:
                activity[turn_id] = summary
        for turn in self._load_session_turns(user_id=user_id, session_id=session_id):
            turn_id = str(turn.get("turn_id") or "").strip()
            if turn_id in activity:
                continue
            summary = self.get_trace_summary(user_id=user_id, session_id=session_id, turn_id=turn_id)
            if summary is not None:
                activity[turn_id] = summary
        return activity

    def _load_latest_run_state(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        try:
            with sqlite3.connect(self._runtime_trace_db_path) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN")
                manifest = connection.execute(
                    """
                    SELECT run_id
                    FROM agent_run_manifests
                    WHERE turn_id = ? AND session_id = ? AND user_id = ?
                    ORDER BY created_at_ms DESC
                    LIMIT 1
                    """,
                    (turn_id, session_id, user_id),
                ).fetchone()
                if manifest is None:
                    return [], None
                run_id = str(manifest["run_id"])
                rows = connection.execute(
                    """
                    SELECT event_id, run_id, sequence, turn_id, session_id,
                           user_id, event_type, step_index, payload_json,
                           created_at_ms
                    FROM agent_run_events
                    WHERE run_id = ?
                    ORDER BY sequence ASC
                    """,
                    (run_id,),
                ).fetchall()
                plan_row = connection.execute(
                    "SELECT plan_json FROM run_plans WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
        except sqlite3.Error:
            return [], None
        events = [
            {
                "event_id": str(row["event_id"]),
                "run_id": str(row["run_id"]),
                "sequence": int(row["sequence"]),
                "turn_id": row["turn_id"],
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "event_type": str(row["event_type"]),
                "step_index": row["step_index"],
                "payload": json.loads(str(row["payload_json"] or "{}")),
                "created_at_ms": int(row["created_at_ms"]),
            }
            for row in rows
        ]
        plan = (
            json.loads(str(plan_row["plan_json"]))
            if plan_row is not None
            else None
        )
        return events, dict(plan) if isinstance(plan, dict) else None

    def _load_session_run_turn_ids(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> list[str]:
        try:
            with sqlite3.connect(self._runtime_trace_db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT turn_id
                    FROM agent_run_manifests
                    WHERE session_id = ? AND user_id = ? AND turn_id IS NOT NULL
                    GROUP BY turn_id
                    ORDER BY MAX(created_at_ms) ASC
                    """,
                    (session_id, user_id),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [str(row[0]) for row in rows if str(row[0] or "").strip()]

    def _build_runtime_trace_root(
        self,
        *,
        turn: dict[str, Any],
        spans: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
    ) -> ExecutionTraceNode:
        return build_runtime_trace_root(
            turn=turn,
            spans=spans,
            llm_calls=llm_calls,
            tool_calls=tool_calls,
        )

    def _ms_to_seconds(self, value: Any) -> Optional[float]:
        return ms_to_seconds(value)

    def _normalize_status(self, status: str) -> str:
        return normalize_status(status)

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
