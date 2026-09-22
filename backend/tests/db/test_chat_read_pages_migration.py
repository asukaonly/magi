"""Read revisions invalidate cached pages for every persisted read-model mutation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config
from magi.chat.read.pagination import read_revision


def test_v18_preserves_rows_and_adds_revision_triggers(tmp_path: Path) -> None:
    path = tmp_path / "chat.db"
    target = next(target for target in MIGRATION_TARGETS if target.name == "chat")
    config = _build_config(target, path)
    command.upgrade(config, "v17")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES ('chat','user','Original',1,1)"
        )
    command.upgrade(config, "v18")
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT title FROM chat_sessions").fetchone()[0] == "Original"
        revision = read_revision(conn, "user", "chat")
        listing = read_revision(conn, "user", "")
        conn.execute("UPDATE chat_sessions SET title='Renamed'")
        assert read_revision(conn, "user", "chat") != revision
        assert read_revision(conn, "user", "") != listing
        conn.execute(
            """INSERT INTO chat_messages(message_id,session_id,user_id,role,message_kind,content_text,created_at_ms,sequence_no)
                        VALUES ('message','chat','user','user','user_text','Hello',1,1)"""
        )
        revision = read_revision(conn, "user", "chat")
        conn.execute("UPDATE chat_messages SET label_json='{}'")
        assert read_revision(conn, "user", "chat") != revision
        revision = read_revision(conn, "user", "chat")
        conn.execute("DELETE FROM chat_messages")
        assert read_revision(conn, "user", "chat") != revision
        conn.execute(
            "INSERT INTO chat_turns(turn_id,session_id,user_id,status,response_mode,created_at_ms,updated_at_ms) VALUES ('turn','chat','user','running','final_only',1,1)"
        )
        revision = read_revision(conn, "user", "chat")
        conn.execute("UPDATE chat_turns SET status='completed'")
        assert read_revision(conn, "user", "chat") != revision
        revision = read_revision(conn, "user", "chat")
        conn.execute(
            """INSERT INTO chat_context_usage_snapshots(turn_id,session_id,user_id,used_tokens,context_window,input_capacity,compaction_threshold,measurement,updated_at_ms)
                        VALUES ('turn','chat','user',1,10,10,9,'actual',1)"""
        )
        assert read_revision(conn, "user", "chat") != revision
        revision = read_revision(conn, "user", "chat")
        listing = read_revision(conn, "user", "")
        conn.execute("DELETE FROM chat_sessions")
        assert read_revision(conn, "user", "chat") != revision
        assert read_revision(conn, "user", "") != listing
    command.downgrade(config, "v17")
    with sqlite3.connect(path) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='chat_read_revisions'"
            ).fetchone()
            is None
        )
        conn.execute(
            "INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES ('new','user','New',1,1)"
        )
