"""Preserve notification content and read state while canonicalizing local ownership."""

import sqlite3

from alembic import command

from magi.db.runner import _build_config, get_migration_target


def test_upgrade_preserves_rows_and_new_default_owner(tmp_path):
    path = tmp_path / "trace.db"
    config = _build_config(get_migration_target("runtime_trace"), path)
    command.upgrade(config, "v9")
    with sqlite3.connect(path) as db:
        for owner, status in [
            ("default_user", "read"),
            ("local_user", "dismissed"),
            ("another-user", "unread"),
        ]:
            db.execute(
                "INSERT INTO user_notifications(user_id,kind,dedupe_key,title,body,status,created_at_ms) VALUES(?, 'suggestion', ?, 'title', 'body', ?, 1)",
                (owner, owner, status),
            )
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT user_id,status,title,body FROM user_notifications ORDER BY id"
        ).fetchall() == [
            ("local_user", "read", "title", "body"),
            ("local_user", "dismissed", "title", "body"),
            ("another-user", "unread", "title", "body"),
        ]
        db.execute(
            "INSERT INTO user_notifications(kind,dedupe_key,title,body,created_at_ms) VALUES('suggestion','new','title','body',2)"
        )
        assert db.execute(
            "SELECT user_id FROM user_notifications WHERE dedupe_key='new'"
        ).fetchone() == ("local_user",)
