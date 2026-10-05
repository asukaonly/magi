from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def test_v17_replaces_disposable_model_context_with_branch_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v16.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v16")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Test', 1, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO chat_model_context_heads(
                session_id, generation, revision, last_sequence_no, updated_at_ms
            ) VALUES ('session-1', 1, 0, 0, 1)
            """
        )
        conn.commit()

    command.upgrade(config, CHAT_MIGRATION_HEAD)

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(chat_model_context_heads)")
        }
        assert "accepted_revision" in columns
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "chat_model_context_revisions" in tables
        assert "chat_model_context_run_heads" in tables
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_model_context_heads"
        ).fetchone() == (0,)
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            CHAT_MIGRATION_HEAD,
        )


def test_v17_model_context_rejects_orphan_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    config = _chat_config(db_path)
    command.upgrade(config, CHAT_MIGRATION_HEAD)

    with sqlite3.connect(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO chat_model_context_heads(
                    session_id, generation, revision, accepted_revision,
                    last_sequence_no, updated_at_ms
                ) VALUES ('missing', 1, 0, 0, 0, 1)
                """
            )
        except sqlite3.IntegrityError as exc:
            assert "chat session is unavailable" in str(exc)
        else:  # pragma: no cover - trigger contract
            raise AssertionError("Orphan model context was accepted")


def test_v17_downgrade_discards_derived_branches_and_preserves_source_chat(tmp_path: Path):
    path = tmp_path / "chat.db"
    config = _chat_config(path)
    command.upgrade(config, "v17")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO chat_sessions(session_id,user_id,title,created_at_ms,updated_at_ms) VALUES ('session-1','user-1','Keep source',1,1)"
        )
        connection.execute(
            "INSERT INTO chat_messages(message_id,session_id,user_id,role,message_kind,content_text,created_at_ms,sequence_no) VALUES ('message-1','session-1','user-1','user','text','Source text must survive',1,1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_heads(session_id,generation,revision,accepted_revision,last_sequence_no,updated_at_ms) VALUES ('session-1',1,1,0,1,1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_events(event_id,session_id,generation,sequence_no,operation,item_kind,item_json,created_at_ms) VALUES ('event-1','session-1',1,1,'append','message','{}',1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_revisions(session_id,generation,revision,parent_revision,branch_kind,run_id,item_count,created_at_ms) VALUES ('session-1',1,1,0,'working','run-1',1,1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_surface_nodes(session_id,generation,revision,position,event_sequence_no) VALUES ('session-1',1,1,0,1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_run_heads(session_id,run_id,generation,base_revision,working_revision,status,updated_at_ms) VALUES ('session-1','run-1',1,0,1,'active',1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_epochs(epoch_id,session_id,generation,system_hash,system_prompt,tools_hash,tools_json,created_at_ms) VALUES ('epoch-1','session-1',1,'sys','prompt','tools','[]',1)"
        )
        connection.execute(
            "INSERT INTO chat_model_context_boundaries(boundary_id,session_id,generation,boundary_no,surface_revision,epoch_id,boundary_kind,created_at_ms) VALUES ('boundary-1','session-1',1,1,1,'epoch-1','request',1)"
        )
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("chat_sessions", "chat_messages")
        }
    command.downgrade(config, "v16")
    with sqlite3.connect(path) as connection:
        assert {
            table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in before
        } == before
        for suffix in ("heads", "events", "surface_nodes", "epochs", "boundaries"):
            assert connection.execute(f"SELECT * FROM chat_model_context_{suffix}").fetchall() == []
        for suffix in ("revisions", "run_heads"):
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (f"chat_model_context_{suffix}",),
                ).fetchone()
                is None
            )
        assert "accepted_revision" not in {
            row[1] for row in connection.execute("PRAGMA table_info(chat_model_context_heads)")
        }
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("v16",)
        connection.execute(
            "INSERT INTO chat_model_context_heads(session_id,generation,revision,last_sequence_no,updated_at_ms) VALUES ('session-1',1,0,0,2)"
        )
        assert connection.execute(
            "SELECT generation,revision,last_sequence_no FROM chat_model_context_heads WHERE session_id='session-1'"
        ).fetchone() == (1, 0, 0)
