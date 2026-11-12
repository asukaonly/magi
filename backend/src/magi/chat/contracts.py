"""Typed contracts for the dedicated chat domain store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi_plugin_sdk.storage_models.chat import (
    CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL,
    CHAT_DELIVERY_STATES,
    CHAT_RECOVERABLE_DELIVERY_STATES,
    ChatSessionRecord,
    ChatTurnRecord,
    ChatMessageRecord,
    ChatAssistantMemoryProjection,
    ChatAssistantMemoryOutboxRecord,
    CreateUserTurnResult,
    ChatUserTurnDeliveryRecord,
    ChatContextSummaryRecord,
    ChatContextUsageSnapshot,
    ChatReplyPreview,
    ChatMessageLabel,
    ChatDeliveryFailureFinalization,
)
