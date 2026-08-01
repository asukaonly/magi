"""SQLite schema constants for chat read storage.

Schema is owned by alembic (``magi.db.migrations.chat``); this module
only re-exports table names referenced by query code.
"""
from __future__ import annotations

CHAT_SESSIONS_TABLE = "chat_sessions"
CHAT_SESSION_CREATION_REQUESTS_TABLE = "chat_session_creation_requests"
CHAT_TURNS_TABLE = "chat_turns"
CHAT_MESSAGES_TABLE = "chat_messages"
CHAT_ATTACHMENTS_TABLE = "chat_attachments"
CHAT_MESSAGE_ASSET_REFS_TABLE = "chat_message_asset_refs"
CHAT_MESSAGE_CODE_DELEGATION_REFS_TABLE = "chat_message_code_delegation_refs"
CHAT_CODE_DELEGATION_ARTIFACTS_TABLE = "chat_code_delegation_artifacts"
CHAT_CONTEXT_SUMMARIES_TABLE = "chat_context_summaries"
CHAT_CONTEXT_USAGE_SNAPSHOTS_TABLE = "chat_context_usage_snapshots"
CHAT_RUN_CONSUMED_EVENTS_TABLE = "chat_run_consumed_events"
CHAT_USER_TURN_DELIVERY_TABLE = "chat_user_turn_delivery"
CHAT_ASSISTANT_MEMORY_OUTBOX_TABLE = "chat_assistant_memory_outbox"
CHAT_GLOBAL_CLEAR_INTENT_TABLE = "chat_global_clear_intent"
CHAT_WORKSPACE_SESSION_CLEANUP_TABLE = "chat_workspace_session_cleanup"
CHAT_CLEARED_SESSION_SCOPES_TABLE = "chat_cleared_session_scopes"
CHAT_CLEARED_MESSAGE_SCOPES_TABLE = "chat_cleared_message_scopes"
