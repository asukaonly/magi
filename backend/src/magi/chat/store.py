"""SQLite-backed persistence composition for the chat domain."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from ..utils.runtime import RuntimePaths, get_runtime_paths
from .storage.assistant_memory_outbox import (
    ChatAssistantMemoryOutboxPersistenceMixin,
)
from .storage.attachments import ChatAttachmentPersistenceMixin
from .storage.context_summaries import ChatContextSummaryPersistenceMixin
from .storage.delivery_failures import ChatDeliveryFailurePersistenceMixin
from .storage.delivery_outcomes import ChatDeliveryOutcomePersistenceMixin
from .storage.messages import ChatMessagePersistenceMixin
from .storage.sessions import ChatSessionPersistenceMixin
from .storage.task_execution_budgets import (
    ChatTaskExecutionBudgetPersistenceMixin,
)
from .storage.turns import ChatTurnPersistenceMixin
from .storage.user_turn_delivery import (
    ChatTurnConflictError,
    ChatUserTurnDeliveryPersistenceMixin,
)


logger = logging.getLogger(__name__)


class ChatStore(
    ChatAttachmentPersistenceMixin,
    ChatAssistantMemoryOutboxPersistenceMixin,
    ChatContextSummaryPersistenceMixin,
    ChatDeliveryFailurePersistenceMixin,
    ChatDeliveryOutcomePersistenceMixin,
    ChatMessagePersistenceMixin,
    ChatSessionPersistenceMixin,
    ChatTaskExecutionBudgetPersistenceMixin,
    ChatTurnPersistenceMixin,
    ChatUserTurnDeliveryPersistenceMixin,
):
    """Compose chat persistence capabilities and own their lifecycle."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/chat/chat.db",
        runtime_paths: RuntimePaths | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._runtime_paths = runtime_paths or _runtime_paths_for_chat_db(
            self.db_path
        )
        self._initialized = False
        self._assistant_memory_outbox_waker: Callable[[], None] | None = None

    async def initialize(self) -> None:
        """Create the chat-domain schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            await db.commit()
        self._initialized = True

    async def shutdown(self) -> None:
        """Reset initialization state."""
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
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            for table in ("chat_sessions", "chat_turns", "chat_messages"):
                cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                if row is not None and int(row[0] or 0) > 0:
                    return False
        return True

    async def _fetchone(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> aiosqlite.Row | None:
        await self.initialize()
        async with sqlite_connection_async(self.db_path, profile="mixed") as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return await cur.fetchone()


def _runtime_paths_for_chat_db(db_path: str) -> RuntimePaths:
    """Use the owning standard runtime tree when the chat DB path identifies it."""

    expanded = Path(db_path).expanduser().absolute()
    if (
        expanded.name == "chat.db"
        and expanded.parent.name == "chat"
        and expanded.parent.parent.name == "data"
    ):
        return RuntimePaths(base_dir=expanded.parents[2])
    return get_runtime_paths()


__all__ = ["ChatStore", "ChatTurnConflictError"]
