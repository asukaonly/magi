"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_overridden INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    last_message_at_ms INTEGER,
    last_user_message_at_ms INTEGER,
    last_message_preview TEXT NOT NULL DEFAULT '',
    last_user_message_preview TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    workspace_path TEXT,
    history_version INTEGER NOT NULL DEFAULT 0,
    archived_at_ms INTEGER,
    deleted_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS chat_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    trace_id TEXT,
    orchestration_id TEXT,
    status TEXT NOT NULL,
    response_mode TEXT NOT NULL,
    execution_mode TEXT,
    ux_plan_json TEXT NOT NULL DEFAULT '{}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    error_text TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
    run_disposition TEXT,
    response_anchor_turn_id TEXT,
    superseded_by_turn_id TEXT,
    supersession_reason TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    content_text TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    is_final INTEGER NOT NULL DEFAULT 1,
    is_visible INTEGER NOT NULL DEFAULT 1,
    created_at_ms INTEGER NOT NULL,
    sequence_no INTEGER NOT NULL,
    replaces_message_id TEXT,
    replaced_by_message_id TEXT,
    persona_id TEXT,
    reply_to_message_id TEXT,
    label_json TEXT
);

CREATE TABLE IF NOT EXISTS chat_attachments (
    attachment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    storage_rel_path TEXT NOT NULL,
    sha256 TEXT,
    created_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_context_summaries (
    summary_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_summary_id TEXT,
    status TEXT NOT NULL DEFAULT 'building',
    summary_kind TEXT NOT NULL,
    persona_scope TEXT,
    covered_from_message_id TEXT,
    covered_to_message_id TEXT,
    first_kept_message_id TEXT,
    covered_to_sequence_no INTEGER,
    session_origin TEXT NOT NULL DEFAULT '',
    summary_text TEXT NOT NULL,
    prompt_profile TEXT NOT NULL DEFAULT 'general_chat',
    model_provider TEXT,
    model_id TEXT,
    token_count_before INTEGER,
    token_count_after INTEGER,
    quality_status TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_run_consumed_events (
    session_id     TEXT    NOT NULL,
    run_id         TEXT    NOT NULL,
    revision       INTEGER NOT NULL DEFAULT 0,
    message_id     TEXT    NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id, revision, message_id)
);

CREATE TABLE IF NOT EXISTS chat_user_turn_delivery (
    turn_id TEXT PRIMARY KEY,
    projection_completed INTEGER NOT NULL DEFAULT 0,
    runtime_enqueued INTEGER NOT NULL DEFAULT 0,
    runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions(user_id, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created
    ON chat_turns(session_id, created_at_ms ASC);

CREATE INDEX IF NOT EXISTS idx_chat_turns_user_updated
    ON chat_turns(user_id, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages(session_id, created_at_ms ASC, sequence_no ASC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_turn_sequence
    ON chat_messages(turn_id, sequence_no ASC);

CREATE INDEX IF NOT EXISTS idx_chat_attachments_session_created
    ON chat_attachments(session_id, created_at_ms ASC);

CREATE INDEX IF NOT EXISTS idx_chat_attachments_message_id
    ON chat_attachments(message_id);

CREATE INDEX IF NOT EXISTS idx_chat_context_summaries_session_status
    ON chat_context_summaries(session_id, status, updated_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_chat_context_summaries_frontier
    ON chat_context_summaries(session_id, summary_kind, persona_scope, covered_to_sequence_no DESC);

CREATE INDEX IF NOT EXISTS idx_crce_message
    ON chat_run_consumed_events(session_id, message_id);

CREATE INDEX IF NOT EXISTS idx_crce_run
    ON chat_run_consumed_events(session_id, run_id, revision);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_crce_run;

DROP INDEX IF EXISTS idx_crce_message;

DROP INDEX IF EXISTS idx_chat_context_summaries_frontier;

DROP INDEX IF EXISTS idx_chat_context_summaries_session_status;

DROP INDEX IF EXISTS idx_chat_attachments_message_id;

DROP INDEX IF EXISTS idx_chat_attachments_session_created;

DROP INDEX IF EXISTS idx_chat_messages_turn_sequence;

DROP INDEX IF EXISTS idx_chat_messages_session_created;

DROP INDEX IF EXISTS idx_chat_turns_user_updated;

DROP INDEX IF EXISTS idx_chat_turns_session_created;

DROP INDEX IF EXISTS idx_chat_sessions_user_updated;

DROP TABLE IF EXISTS chat_run_consumed_events;

DROP TABLE IF EXISTS chat_user_turn_delivery;

DROP TABLE IF EXISTS chat_context_summaries;

DROP TABLE IF EXISTS chat_attachments;

DROP TABLE IF EXISTS chat_messages;

DROP TABLE IF EXISTS chat_turns;

DROP TABLE IF EXISTS chat_sessions;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
