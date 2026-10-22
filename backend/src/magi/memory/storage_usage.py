"""Optional complete database-footprint measurement for the selected memory owners."""

from typing import Protocol


class MemoryStorageUsage(Protocol):
    async def measure_bytes(self) -> int | None:
        """Return the complete selected database footprint, or None when unknown."""
        ...
