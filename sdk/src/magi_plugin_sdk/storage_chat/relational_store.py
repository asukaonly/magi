"""Relational persistence composition for the chat domain."""

from __future__ import annotations

import logging
from typing import Callable


from .host import ChatStorageHost
from magi_plugin_sdk.storage_chat.relational import ChatDatabase, ChatRow
from magi_plugin_sdk.storage_chat.statements import ChatSql
from magi_plugin_sdk.storage_chat.ownership import ChatOwnershipPersistenceMixin
from magi_plugin_sdk.storage_chat.assistant_memory_outbox import ChatAssistantMemoryOutboxPersistenceMixin
from magi_plugin_sdk.storage_chat.attachments import ChatAttachmentPersistenceMixin
from magi_plugin_sdk.storage_chat.context_summaries import ChatContextSummaryPersistenceMixin
from magi_plugin_sdk.storage_chat.delivery_failures import ChatDeliveryFailurePersistenceMixin
from magi_plugin_sdk.storage_chat.delivery_outcomes import ChatDeliveryOutcomePersistenceMixin
from magi_plugin_sdk.storage_chat.messages import ChatMessagePersistenceMixin
from magi_plugin_sdk.storage_chat.post_turn_outbox import ChatPostTurnOutboxMixin
from magi_plugin_sdk.storage_chat.outbound_delivery import ChatOutboundDeliveryMixin
from magi_plugin_sdk.storage_chat.model_context import ChatModelContextPersistenceMixin
from magi_plugin_sdk.storage_chat.sessions import ChatSessionPersistenceMixin
from magi_plugin_sdk.storage_chat.task_execution_budgets import ChatTaskExecutionBudgetPersistenceMixin
from magi_plugin_sdk.storage_chat.turns import ChatTurnPersistenceMixin
from magi_plugin_sdk.storage_chat.user_turn_delivery import ChatUserTurnDeliveryPersistenceMixin


logger = logging.getLogger(__name__)


class RelationalChatRepository(
    ChatOwnershipPersistenceMixin,
    ChatAttachmentPersistenceMixin,
    ChatAssistantMemoryOutboxPersistenceMixin,
    ChatContextSummaryPersistenceMixin,
    ChatDeliveryFailurePersistenceMixin,
    ChatDeliveryOutcomePersistenceMixin,
    ChatMessagePersistenceMixin,
    ChatPostTurnOutboxMixin,
    ChatOutboundDeliveryMixin,
    ChatModelContextPersistenceMixin,
    ChatSessionPersistenceMixin,
    ChatTaskExecutionBudgetPersistenceMixin,
    ChatTurnPersistenceMixin,
    ChatUserTurnDeliveryPersistenceMixin,
):
    """Compose chat persistence capabilities and own their lifecycle."""

    def __init__(self, *, database: ChatDatabase, host: ChatStorageHost) -> None:
        self.database = database
        self.host = host
        self._initialized = False
        self._assistant_memory_outbox_waker: Callable[[], None] | None = None

    async def initialize(self) -> None:
        """Open storage owned by the composition root."""
        if not self._initialized:
            await self.database.initialize()
            self._initialized = True

    async def shutdown(self) -> None:
        """Reset the repository without closing a shared database owner."""
        self._initialized = False

    def set_assistant_memory_outbox_waker(
        self,
        waker: Callable[[], None] | None,
    ) -> None:
        """Bind the optional process-local wake hint for durable outbox work."""

        self._assistant_memory_outbox_waker = waker

    def _notify_assistant_memory_outbox(self) -> None:
        waker = self._assistant_memory_outbox_waker
        if waker is None:
            return
        try:
            waker()
        except Exception:
            logger.exception("Assistant-memory outbox wake failed")

    async def is_empty(self) -> bool:
        """Return whether the chat store has any durable rows."""
        await self.initialize()
        async with self.database.session() as db:
            for table in ("chat_sessions", "chat_turns", "chat_messages"):
                cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                if row is not None and int(row[0] or 0) > 0:
                    return False
        return True

    async def _fetchone(
        self,
        sql: str | ChatSql,
        params: tuple[object, ...],
    ) -> ChatRow | None:
        await self.initialize()
        async with self.database.session() as db:
            cur = await db.execute(sql, params)
            return await cur.fetchone()
