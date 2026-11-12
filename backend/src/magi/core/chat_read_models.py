"""Shared chat read DTOs and outcomes used by API and domain services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi_plugin_sdk.storage_models.chat_reads import (
    ChatAttachmentLocation,
    ChatSessionSummary,
    ChatSessionRenameResult,
    SessionWorkspaceUpdateResult,
    ChatMessageSourceIdentity,
    ChatDisplayMessage,
    _format_prompt_attachment_references,
    InvalidPageCursor,
    StalePageCursor,
)
