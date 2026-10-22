"""Memory-owned asset visibility contracts."""

from typing import Protocol


class AssetReferenceRepository(Protocol):
    async def is_visible_reference(self, asset_ref: str) -> bool: ...
