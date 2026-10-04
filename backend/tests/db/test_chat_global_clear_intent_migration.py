"""Migration coverage for interrupted global chat-clear recovery."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def _drop_post_v5_schema(connection: sqlite3.Connection) -> None:
    for trigger_name in (
        "trg_chat_sessions_reject_cleared_session",
        "trg_chat_turns_reject_unavailable_session",
        "trg_chat_messages_reject_unavailable_session",
        "trg_chat_attachments_reject_unavailable_session",
        "trg_chat_context_summaries_reject_unavailable_session",
        "trg_chat_run_consumed_events_reject_unavailable_session",
        "trg_chat_assistant_memory_outbox_reject_unavailable_session",
    ):
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    connection.execute("DROP INDEX IF EXISTS uq_chat_sessions_session_id_nocase")
    connection.execute("DROP TABLE IF EXISTS chat_cleared_session_scopes")
    connection.execute("DROP TABLE IF EXISTS chat_global_clear_intent")


@pytest.mark.parametrize("initial_revision", ["v5", "head"], ids=["legacy-upgrade", "fresh"])
def test_global_clear_intent_enforces_state_contract_without_changing_chat_data(
    tmp_path: Path, initial_revision: str,
) -> None:
    db_path = tmp_path / "chat-v5.db"
    config = _chat_config(db_path)
    command.upgrade(config, initial_revision)
    with sqlite3.connect(db_path) as connection:
        if initial_revision == "v5":
            _drop_post_v5_schema(connection)
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Existing chat', 1, 2)
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        assert connection.execute(
            "SELECT title FROM chat_sessions WHERE session_id = 'session-1'"
        ).fetchone() == ("Existing chat",)
        connection.execute(
            """
            INSERT INTO chat_global_clear_intent(
                intent_key, requested_at_ms, session_count
            ) VALUES ('global', 123, 4)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO chat_global_clear_intent(
                    intent_key, requested_at_ms, session_count
                ) VALUES ('other', 456, 0)
                """
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                UPDATE chat_global_clear_intent
                SET session_count = -1 WHERE intent_key = 'global'
                """
            )
        assert connection.execute(
            "SELECT intent_key, requested_at_ms, session_count FROM chat_global_clear_intent"
        ).fetchall() == [("global", 123, 4)]
