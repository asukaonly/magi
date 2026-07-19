from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command

from magi.db.migrations.chat import CHAT_MIGRATION_HEAD
from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def _drop_v9_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DROP INDEX IF EXISTS idx_chat_code_delegation_artifacts_scope"
    )
    connection.execute("DROP TABLE IF EXISTS chat_code_delegation_artifacts")
    connection.execute(
        "DROP INDEX IF EXISTS idx_chat_message_code_delegation_scope"
    )
    connection.execute(
        "DROP TABLE IF EXISTS chat_message_code_delegation_refs"
    )


def _delegation_contract(
    connection: sqlite3.Connection,
) -> tuple[object, ...]:
    message_columns = tuple(
        connection.execute(
            "PRAGMA table_info(chat_message_code_delegation_refs)"
        ).fetchall()
    )
    artifact_columns = tuple(
        connection.execute(
            "PRAGMA table_info(chat_code_delegation_artifacts)"
        ).fetchall()
    )
    raw_schema_rows = connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE name IN (
                'chat_message_code_delegation_refs',
                'idx_chat_message_code_delegation_scope',
                'chat_code_delegation_artifacts',
                'idx_chat_code_delegation_artifacts_scope'
            )
            ORDER BY type, name
            """
        ).fetchall()
    schema_rows = tuple(
        (row[0], row[1], " ".join(str(row[2]).split()))
        for row in raw_schema_rows
    )
    return message_columns, artifact_columns, schema_rows


def test_v9_backfills_message_ownership_and_orphan_cleanup_registry(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat-v8.db"
    config = _chat_config(db_path)
    command.upgrade(config, "v8")
    workspace_one = str((tmp_path / "workspace-one").resolve())
    workspace_two = str((tmp_path / "workspace-two").resolve())
    delegation_one = "ABCDEF0123456789ABCDEF0123456789"
    delegation_two = "1" * 32

    with sqlite3.connect(db_path) as connection:
        _drop_v9_schema(connection)
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'Existing chat', 1, 2)
            """
        )
        connection.executemany(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                content_text, payload_json, is_visible,
                created_at_ms, sequence_no
            ) VALUES (?, 'session-1', ?, 'user-1', 'assistant',
                      'assistant_final', 'private', ?, ?, ?, ?)
            """,
            [
                (
                    "message-valid",
                    "turn-valid",
                    json.dumps(
                        {
                            "code_agent_delegations": [
                                {
                                    "delegation_id": f" {delegation_one} ",
                                    "turn_id": " turn-valid ",
                                    "workspace_path": f" {workspace_one} ",
                                },
                                {
                                    "delegation_id": delegation_one.lower(),
                                    "turn_id": "turn-valid",
                                    "workspace_path": workspace_one,
                                },
                            ]
                        }
                    ),
                    1,
                    10,
                    1,
                ),
                (
                    "message-hidden",
                    "turn-hidden",
                    json.dumps(
                        {
                            "code_agent_delegations": [
                                {
                                    "delegation_id": delegation_two,
                                    "turn_id": "turn-hidden",
                                    "workspace_path": workspace_two,
                                }
                            ]
                        }
                    ),
                    0,
                    11,
                    2,
                ),
                (
                    "message-invalid",
                    "turn-invalid",
                    json.dumps(
                        {
                            "code_agent_delegations": [
                                {
                                    "delegation_id": "not-a-safe-id",
                                    "turn_id": "turn-invalid",
                                    "workspace_path": workspace_one,
                                },
                                {
                                    "delegation_id": "2" * 32,
                                    "turn_id": "",
                                    "workspace_path": workspace_one,
                                },
                                {
                                    "delegation_id": "3" * 32,
                                    "turn_id": "turn-relative",
                                    "workspace_path": "relative/workspace",
                                },
                            ]
                        }
                    ),
                    1,
                    12,
                    3,
                ),
                (
                    "message-invalid-json",
                    "turn-invalid-json",
                    "{",
                    1,
                    13,
                    4,
                ),
            ],
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == (CHAT_MIGRATION_HEAD,)
        assert connection.execute(
            """
            SELECT
                message_id,
                session_id,
                delegation_id,
                turn_id,
                workspace_path,
                created_at_ms
            FROM chat_message_code_delegation_refs
            ORDER BY message_id
            """
        ).fetchall() == [
            (
                "message-hidden",
                "session-1",
                delegation_two,
                "turn-hidden",
                workspace_two,
                11,
            ),
            (
                "message-valid",
                "session-1",
                delegation_one.lower(),
                "turn-valid",
                workspace_one,
                10,
            ),
        ]
        assert connection.execute(
            """
            SELECT
                session_id,
                delegation_id,
                turn_id,
                workspace_path,
                created_at_ms
            FROM chat_code_delegation_artifacts
            ORDER BY delegation_id
            """
        ).fetchall() == [
            (
                "session-1",
                delegation_two,
                "turn-hidden",
                workspace_two,
                11,
            ),
            (
                "session-1",
                delegation_one.lower(),
                "turn-valid",
                workspace_one,
                10,
            ),
        ]

    command.downgrade(config, "v8")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'chat_message_code_delegation_refs'
            """
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'chat_code_delegation_artifacts'
            """
        ).fetchone() is None

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT message_id, delegation_id
            FROM chat_message_code_delegation_refs
            ORDER BY message_id
            """
        ).fetchall() == [
            ("message-hidden", delegation_two),
            ("message-valid", delegation_one.lower()),
        ]


def test_v9_upgraded_schema_matches_fresh_database(tmp_path: Path) -> None:
    upgraded_path = tmp_path / "upgraded.db"
    upgraded_config = _chat_config(upgraded_path)
    command.upgrade(upgraded_config, "v8")
    with sqlite3.connect(upgraded_path) as connection:
        _drop_v9_schema(connection)
        connection.commit()
    command.upgrade(upgraded_config, "head")

    fresh_path = tmp_path / "fresh.db"
    command.upgrade(_chat_config(fresh_path), "head")

    with sqlite3.connect(upgraded_path) as upgraded, sqlite3.connect(
        fresh_path
    ) as fresh:
        assert _delegation_contract(upgraded) == _delegation_contract(fresh)
