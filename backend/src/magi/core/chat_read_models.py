"""Shared chat read DTOs and outcomes used by API and domain services."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.chat_reads import (
    ChatAttachmentLocation as ChatAttachmentLocation,
    ChatSessionSummary as ChatSessionSummary,
    ChatSessionRenameResult as ChatSessionRenameResult,
    SessionWorkspaceUpdateResult as SessionWorkspaceUpdateResult,
    ChatMessageSourceIdentity as ChatMessageSourceIdentity,
    ChatDisplayMessage as ChatDisplayMessage,
    _format_prompt_attachment_references as _format_prompt_attachment_references,
    InvalidPageCursor as InvalidPageCursor,
    StalePageCursor as StalePageCursor,
)
