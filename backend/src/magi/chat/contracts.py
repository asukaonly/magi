"""Typed contracts for the dedicated chat domain store."""

from __future__ import annotations

from magi_plugin_sdk.storage_models.chat import (
    CHAT_DELIVERY_STATE_READY as CHAT_DELIVERY_STATE_READY,
    CHAT_DELIVERY_STATE_QUEUED as CHAT_DELIVERY_STATE_QUEUED,
    CHAT_DELIVERY_STATE_ADMITTED as CHAT_DELIVERY_STATE_ADMITTED,
    CHAT_DELIVERY_STATE_TERMINAL as CHAT_DELIVERY_STATE_TERMINAL,
    CHAT_DELIVERY_STATES as CHAT_DELIVERY_STATES,
    CHAT_RECOVERABLE_DELIVERY_STATES as CHAT_RECOVERABLE_DELIVERY_STATES,
    ChatSessionRecord as ChatSessionRecord,
    ChatTurnRecord as ChatTurnRecord,
    ChatMessageRecord as ChatMessageRecord,
    ChatAssistantMemoryProjection as ChatAssistantMemoryProjection,
    ChatAssistantMemoryOutboxRecord as ChatAssistantMemoryOutboxRecord,
    CreateUserTurnResult as CreateUserTurnResult,
    ChatUserTurnDeliveryRecord as ChatUserTurnDeliveryRecord,
    ChatContextSummaryRecord as ChatContextSummaryRecord,
    ChatContextUsageSnapshot as ChatContextUsageSnapshot,
    ChatReplyPreview as ChatReplyPreview,
    ChatMessageLabel as ChatMessageLabel,
    ChatDeliveryFailureFinalization as ChatDeliveryFailureFinalization,
)
