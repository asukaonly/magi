"""Keep external conversation threads in separate session bindings."""

from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("ALTER TABLE channel_session_mappings RENAME TO channel_session_mappings_old")
    connection.exec_driver_sql("DROP INDEX idx_csm_session")
    connection.exec_driver_sql("""
        CREATE TABLE channel_session_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_type TEXT NOT NULL,
            external_chat_id TEXT NOT NULL,
            external_thread_id TEXT NOT NULL DEFAULT '',
            magi_session_id TEXT NOT NULL,
            magi_user_id TEXT NOT NULL,
            is_group INTEGER NOT NULL DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            last_active_at_ms INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(channel_type, external_chat_id, external_thread_id)
        )
    """)
    connection.exec_driver_sql("""
        INSERT INTO channel_session_mappings
            (id, channel_type, external_chat_id, external_thread_id,
             magi_session_id, magi_user_id, is_group, created_at_ms,
             last_active_at_ms, metadata_json)
        SELECT id, channel_type, external_chat_id, '', magi_session_id,
               magi_user_id, is_group, created_at_ms, last_active_at_ms, metadata_json
        FROM channel_session_mappings_old
    """)
    connection.exec_driver_sql("DROP TABLE channel_session_mappings_old")
    connection.exec_driver_sql("CREATE INDEX idx_csm_session ON channel_session_mappings(magi_session_id)")


def downgrade() -> None:
    raise RuntimeError("Thread-scoped bindings require restoring a pre-migration snapshot")
