"""SQLite schema constants for chat read storage.

Schema is owned by alembic (``magi.db.migrations.chat``); this module
only re-exports table names referenced by query code.
"""
from __future__ import annotations

CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"
CHAT_ATTACHMENTS_TABLE = "chat_attachments"
CHAT_CONTEXT_SUMMARIES_TABLE = "chat_context_summaries"
CHAT_RUN_CONSUMED_EVENTS_TABLE = "chat_run_consumed_events"
CHAT_USER_TURN_DELIVERY_TABLE = "chat_user_turn_delivery"
