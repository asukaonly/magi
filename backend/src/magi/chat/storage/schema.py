"""SQLite schema helpers for the chat write store."""
from __future__ import annotations

CHAT_STORE_SCHEMA_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions(user_id, updated_at_ms DESC);

CREATE TABLE IF NOT EXISTS chat_session_creation_requests (
    user_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (user_id, idempotency_key)
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
CREATE INDEX IF NOT EXISTS idx_chat_turns_session_created
    ON chat_turns(session_id, created_at_ms ASC);
CREATE INDEX IF NOT EXISTS idx_chat_turns_user_updated
    ON chat_turns(user_id, updated_at_ms DESC);

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
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages(session_id, created_at_ms ASC, sequence_no ASC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_turn_sequence
    ON chat_messages(turn_id, sequence_no ASC);

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
CREATE INDEX IF NOT EXISTS idx_chat_attachments_session_created
    ON chat_attachments(session_id, created_at_ms ASC);
CREATE INDEX IF NOT EXISTS idx_chat_attachments_message_id
    ON chat_attachments(message_id);

CREATE TABLE IF NOT EXISTS chat_message_asset_refs (
    message_id TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    storage_rel_path TEXT NOT NULL,
    asset_kind TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (message_id, asset_key)
);
CREATE INDEX IF NOT EXISTS idx_chat_message_asset_refs_asset_key
    ON chat_message_asset_refs(asset_key, message_id);

CREATE TABLE IF NOT EXISTS chat_message_code_delegation_refs (
    message_id TEXT NOT NULL,
    session_id TEXT COLLATE NOCASE NOT NULL,
    delegation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (message_id, delegation_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_message_code_delegation_scope
    ON chat_message_code_delegation_refs(
        workspace_path,
        session_id,
        delegation_id,
        message_id
    );

CREATE TABLE IF NOT EXISTS chat_code_delegation_artifacts (
    workspace_path TEXT NOT NULL,
    session_id TEXT COLLATE NOCASE NOT NULL,
    delegation_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    PRIMARY KEY (workspace_path, session_id, delegation_id)
);
CREATE INDEX IF NOT EXISTS idx_chat_code_delegation_artifacts_scope
    ON chat_code_delegation_artifacts(
        session_id,
        turn_id,
        delegation_id
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
CREATE INDEX IF NOT EXISTS idx_chat_context_summaries_session_status
    ON chat_context_summaries(session_id, status, updated_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_chat_context_summaries_frontier
    ON chat_context_summaries(session_id, summary_kind, persona_scope, covered_to_sequence_no DESC);

CREATE TABLE IF NOT EXISTS chat_context_usage_snapshots (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    used_tokens INTEGER NOT NULL CHECK (used_tokens > 0),
    context_window INTEGER NOT NULL CHECK (context_window > 0),
    input_capacity INTEGER NOT NULL CHECK (input_capacity > 0),
    compaction_threshold INTEGER NOT NULL CHECK (compaction_threshold > 0),
    measurement TEXT NOT NULL
        CHECK (measurement IN ('actual', 'estimated')),
    model_provider TEXT,
    model_id TEXT,
    updated_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_context_usage_session_updated
    ON chat_context_usage_snapshots(session_id, updated_at_ms DESC, turn_id);

CREATE TABLE IF NOT EXISTS chat_run_consumed_events (
    session_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    message_id TEXT NOT NULL,
    recorded_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, run_id, revision, message_id)
);
CREATE INDEX IF NOT EXISTS idx_crce_message
    ON chat_run_consumed_events(session_id, message_id);
CREATE INDEX IF NOT EXISTS idx_crce_run
    ON chat_run_consumed_events(session_id, run_id, revision);

CREATE TABLE IF NOT EXISTS chat_user_turn_delivery (
    turn_id TEXT PRIMARY KEY,
    projection_completed INTEGER NOT NULL DEFAULT 0,
    delivery_attempt_no INTEGER NOT NULL DEFAULT 0
        CHECK (delivery_attempt_no >= 0),
    delivery_state TEXT NOT NULL DEFAULT 'ready'
        CHECK (delivery_state IN ('ready', 'queued', 'admitted', 'terminal')),
    current_command_id INTEGER,
    runtime_envelope_json TEXT NOT NULL DEFAULT '{}',
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    CHECK (
        (delivery_state = 'ready' AND current_command_id IS NULL)
        OR delivery_state = 'terminal'
        OR current_command_id IS NOT NULL
    )
);
CREATE INDEX IF NOT EXISTS idx_chat_user_turn_delivery_recovery
    ON chat_user_turn_delivery(delivery_state, updated_at_ms, turn_id);

CREATE TABLE IF NOT EXISTS chat_assistant_memory_outbox (
    canonical_message_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    content_text TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'claimed')),
    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    next_attempt_at_ms INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at_ms INTEGER,
    last_error TEXT,
    updated_at_ms INTEGER NOT NULL,
    CHECK (
        (state = 'pending' AND lease_token IS NULL AND lease_expires_at_ms IS NULL)
        OR (state = 'claimed' AND lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_chat_assistant_memory_outbox_ready
    ON chat_assistant_memory_outbox(
        state,
        next_attempt_at_ms,
        lease_expires_at_ms,
        created_at_ms,
        canonical_message_id
    );
CREATE INDEX IF NOT EXISTS idx_chat_assistant_memory_outbox_session
    ON chat_assistant_memory_outbox(session_id, canonical_message_id);

CREATE TABLE IF NOT EXISTS chat_global_clear_intent (
    intent_key TEXT PRIMARY KEY
        CHECK (intent_key = 'global'),
    requested_at_ms INTEGER NOT NULL,
    session_count INTEGER NOT NULL DEFAULT 0
        CHECK (session_count >= 0)
);

CREATE TABLE IF NOT EXISTS chat_cleared_session_scopes (
    session_id TEXT COLLATE NOCASE PRIMARY KEY,
    cleared_at_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_cleared_message_scopes (
    session_id TEXT COLLATE NOCASE NOT NULL,
    message_id TEXT COLLATE NOCASE NOT NULL,
    cleared_at_ms INTEGER NOT NULL,
    PRIMARY KEY (session_id, message_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_session_id_nocase
    ON chat_sessions(session_id COLLATE NOCASE);

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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_turns_reject_unavailable_session
BEFORE INSERT ON chat_turns
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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_messages_reject_unavailable_session
BEFORE INSERT ON chat_messages
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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_messages_reject_cleared_message
BEFORE INSERT ON chat_messages
WHEN EXISTS (
    SELECT 1
    FROM chat_cleared_message_scopes AS cleared
    WHERE cleared.session_id = NEW.session_id COLLATE NOCASE
      AND cleared.message_id = NEW.message_id COLLATE NOCASE
)
BEGIN
    SELECT RAISE(ABORT, 'chat message was cleared');
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_attachments_reject_unavailable_session
BEFORE INSERT ON chat_attachments
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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_context_summaries_reject_unavailable_session
BEFORE INSERT ON chat_context_summaries
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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_run_consumed_events_reject_unavailable_session
BEFORE INSERT ON chat_run_consumed_events
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
END;

CREATE TRIGGER IF NOT EXISTS trg_chat_assistant_memory_outbox_reject_unavailable_session
BEFORE INSERT ON chat_assistant_memory_outbox
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
END;
"""
