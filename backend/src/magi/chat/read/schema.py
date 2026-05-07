"""SQLite schema constants for chat read storage.

Schema is owned by alembic (``magi.db.migrations.chat``); this module
only re-exports table names referenced by query code.
"""
from __future__ import annotations

import sqlite3

CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"
CHAT_ATTACHMENTS_TABLE = "chat_attachments"
CHAT_CONTEXT_SUMMARIES_TABLE = "chat_context_summaries"


def ensure_chat_store_schema(conn: sqlite3.Connection) -> None:
    """No-op kept for compatibility — schema is alembic-managed."""
    return None
