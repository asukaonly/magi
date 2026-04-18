"""Async user-profile service backed by L2 cognition stores.

Provides display-name and preference lookups that the prompt assembler
injects into context.  Falls back to safe defaults when L2 is unavailable
or the user entity does not exist yet.

Results are cached per user_id with a configurable TTL to avoid redundant
SQLite round-trips during prompt assembly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict

from ..core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CACHE_TTL = 300  # 5 minutes


@dataclass
class _CacheEntry:
    display_name: str = "unknown"
    preferences: Dict[str, Any] = field(default_factory=dict)
    fetched_at: float = 0.0


class UserProfileService:
    """Thin async facade over L2 entity catalog + ToM snapshots.

    Maintains a lightweight in-memory TTL cache keyed by ``user_id`` so that
    repeated calls within the same prompt-assembly cycle (or across
    back-to-back messages) do not issue duplicate DB queries.
    """

    def __init__(self, unified_memory=None, cache_ttl: float = _DEFAULT_CACHE_TTL):
        self._unified_memory = unified_memory
        self._cache_ttl = cache_ttl
        self._cache: Dict[str, _CacheEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_display_name(self, user_id: str) -> str:
        """Return the canonical display name for *user_id* from L2 entity catalog."""
        entry = await self._get_cached(user_id)
        return entry.display_name

    async def get_preference_summary(self, user_id: str) -> Dict[str, Any]:
        """Return aggregated user preferences from L2 ToM snapshot."""
        entry = await self._get_cached(user_id)
        return dict(entry.preferences)

    def invalidate(self, user_id: str | None = None) -> None:
        """Drop cached data for *user_id*, or all entries if ``None``."""
        if user_id is None:
            self._cache.clear()
        else:
            self._cache.pop(user_id, None)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_cached(self, user_id: str) -> _CacheEntry:
        """Return a cache entry, fetching from L2 if stale or missing."""
        if not user_id:
            return _CacheEntry()

        now = time.monotonic()
        entry = self._cache.get(user_id)
        if entry is not None and (now - entry.fetched_at) < self._cache_ttl:
            return entry

        entry = _CacheEntry(fetched_at=now)
        entry.display_name = await self._fetch_display_name(user_id)
        entry.preferences = await self._fetch_preferences(user_id)
        self._cache[user_id] = entry
        return entry

    async def _fetch_display_name(self, user_id: str) -> str:
        if self._unified_memory is None:
            return "unknown"

        catalog = getattr(self._unified_memory, "l2_entity_catalog", None)
        if catalog is None:
            return "unknown"

        entity_id = f"user:{user_id}"
        try:
            entities = await catalog.list_entities(entity_ids=[entity_id])
            if entities:
                name = entities[0].get("canonical_name", "")
                if name:
                    return name
        except Exception:
            logger.debug("Failed to look up display name for %s", user_id)

        return "unknown"

    async def _fetch_preferences(self, user_id: str) -> Dict[str, Any]:
        if self._unified_memory is None:
            return {}

        l2 = getattr(self._unified_memory, "l2", None)
        if l2 is None:
            return {}

        entity_id = f"user:{user_id}"
        try:
            snapshot = await l2.get_tom_snapshot(
                entity_id=entity_id,
                entity_type="user",
            )
            if snapshot is not None:
                return dict(snapshot.get("preferences", {}) or {})
        except Exception:
            logger.debug("Failed to get preference summary for %s", user_id)

        return {}
