"""Lexical retrieval through the event repository boundary."""

from __future__ import annotations

from typing import List, Protocol, Tuple, cast

from ..ports import MemoryEventRepository
from ...event_contracts import MemoryEvent
from .search_text import get_search_text


class _L1EventFtsHostProtocol(Protocol):
    event_repository: MemoryEventRepository

    async def initialize(self) -> None: ...


class L1EventFtsMixin:
    """Query and rebuild the lexical index owned by the event repository."""

    async def bm25_search(
        self,
        query: str,
        *,
        limit: int = 20,
        user_id: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        strict: bool = False,
        l1_retrieval_scopes: list[str] | None = None,
    ) -> List[Tuple[str, float]]:
        host = cast(_L1EventFtsHostProtocol, self)
        await host.initialize()
        return await host.event_repository.bm25_search(query, limit=limit, user_id=user_id, start_time=start_time, end_time=end_time, strict=strict, l1_retrieval_scopes=l1_retrieval_scopes)

    async def backfill_fts(self, *, batch_size: int = 500) -> int:
        host = cast(_L1EventFtsHostProtocol, self)
        await host.initialize()
        return await host.event_repository.backfill_fts(batch_size=batch_size)

    def get_search_text(self, event: MemoryEvent) -> str:
        return get_search_text(event)
