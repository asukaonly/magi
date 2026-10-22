"""Memory-facing lifecycle for durable cognition handoffs."""

import time
from .ports import MemoryEventRepository


class L1CognitionHandoffMixin:
    event_repository: MemoryEventRepository

    async def list_ready_cognition_handoffs(self, *, limit: int = 100) -> list[str]:
        return await self.event_repository.list_ready_cognition_handoffs(now=time.time(), limit=limit)

    async def complete_cognition_handoff(self, event_id: str) -> None:
        await self.event_repository.complete_cognition_handoff(event_id)

    async def retry_cognition_handoff(self, event_id: str, *, error: str) -> None:
        await self.event_repository.retry_cognition_handoff(event_id, error=error, now=time.time())
