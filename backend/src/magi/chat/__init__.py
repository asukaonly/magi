"""Dedicated chat-domain persistence exports."""

from .attachment_storage import LocalChatAttachmentStorage, StoredChatAttachment
from .asset_gc import ChatAssetGC
from .attachment_ingestion import LocalChatAttachmentIngestionService
from .contracts import (
    ChatAssistantMemoryOutboxRecord,
    ChatAssistantMemoryProjection,
    ChatContextSummaryRecord,
    ChatContextUsageSnapshot,
    ChatMessageLabel,
    ChatMessageRecord,
    ChatSessionRecord,
    ChatTurnRecord,
    ChatUserTurnDeliveryRecord,
)
from .pdf_attachment_parser import LocalPdfAttachmentParser, ParsedPdfAttachment
from .projector import ChatProjector
from .read_ports import ChatReadRepository
from .provider import get_chat_read_service
from ..core.chat_read_models import (
    ChatDisplayMessage, ChatSessionRenameResult, ChatSessionSummary, SessionWorkspaceUpdateResult,
)
from .ports import ChatRepository
from .text_attachment_parser import LocalTextAttachmentParser, ParsedTextAttachment

__all__ = [
    "ChatDisplayMessage",
    "ChatAssistantMemoryOutboxRecord",
    "ChatAssistantMemoryProjection",
    "ChatContextSummaryRecord",
    "ChatContextUsageSnapshot",
    "ChatMessageLabel",
    "ChatMessageRecord",
    "ChatProjector",
    "ChatAssetGC",
    "ChatReadRepository",
    "ChatSessionRecord",
    "ChatSessionRenameResult",
    "ChatSessionSummary",
    "LocalChatAttachmentIngestionService",
    "LocalChatAttachmentStorage",
    "LocalPdfAttachmentParser",
    "LocalTextAttachmentParser",
    "ParsedPdfAttachment",
    "ParsedTextAttachment",
    "SessionWorkspaceUpdateResult",
    "StoredChatAttachment",
    "ChatRepository",
    "ChatTurnRecord",
    "ChatUserTurnDeliveryRecord",
    "get_chat_read_service",
]
