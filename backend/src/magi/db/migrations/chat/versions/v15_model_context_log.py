"""Add the canonical model-context log and current surface."""

from __future__ import annotations

from alembic import op

revision = "v15"
down_revision = "v14"
branch_labels = None
depends_on = None


_SESSION_SCOPED_TABLES = (
    "chat_model_context_heads",
    "chat_model_context_events",
    "chat_model_context_surface_nodes",
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
                  OR sessions.deleted_at_ms IS NOT NULL
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
        CREATE TABLE chat_model_context_heads (
            session_id TEXT COLLATE NOCASE PRIMARY KEY,
            generation INTEGER NOT NULL DEFAULT 1 CHECK (generation > 0),
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            last_sequence_no INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence_no >= 0),
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_model_context_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
            operation TEXT NOT NULL CHECK (operation IN ('append', 'surface_replace')),
            item_kind TEXT NOT NULL,
            item_json TEXT NOT NULL,
            turn_id TEXT,
            run_id TEXT,
            step_index INTEGER CHECK (step_index IS NULL OR step_index >= 0),
            created_at_ms INTEGER NOT NULL,
            UNIQUE (session_id, generation, sequence_no)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_chat_model_context_events_session_sequence
        ON chat_model_context_events(session_id, generation, sequence_no)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_chat_model_context_events_turn
        ON chat_model_context_events(session_id, turn_id, sequence_no)
        """
    )
    op.execute(
        """
        CREATE TABLE chat_model_context_surface_nodes (
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            position INTEGER NOT NULL CHECK (position >= 0),
            event_sequence_no INTEGER NOT NULL CHECK (event_sequence_no > 0),
            PRIMARY KEY (session_id, generation, position),
            UNIQUE (session_id, generation, event_sequence_no)
        )
        """
    )
    for table in _SESSION_SCOPED_TABLES:
        op.execute(_insert_trigger_sql(table))


def downgrade() -> None:
    for table in reversed(_SESSION_SCOPED_TABLES):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_reject_unavailable_session"
        )
    op.execute("DROP TABLE IF EXISTS chat_model_context_surface_nodes")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_events_turn")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_events_session_sequence")
    op.execute("DROP TABLE IF EXISTS chat_model_context_events")
    op.execute("DROP TABLE IF EXISTS chat_model_context_heads")
