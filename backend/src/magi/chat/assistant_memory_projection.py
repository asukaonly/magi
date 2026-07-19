"""Durable delivery of committed assistant messages into L1 memory."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import time
from typing import Any, Protocol

from ..core.logger import get_logger
from ..events.events import EventTypes
from .contracts import ChatAssistantMemoryOutboxRecord
from .projector import CHAT_MEMORY_SOURCE, ChatProjector

logger = get_logger(__name__)


class _AssistantMemoryOutboxProtocol(Protocol):
    async def claim_assistant_memory_projections(
        self,
        *,
        limit: int,
        lease_seconds: float,
        now_ms: int | None = None,
    ) -> list[ChatAssistantMemoryOutboxRecord]: ...

    async def complete_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
        lease_token: str,
    ) -> bool: ...

    async def retry_assistant_memory_projection(
        self,
        *,
        canonical_message_id: str,
        lease_token: str,
        retry_delay_ms: int,
        error: str,
        now_ms: int | None = None,
    ) -> bool: ...


class ChatAssistantMemoryProjectionService:
    """Retry assistant-memory projection until L1 confirms the stable identity."""

    def __init__(
        self,
        *,
        outbox: _AssistantMemoryOutboxProtocol,
        projector: ChatProjector,
        unified_memory: Any,
        retry_interval_seconds: float = 5.0,
        confirmation_timeout_seconds: float = 1.0,
        confirmation_poll_seconds: float = 0.02,
        lease_seconds: float = 30.0,
        page_size: int = 20,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
    ) -> None:
        self._outbox = outbox
        self._projector = projector
        self._unified_memory = unified_memory
        self._retry_interval_seconds = max(0.05, float(retry_interval_seconds))
        self._confirmation_timeout_seconds = max(
            0.01,
            float(confirmation_timeout_seconds),
        )
        self._confirmation_poll_seconds = max(
            0.001,
            float(confirmation_poll_seconds),
        )
        self._lease_seconds = max(1.0, float(lease_seconds))
        self._page_size = max(1, min(int(page_size), 100))
        self._retry_base_seconds = max(0.01, float(retry_base_seconds))
        self._retry_max_seconds = max(
            self._retry_base_seconds,
            float(retry_max_seconds),
        )
        self._wake_event = asyncio.Event()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start startup recovery and periodic retry processing."""

        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="chat-assistant-memory-projection",
        )
        self.wake()

    async def stop(self) -> None:
        """Stop processing; owned leases become recoverable after expiry."""

        self._stop_event.set()
        self.wake()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def wake(self) -> None:
        """Hint that newly committed projection work is ready."""

        self._wake_event.set()

    async def process_ready_once(self) -> dict[str, int]:
        """Process one leased page for tests and controlled maintenance."""

        rows = await self._outbox.claim_assistant_memory_projections(
            limit=self._page_size,
            lease_seconds=self._lease_seconds,
        )
        stats = {
            "claimed": len(rows),
            "confirmed": 0,
            "disabled": 0,
            "retried": 0,
            "cancelled": 0,
        }
        for row in rows:
            outcome = await self._process_claimed(row)
            stats[outcome] += 1
        return stats

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                while not self._stop_event.is_set():
                    stats = await self.process_ready_once()
                    if stats["claimed"] < self._page_size:
                        break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Assistant-memory projection recovery failed")

            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self._retry_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass
            finally:
                self._wake_event.clear()

    async def _process_claimed(
        self,
        row: ChatAssistantMemoryOutboxRecord,
    ) -> str:
        projection = row.projection
        try:
            async with self._unified_memory.memory_operation_guard():
                l1_store = self._unified_memory.l1
                if l1_store is None:
                    completed = await self._complete(row)
                    return "disabled" if completed else "cancelled"

                finder = l1_store.find_event_id_by_idempotency
                if await self._find_projection(finder, projection.canonical_message_id):
                    completed = await self._complete(row)
                    return "confirmed" if completed else "cancelled"

                await self._projector.project_assistant_message(
                    message_id=projection.canonical_message_id,
                    user_id=projection.user_id,
                    session_id=projection.session_id,
                    turn_id=projection.turn_id,
                    content=projection.content,
                    created_at_ms=projection.created_at_ms,
                )
                if await self._wait_for_confirmation(
                    finder,
                    projection.canonical_message_id,
                ):
                    completed = await self._complete(row)
                    return "confirmed" if completed else "cancelled"
                raise TimeoutError("L1 did not confirm assistant-memory projection")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            retry_delay_ms = int(
                min(
                    self._retry_max_seconds,
                    self._retry_base_seconds
                    * (2 ** min(max(0, row.attempt_count - 1), 16)),
                )
                * 1000
            )
            retained = await self._outbox.retry_assistant_memory_projection(
                canonical_message_id=projection.canonical_message_id,
                lease_token=row.lease_token,
                retry_delay_ms=retry_delay_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
            if retained:
                logger.warning(
                    "Assistant-memory projection scheduled for retry",
                    message_id=projection.canonical_message_id,
                    attempt_count=row.attempt_count,
                    retry_delay_ms=retry_delay_ms,
                    error=str(exc),
                )
                return "retried"
            return "cancelled"

    async def _complete(self, row: ChatAssistantMemoryOutboxRecord) -> bool:
        return await self._outbox.complete_assistant_memory_projection(
            canonical_message_id=row.projection.canonical_message_id,
            lease_token=row.lease_token,
        )

    async def _wait_for_confirmation(
        self,
        finder: Any,
        canonical_message_id: str,
    ) -> bool:
        deadline = time.monotonic() + self._confirmation_timeout_seconds
        while True:
            if await self._find_projection(finder, canonical_message_id):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self._confirmation_poll_seconds)

    @staticmethod
    async def _find_projection(finder: Any, canonical_message_id: str) -> bool:
        return (
            await finder(
                source=CHAT_MEMORY_SOURCE,
                event_type=EventTypes.AI_RESPONSE,
                idempotency_key=canonical_message_id,
            )
            is not None
        )


__all__ = ["ChatAssistantMemoryProjectionService"]
