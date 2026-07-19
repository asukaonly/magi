"""Migration coverage for durable chat message clear barriers."""

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


def _barrier_contract(connection: sqlite3.Connection) -> tuple[object, ...]:
    columns = tuple(
        connection.execute(
            "PRAGMA table_info(chat_cleared_message_scopes)"
        ).fetchall()
    )
    trigger = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'trigger'
          AND name = 'trg_chat_messages_reject_cleared_message'
        """
    ).fetchone()
    return columns, " ".join(str(trigger[0]).split())


def test_v8_blocks_recreation_of_one_cleared_message(tmp_path: Path) -> None:
    db_path = tmp_path / "chat-v7.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v7")

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', '', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_cleared_message_scopes(
                session_id, message_id, cleared_at_ms
            ) VALUES ('session-1', 'message-1', 2)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="message was cleared"):
            connection.execute(
                """
                INSERT INTO chat_messages(
                    message_id, session_id, user_id, role, message_kind,
                    created_at_ms, sequence_no
                ) VALUES (
                    'MESSAGE-1', 'SESSION-1', 'user-1', 'assistant',
                    'assistant_final', 3, 1
                )
                """
            )
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, user_id, role, message_kind,
                created_at_ms, sequence_no
            ) VALUES (
                'message-2', 'session-1', 'user-1', 'assistant',
                'assistant_final', 3, 2
            )
            """
        )


def test_v8_backfills_old_redacted_message_without_claiming_normal_hidden_rows(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v7-redacted.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v7")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', '', 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, user_id, role, message_kind,
                content_text, payload_json, is_visible,
                created_at_ms, sequence_no
            ) VALUES
                (
                    'old-deleted', 'session-1', 'user-1', 'assistant',
                    'assistant_final', '', '{}', 0, 1, 1
                ),
                (
                    'normal-hidden', 'session-1', 'user-1', 'assistant',
                    'assistant_interim', 'still owned', '{}', 0, 2, 2
                )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        barriers = connection.execute(
            """
            SELECT message_id
            FROM chat_cleared_message_scopes
            ORDER BY message_id
            """
        ).fetchall()
        assert barriers == [("old-deleted",)]
        with pytest.raises(sqlite3.IntegrityError, match="message was cleared"):
            connection.execute(
                """
                INSERT OR REPLACE INTO chat_messages(
                    message_id, session_id, user_id, role, message_kind,
                    content_text, created_at_ms, sequence_no
                ) VALUES (
                    'old-deleted', 'session-1', 'user-1', 'assistant',
                    'assistant_final', 'late', 3, 3
                )
                """
            )
        connection.execute(
            """
            INSERT OR REPLACE INTO chat_messages(
                message_id, session_id, user_id, role, message_kind,
                content_text, created_at_ms, sequence_no
            ) VALUES (
                'normal-hidden', 'session-1', 'user-1', 'assistant',
                'assistant_final', 'legitimate retry', 4, 4
            )
            """
        )


def test_v8_message_barrier_matches_fresh_baseline(tmp_path: Path) -> None:
    upgraded_path = tmp_path / "upgraded.db"
    upgraded_config = _chat_config(upgraded_path)
    command.upgrade(upgraded_config, "v7")
    command.upgrade(upgraded_config, "head")

    baseline_path = tmp_path / "baseline.db"
    command.upgrade(_chat_config(baseline_path), "v1")

    with sqlite3.connect(upgraded_path) as upgraded, sqlite3.connect(
        baseline_path
    ) as baseline:
        assert _barrier_contract(upgraded) == _barrier_contract(baseline)
