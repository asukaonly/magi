"""Period-anchored representative asset selection."""

from __future__ import annotations

from typing import Optional, Sequence

from .source_registry import MediaSourceRegistry


class MediaSelector:
    """Given a time window, return a representative asset_ref or None.

    Plan 1 ships a simple priority-then-earliest policy. Plan 2 swaps the
    policy with a richer scorer (people-bearing > outdoor > time-of-day fit,
    plus existing user-pin signals).
    """

    def __init__(
        self,
        *,
        registry: MediaSourceRegistry,
        source_priority: Sequence[str] = ("photo-library", "chat-attachments"),
    ) -> None:
        self._registry = registry
        self._source_priority = tuple(source_priority)

    async def pick_representative(
        self,
        *,
        start: float,
        end: float,
        hint: str = "hero",
    ) -> Optional[str]:
        """Return a single asset_ref representing the window, or None.

        ``hint`` is reserved for future use (e.g., "thumbnail", "moodboard");
        the Plan 1 policy ignores it.
        """
        # Walk priority order, take earliest from the first source that has any.
        for source_id in self._source_priority:
            src = self._registry.get(source_id)
            if src is None:
                continue
            try:
                assets = await src.list_assets(start=start, end=end)
            except Exception:
                continue
            if not assets:
                continue
            assets_sorted = sorted(assets, key=lambda a: a.get("timestamp", 0.0))
            ref = (assets_sorted[0] or {}).get("ref")
            if ref:
                return str(ref)
        return None
