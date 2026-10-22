"""Relational persistence composition for the chat domain."""

from __future__ import annotations

import logging
from typing import Callable


from ...utils.runtime import RuntimePaths
from .relational import ChatDatabase, ChatRow
from .statements import ChatSql
from .ownership import ChatOwnershipPersistenceMixin
from .assistant_memory_outbox import (
    ChatAssistantMemoryOutboxPersistenceMixin,
)
from .attachments import ChatAttachmentPersistenceMixin
from .context_summaries import ChatContextSummaryPersistenceMixin
from .delivery_failures import ChatDeliveryFailurePersistenceMixin
from .delivery_outcomes import ChatDeliveryOutcomePersistenceMixin
from .messages import ChatMessagePersistenceMixin
from .post_turn_outbox import ChatPostTurnOutboxMixin
from .outbound_delivery import ChatOutboundDeliveryMixin
from .model_context import ChatModelContextPersistenceMixin
from .sessions import ChatSessionPersistenceMixin
from .task_execution_budgets import (
    ChatTaskExecutionBudgetPersistenceMixin,
)
from .turns import ChatTurnPersistenceMixin
from .user_turn_delivery import (
    ChatUserTurnDeliveryPersistenceMixin,
)


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

    def __init__(self, *, database: ChatDatabase, runtime_paths: RuntimePaths) -> None:
        self.database = database
        self._runtime_paths = runtime_paths
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

