from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from alembic import command
import pytest

from magi.db.runner import MIGRATION_TARGETS, _build_config


def _chat_config(db_path: Path):
    target = next(item for item in MIGRATION_TARGETS if item.name == "chat")
    return _build_config(target, db_path)


def test_chat_asset_owner_migration_backfills_attachment_and_payload_paths(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "chat" / "chat.db"
    db_path.parent.mkdir(parents=True)
    config = _chat_config(db_path)
    command.upgrade(config, "v2")
    original_rel_path = (
        "data/resources/chat/files/session-1/turn-1/attachment-1__source.txt"
    )
    derived_rel_path = "data/resources/chat/derived/session-1/turn-1/attachment-1.txt"
    payload_only_rel_path = (
        "data/resources/chat/images/session-2/turn-2/"
        "different-attachment__payload-only.png"
    )
    loop_a = tmp_path / "data" / "resources" / "chat" / "files" / "loop-a"
    loop_b = loop_a.with_name("loop-b")
    loop_a.parent.mkdir(parents=True)
    try:
        loop_a.symlink_to(loop_b)
        loop_b.symlink_to(loop_a)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_chat_message_asset_refs_asset_key")
        connection.execute("DROP TABLE chat_message_asset_refs")
        connection.execute(
            """
            INSERT INTO chat_sessions(
                session_id, user_id, title, created_at_ms, updated_at_ms
            ) VALUES ('session-1', 'user-1', 'one', 1, 1),
                     ('session-2', 'user-1', 'two', 2, 2)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_messages(
                message_id, session_id, turn_id, user_id, role, message_kind,
                payload_json, created_at_ms, sequence_no
            ) VALUES (?, 'session-1', 'turn-1', 'user-1', 'user', 'user_text', ?, 1, 1),
                     (?, 'session-2', 'turn-2', 'user-1', 'user', 'user_text', ?, 2, 1)
            """,
            (
                "message-1",
                json.dumps(
                    {
                        "attachments": [
                            {
                                "attachment_id": "attachment-1",
                                "derived_text_path": derived_rel_path,
                            }
                        ]
                    }
                ),
                "message-2",
                json.dumps(
                    {
                        "attachments": [
                            {
                                "attachment_id": "payload-only",
                                "storage_path": payload_only_rel_path,
                            },
                            {"storage_path": str(loop_a)},
                        ]
                    }
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO chat_attachments(
                attachment_id, session_id, turn_id, message_id, user_id,
                kind, storage_rel_path, created_at_ms
            ) VALUES (
                'attachment-1', 'session-1', 'turn-1', 'message-1', 'user-1',
                'file', ?, 1
            )
            """,
            (original_rel_path,),
        )
        connection.commit()

    command.upgrade(config, "head")

    expected_rows = [
        (
            "message-1",
            "derived/session-1/turn-1/attachment-1.txt",
            derived_rel_path,
            "derived_text",
        ),
        (
            "message-1",
            "files/session-1/turn-1/attachment-1__source.txt",
            original_rel_path,
            "attachment",
        ),
            (
                "message-2",
                "derived/session-2/turn-2/payload-only.txt",
                "data/resources/chat/derived/session-2/turn-2/payload-only.txt",
                "derived_text",
            ),
        ]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT message_id, asset_key, storage_rel_path, asset_kind
            FROM chat_message_asset_refs
            ORDER BY message_id, asset_key
            """
        ).fetchall() == expected_rows
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'idx_chat_message_asset_refs_asset_key'
            """
        ).fetchone() == (1,)

    command.downgrade(config, "v2")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'chat_message_asset_refs'
            """
        ).fetchone() is None

    command.upgrade(config, "head")
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT message_id, asset_key, storage_rel_path, asset_kind
            FROM chat_message_asset_refs
            ORDER BY message_id, asset_key
            """
        ).fetchall() == expected_rows


def test_chat_asset_owner_migration_rejects_retargeted_resource_root(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "chat" / "chat.db"
    db_path.parent.mkdir(parents=True)
    config = _chat_config(db_path)
    command.upgrade(config, "v2")
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX idx_chat_message_asset_refs_asset_key")
        connection.execute("DROP TABLE chat_message_asset_refs")
        connection.commit()

    resources_parent = tmp_path / "data" / "resources"
    resources_parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (resources_parent / "chat").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not available on this platform")

    with pytest.raises(RuntimeError, match="resources root was retargeted"):
        command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'chat_message_asset_refs'
            """
        ).fetchone() is None
