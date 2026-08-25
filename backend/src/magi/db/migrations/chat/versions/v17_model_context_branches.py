"""Replace disposable model context with immutable revisions and run branches."""

from __future__ import annotations

from alembic import op

revision = "v17"
down_revision = "v16"
branch_labels = None
depends_on = None


_TABLES = (
    "chat_model_context_heads",
    "chat_model_context_events",
    "chat_model_context_revisions",
    "chat_model_context_surface_nodes",
    "chat_model_context_run_heads",
    "chat_model_context_epochs",
    "chat_model_context_boundaries",
)


def _insert_trigger_sql(table: str) -> str:
    trigger = f"trg_{table}_reject_unavailable_session"
    return f"""
CREATE TRIGGER IF NOT EXISTS {trigger}
BEFORE INSERT ON {table}
WHEN NOT EXISTS (
    SELECT 1
    FROM chat_sessions AS sessions
    WHERE sessions.session_id = NEW.session_id COLLATE NOCASE
      AND sessions.session_id = NEW.session_id
      AND sessions.deleted_at_ms IS NULL
      AND sessions.archived_at_ms IS NULL
)
OR EXISTS (
    SELECT 1 FROM chat_global_clear_intent WHERE intent_key = 'global'
)
OR EXISTS (
    SELECT 1 FROM chat_cleared_session_scopes AS cleared
    WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
)
BEGIN
    SELECT RAISE(ABORT, 'chat session is unavailable');
END
    """


def _drop_current_tables() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_reject_unavailable_session")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_boundaries_turn")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_events_turn")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_events_session_sequence")
    op.execute("DROP INDEX IF EXISTS idx_chat_model_context_run_heads_status")
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def upgrade() -> None:
    _drop_current_tables()
    op.execute(
        """
        CREATE TABLE chat_model_context_heads (
            session_id TEXT COLLATE NOCASE PRIMARY KEY,
            generation INTEGER NOT NULL DEFAULT 1 CHECK (generation > 0),
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            accepted_revision INTEGER NOT NULL DEFAULT 0 CHECK (accepted_revision >= 0),
            last_sequence_no INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence_no >= 0),
            updated_at_ms INTEGER NOT NULL,
            CHECK (accepted_revision <= revision)
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
            operation TEXT NOT NULL,
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
        CREATE TABLE chat_model_context_revisions (
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            parent_revision INTEGER NOT NULL CHECK (parent_revision >= 0),
            branch_kind TEXT NOT NULL CHECK (branch_kind IN ('accepted', 'working')),
            run_id TEXT,
            item_count INTEGER NOT NULL CHECK (item_count >= 0),
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY (session_id, generation, revision)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_model_context_surface_nodes (
            session_id TEXT COLLATE NOCASE NOT NULL,
            generation INTEGER NOT NULL CHECK (generation > 0),
            revision INTEGER NOT NULL CHECK (revision > 0),
            position INTEGER NOT NULL CHECK (position >= 0),
            event_sequence_no INTEGER NOT NULL CHECK (event_sequence_no > 0),
            PRIMARY KEY (session_id, generation, revision, position),
            UNIQUE (session_id, generation, revision, event_sequence_no)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_model_context_run_heads (
            session_id TEXT COLLATE NOCASE NOT NULL,
            run_id TEXT NOT NULL,
            turn_id TEXT,
            generation INTEGER NOT NULL CHECK (generation > 0),
            base_revision INTEGER NOT NULL CHECK (base_revision >= 0),
            working_revision INTEGER NOT NULL CHECK (working_revision >= 0),
            status TEXT NOT NULL CHECK (status IN ('active', 'accepted', 'abandoned')),
            updated_at_ms INTEGER NOT NULL,
            PRIMARY KEY (session_id, run_id),
            CHECK (working_revision >= base_revision)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_chat_model_context_run_heads_status
        ON chat_model_context_run_heads(session_id, status, updated_at_ms)
        """
    )
    op.execute(
        """
        CREATE TABLE chat_model_context_epochs (
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
        CREATE TABLE chat_model_context_boundaries (
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
            request_options_json TEXT NOT NULL DEFAULT '{}',
            created_at_ms INTEGER NOT NULL,
            UNIQUE (session_id, generation, boundary_no)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_chat_model_context_boundaries_turn
        ON chat_model_context_boundaries(session_id, turn_id, boundary_no)
        """
    )
    for table in _TABLES:
        op.execute(_insert_trigger_sql(table))


def downgrade() -> None:
    _drop_current_tables()
    from magi.db.migrations.chat.versions import (
        v15_model_context_log,
        v16_model_context_boundaries,
    )

    v15_model_context_log.upgrade()
    v16_model_context_boundaries.upgrade()
