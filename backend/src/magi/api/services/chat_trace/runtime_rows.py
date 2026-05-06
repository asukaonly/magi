"""Runtime trace row loading helpers for chat trace reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol, cast

from ....core.sqlite import connect_sqlite


class _TraceRuntimeRowsHost(Protocol):
    _runtime_trace_db_path: Path


class TraceRuntimeRowsMixin:
    """Load normalized runtime trace rows from SQLite."""

    def _load_trace_turn(self, *, user_id: str, session_id: str, turn_id: str) -> Optional[dict[str, Any]]:
        rows = self._query_trace_rows(
            """
            SELECT *
            FROM trace_turns
            WHERE user_id = ? AND session_id = ? AND turn_id = ?
            LIMIT 1
            """,
            (user_id, session_id, turn_id),
        )
        return rows[0] if rows else None

    def _load_session_turns(self, *, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return self._query_trace_rows(
            """
            SELECT *
            FROM trace_turns
            WHERE user_id = ? AND session_id = ?
            ORDER BY updated_at_ms ASC
            """,
            (user_id, session_id),
        )

    def _load_trace_spans(self, *, trace_id: str) -> list[dict[str, Any]]:
        if not trace_id:
            return []
        return self._query_trace_rows(
            """
            SELECT *
            FROM trace_spans
            WHERE trace_id = ? AND node_type <> 'turn_record'
            ORDER BY started_at_ms ASC, span_id ASC
            """,
            (trace_id,),
        )

    def _load_detail_rows(self, *, table: str, trace_id: str) -> list[dict[str, Any]]:
        if not trace_id:
            return []
        return self._query_trace_rows(
            f"""
            SELECT *
            FROM {table}
            WHERE trace_id = ?
            """,
            (trace_id,),
        )

    def _query_trace_rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        host = cast(_TraceRuntimeRowsHost, self)
        if not host._runtime_trace_db_path.exists():
            return []
        conn = connect_sqlite(host._runtime_trace_db_path, profile="hot_write")
        cur = conn.cursor()
        cur.execute(query, params)
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows


__all__ = ["TraceRuntimeRowsMixin"]
