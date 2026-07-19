"""Prevent cleared chat sessions from being recreated by late writes."""

from __future__ import annotations

from alembic import op

revision = "v7"
down_revision = "v6"
branch_labels = None
depends_on = None


_SESSION_SCOPED_TABLES = (
    "chat_turns",
    "chat_messages",
    "chat_attachments",
    "chat_context_summaries",
    "chat_run_consumed_events",
    "chat_assistant_memory_outbox",
)


def _insert_trigger_sql(table: str) -> str:
    trigger = f"trg_{table}_reject_unavailable_session"
    return f"""
        CREATE TRIGGER IF NOT EXISTS {trigger}
        BEFORE INSERT ON {table}
        WHEN EXISTS (
            SELECT 1
            FROM chat_global_clear_intent
            WHERE intent_key = 'global'
        )
        OR EXISTS (
            SELECT 1
            FROM chat_cleared_session_scopes AS cleared
            WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
        )
        OR EXISTS (
            SELECT 1
            FROM chat_sessions AS sessions
            WHERE sessions.session_id = NEW.session_id COLLATE NOCASE
              AND (
                  sessions.session_id != NEW.session_id
                  OR
                  sessions.deleted_at_ms IS NOT NULL
                  OR sessions.archived_at_ms IS NOT NULL
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'chat session is unavailable');
        END
    """


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_cleared_session_scopes (
            session_id TEXT COLLATE NOCASE PRIMARY KEY,
            cleared_at_ms INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        INSERT OR IGNORE INTO chat_cleared_session_scopes(
            session_id,
            cleared_at_ms
        )
        SELECT session_id, deleted_at_ms
        FROM chat_sessions
        WHERE deleted_at_ms IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_session_id_nocase
        ON chat_sessions(session_id COLLATE NOCASE)
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_chat_sessions_reject_cleared_session
        BEFORE INSERT ON chat_sessions
        WHEN EXISTS (
            SELECT 1
            FROM chat_global_clear_intent
            WHERE intent_key = 'global'
        )
        OR EXISTS (
            SELECT 1
            FROM chat_cleared_session_scopes AS cleared
            WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
        )
        BEGIN
            SELECT RAISE(ABORT, 'chat session was cleared');
        END
        """
    )
    for table in _SESSION_SCOPED_TABLES:
        op.execute(_insert_trigger_sql(table))


def downgrade() -> None:
    for table in reversed(_SESSION_SCOPED_TABLES):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_reject_unavailable_session"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_chat_sessions_reject_cleared_session")
    op.execute("DROP INDEX IF EXISTS uq_chat_sessions_session_id_nocase")
    op.execute("DROP TABLE IF EXISTS chat_cleared_session_scopes")
