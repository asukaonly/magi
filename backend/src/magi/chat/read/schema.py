"""SQLite schema helpers for chat read storage."""
from __future__ import annotations

import sqlite3

CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"
CHAT_ATTACHMENTS_TABLE = "chat_attachments"
CHAT_CONTEXT_SUMMARIES_TABLE = "chat_context_summaries"

CHAT_STORE_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {CHAT_SESSIONS_TABLE} (
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
CREATE TABLE IF NOT EXISTS {CHAT_TURNS_TABLE} (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    trace_id TEXT,
    orchestration_id TEXT,
    status TEXT NOT NULL,
    response_mode TEXT NOT NULL,
    execution_mode TEXT,
    ux_plan_json TEXT NOT NULL DEFAULT '{{}}',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    completed_at_ms INTEGER,
    error_text TEXT,
    run_id TEXT,
    run_revision INTEGER NOT NULL DEFAULT 0,
    run_disposition TEXT
);
CREATE TABLE IF NOT EXISTS {CHAT_MESSAGES_TABLE} (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    content_text TEXT,
    payload_json TEXT NOT NULL DEFAULT '{{}}',
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
CREATE TABLE IF NOT EXISTS {CHAT_ATTACHMENTS_TABLE} (
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
CREATE TABLE IF NOT EXISTS {CHAT_CONTEXT_SUMMARIES_TABLE} (
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
"""


def ensure_chat_store_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CHAT_STORE_SCHEMA_SQL)
    column_names = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({CHAT_TURNS_TABLE})").fetchall()
    }
    if "run_id" not in column_names:
        conn.execute(f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_id TEXT")
    if "run_revision" not in column_names:
        conn.execute(
            f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_revision INTEGER NOT NULL DEFAULT 0"
        )
    if "run_disposition" not in column_names:
        conn.execute(f"ALTER TABLE {CHAT_TURNS_TABLE} ADD COLUMN run_disposition TEXT")

    session_column_names = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({CHAT_SESSIONS_TABLE})").fetchall()
    }
    if "history_version" not in session_column_names:
        conn.execute(
            f"ALTER TABLE {CHAT_SESSIONS_TABLE} ADD COLUMN history_version INTEGER NOT NULL DEFAULT 0"
        )
    if "workspace_path" not in session_column_names:
        conn.execute(f"ALTER TABLE {CHAT_SESSIONS_TABLE} ADD COLUMN workspace_path TEXT")

    message_column_names = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({CHAT_MESSAGES_TABLE})").fetchall()
    }
    if "reply_to_message_id" not in message_column_names:
        conn.execute(f"ALTER TABLE {CHAT_MESSAGES_TABLE} ADD COLUMN reply_to_message_id TEXT")
    if "label_json" not in message_column_names:
        conn.execute(f"ALTER TABLE {CHAT_MESSAGES_TABLE} ADD COLUMN label_json TEXT")
    if "persona_id" not in message_column_names:
        conn.execute(f"ALTER TABLE {CHAT_MESSAGES_TABLE} ADD COLUMN persona_id TEXT")

    summary_column_names = {
        str(row[1])
        for row in conn.execute(f"PRAGMA table_info({CHAT_CONTEXT_SUMMARIES_TABLE})").fetchall()
    }
    summary_migrations = {
        "parent_summary_id": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN parent_summary_id TEXT",
        "status": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN status TEXT NOT NULL DEFAULT 'building'",
        "summary_kind": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN summary_kind TEXT NOT NULL DEFAULT 'token_budget'",
        "persona_scope": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN persona_scope TEXT",
        "covered_from_message_id": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN covered_from_message_id TEXT",
        "covered_to_message_id": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN covered_to_message_id TEXT",
        "first_kept_message_id": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN first_kept_message_id TEXT",
        "covered_to_sequence_no": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN covered_to_sequence_no INTEGER",
        "session_origin": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN session_origin TEXT NOT NULL DEFAULT ''",
        "summary_text": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN summary_text TEXT NOT NULL DEFAULT ''",
        "prompt_profile": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN prompt_profile TEXT NOT NULL DEFAULT 'general_chat'",
        "model_provider": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN model_provider TEXT",
        "model_id": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN model_id TEXT",
        "token_count_before": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN token_count_before INTEGER",
        "token_count_after": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN token_count_after INTEGER",
        "quality_status": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN quality_status TEXT",
        "created_at_ms": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN created_at_ms INTEGER NOT NULL DEFAULT 0",
        "updated_at_ms": f"ALTER TABLE {CHAT_CONTEXT_SUMMARIES_TABLE} ADD COLUMN updated_at_ms INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, sql in summary_migrations.items():
        if summary_column_names and column_name not in summary_column_names:
            conn.execute(sql)
