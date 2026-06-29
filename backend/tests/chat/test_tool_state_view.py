from __future__ import annotations

import sqlite3
from pathlib import Path

from magi.chat.task_agent.tool_state_view import ChatToolStateView


def test_tool_state_view_restores_recent_state_from_runtime_trace(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime_trace.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE trace_turns (
                trace_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT,
                updated_at_ms INTEGER
            );
            CREATE TABLE trace_tools (
                trace_id TEXT NOT NULL,
                turn_id TEXT,
                tool_name TEXT,
                error_code TEXT,
                error_message TEXT,
                result_preview TEXT,
                arguments_json TEXT,
                execution_time_ms REAL,
                success INTEGER
            );
            """)
        conn.execute(
            "INSERT INTO trace_turns(trace_id, user_id, session_id, updated_at_ms) VALUES (?, ?, ?, ?)",
            ("trace-1", "user-1", "session-1", 100),
        )
        conn.execute(
            """
            INSERT INTO trace_tools(
                trace_id, turn_id, tool_name, error_code, error_message,
                result_preview, arguments_json, execution_time_ms, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "trace-1",
                "turn-1",
                "photo_resolver",
                "",
                "",
                "Resolved one photo",
                '{"asset_ref_id":"asset-1"}',
                42.4,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    view = ChatToolStateView(runtime_trace_db_path=db_path)
    view.restore_from_trace(
        require_session_id=lambda _user_id, raw_session_id: str(raw_session_id or "default"),
        build_history_key=lambda user_id, session_id: f"{user_id}::{session_id}",
    )

    state = view.recent_state("user-1::session-1")

    assert state == [
        {
            "tool_name": "photo_resolver",
            "status": "success",
            "turn_id": "turn-1",
            "execution_time_ms": 42,
            "outcome": "Resolved one photo",
            "handles": ["asset_ref_id:asset-1"],
        }
    ]
