"""Dedicated chat-domain persistence exports."""

from .attachment_storage import LocalChatAttachmentStorage, StoredChatAttachment
from .contracts import ChatMessageRecord, ChatSessionRecord, ChatTurnRecord
from .pdf_attachment_parser import LocalPdfAttachmentParser, ParsedPdfAttachment
from .projector import ChatProjector
from .read_service import (
    ChatDisplayMessage,
    ChatReadService,
    ChatSessionRenameResult,
    ChatSessionSummary,
    SessionWorkspaceUpdateResult,
    get_chat_read_service,
)
from .store import ChatStore
from .text_attachment_parser import LocalTextAttachmentParser, ParsedTextAttachment

__all__ = [
    "ChatDisplayMessage",
    "ChatMessageRecord",
    "ChatProjector",
    "ChatReadService",
    "ChatSessionRecord",
    "ChatSessionRenameResult",
    "ChatSessionSummary",
    "LocalChatAttachmentStorage",
    "LocalPdfAttachmentParser",
    "LocalTextAttachmentParser",
    "ParsedPdfAttachment",
    "ParsedTextAttachment",
    "SessionWorkspaceUpdateResult",
    "StoredChatAttachment",
    "ChatStore",
    "ChatTurnRecord",
    "get_chat_read_service",
]
