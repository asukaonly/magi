"""SQLite schema helpers for the chat write store."""
from __future__ import annotations

import aiosqlite

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
"""


async def ensure_chat_store_schema(db: aiosqlite.Connection) -> None:
    await db.executescript(CHAT_STORE_SCHEMA_SQL)
    await ensure_chat_session_columns(db)
    await ensure_chat_turn_columns(db)
    await ensure_chat_message_columns(db)


async def ensure_chat_turn_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(chat_turns)")
    rows = await cursor.fetchall()
    column_names = {str(row[1]) for row in rows}
    if "run_id" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN run_id TEXT")
    if "run_revision" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN run_revision INTEGER NOT NULL DEFAULT 0")
    if "run_disposition" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN run_disposition TEXT")
    if "response_anchor_turn_id" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN response_anchor_turn_id TEXT")
    if "superseded_by_turn_id" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN superseded_by_turn_id TEXT")
    if "supersession_reason" not in column_names:
        await db.execute("ALTER TABLE chat_turns ADD COLUMN supersession_reason TEXT")


async def ensure_chat_session_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(chat_sessions)")
    rows = await cursor.fetchall()
    column_names = {str(row[1]) for row in rows}
    if "history_version" not in column_names:
        await db.execute(
            "ALTER TABLE chat_sessions ADD COLUMN history_version INTEGER NOT NULL DEFAULT 0"
        )
    if "workspace_path" not in column_names:
        await db.execute("ALTER TABLE chat_sessions ADD COLUMN workspace_path TEXT")


async def ensure_chat_message_columns(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(chat_messages)")
    rows = await cursor.fetchall()
    column_names = {str(row[1]) for row in rows}
    if "reply_to_message_id" not in column_names:
        await db.execute("ALTER TABLE chat_messages ADD COLUMN reply_to_message_id TEXT")
    if "label_json" not in column_names:
        await db.execute("ALTER TABLE chat_messages ADD COLUMN label_json TEXT")
