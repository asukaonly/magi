"""Add reconstructible model-call epochs and boundaries."""

from __future__ import annotations

from alembic import op

revision = "v16"
down_revision = "v15"
branch_labels = None
depends_on = None


_SESSION_SCOPED_TABLES = (
    "chat_model_context_epochs",
    "chat_model_context_boundaries",
)


def _insert_trigger_sql(table: str) -> str:
    trigger = f"trg_{table}_reject_unavailable_session"
    return f"""
CREATE TRIGGER IF NOT EXISTS {trigger}
BEFORE INSERT ON {table}
WHEN EXISTS (
    SELECT 1 FROM chat_global_clear_intent WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1 FROM chat_cleared_session_scopes AS cleared
    WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
)
OR EXISTS (
    SELECT 1 FROM chat_sessions AS sessions
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
        CREATE TABLE IF NOT EXISTS chat_model_context_epochs (
            epoch_id TEXT PRIMARY KEY,
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            system_hash TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            tools_hash TEXT NOT NULL,
            tools_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            UNIQUE (session_id, generation, system_hash, tools_hash)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_model_context_boundaries (
            boundary_id TEXT PRIMARY KEY,
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            boundary_no INTEGER NOT NULL CHECK (boundary_no > 0),
            surface_revision INTEGER NOT NULL CHECK (surface_revision >= 0),
            epoch_id TEXT NOT NULL,
            boundary_kind TEXT NOT NULL,
            turn_id TEXT,
            run_id TEXT,
            step_index INTEGER CHECK (step_index IS NULL OR step_index >= 0),
            created_at_ms INTEGER NOT NULL,
            UNIQUE (session_id, generation, boundary_no)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_model_context_boundaries_turn
        ON chat_model_context_boundaries(session_id, turn_id, boundary_no)
        """
    )
    for table in _SESSION_SCOPED_TABLES:
        op.execute(_insert_trigger_sql(table))


def downgrade() -> None:
    for table in reversed(_SESSION_SCOPED_TABLES):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_reject_unavailable_session"
        )
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_boundaries_turn")
    op.execute("DROP TABLE IF EXISTS chat_model_context_boundaries")
    op.execute("DROP TABLE IF EXISTS chat_model_context_epochs")
