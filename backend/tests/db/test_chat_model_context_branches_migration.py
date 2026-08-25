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


def test_v17_downgrade_restores_empty_v16_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    config = _chat_config(db_path)
    command.upgrade(config, CHAT_MIGRATION_HEAD)

    command.downgrade(config, "v16")

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(chat_model_context_heads)")
        }
        assert "accepted_revision" not in columns
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "v16",
        )
