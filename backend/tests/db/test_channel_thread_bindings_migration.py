"""Migration preserves conversation identity while introducing thread scope."""
import sqlite3

from alembic import command

from magi.db.runner import MIGRATION_TARGETS, _build_config


def test_existing_binding_survives_thread_migration(tmp_path):
    path = tmp_path / "channels.db"
    target = next(target for target in MIGRATION_TARGETS if target.name == "channels")
    config = _build_config(target, path)
    command.upgrade(config, "v2")
    with sqlite3.connect(path) as db:
        db.execute("""
            INSERT INTO channel_session_mappings
            (channel_type, external_chat_id, magi_session_id, magi_user_id,
             is_group, created_at_ms, last_active_at_ms, metadata_json)
            VALUES ('account:telegram', 'chat', 'session', 'user', 1, 10, 20, '{"name":"group"}')
        """)
    command.upgrade(config, "v3")
    with sqlite3.connect(path) as db:
        assert db.execute("""
            SELECT channel_type, external_chat_id, external_thread_id, magi_session_id,
                   magi_user_id, is_group, created_at_ms, last_active_at_ms, metadata_json
            FROM channel_session_mappings
        """).fetchone() == ('account:telegram', 'chat', '', 'session', 'user', 1, 10, 20, '{"name":"group"}')
        db.execute("""
            INSERT INTO channel_session_mappings
            (channel_type, external_chat_id, external_thread_id, magi_session_id,
             magi_user_id, created_at_ms, last_active_at_ms)
            VALUES ('account:telegram', 'chat', 'topic', 'topic-session', 'user', 30, 30)
        """)
        assert db.execute("SELECT COUNT(*) FROM channel_session_mappings").fetchone() == (2,)
