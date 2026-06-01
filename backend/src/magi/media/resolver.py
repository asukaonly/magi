"""Asset reference resolver.

Placeholder for the `asset_resolve` tool described in
`docs/unified-asset-resolver-architecture.md` (status: Proposed). The
class shape and interface stub here ensure callers can wire imports
without waiting for that proposal to land; raising NotImplementedError
keeps surprises out of production code paths.
"""

from __future__ import annotations

from typing import Any, Mapping


class AssetResolver:
    """Resolve an asset_ref into source-specific evidence.

    Resolution is delegated to source-owned hooks once the unified-asset
    proposal lands. For Plan 1, callers should treat any reference as
    opaque: store it, surface it as an identifier, never try to resolve.
    """

    def __init__(self) -> None:
        self._unimplemented = True

    async def resolve(self, *, asset_ref: str, scope: Mapping[str, Any] | None = None) -> Any:
        raise NotImplementedError(
            "AssetResolver is a forward-compatible placeholder; "
            "implement when unified-asset-resolver lands."
        )
