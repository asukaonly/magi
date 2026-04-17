"""Async user-profile service backed by L2 cognition stores.

Provides display-name and preference lookups that the prompt assembler
injects into context.  Falls back to safe defaults when L2 is unavailable
or the user entity does not exist yet.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.logger import get_logger

logger = get_logger(__name__)


class UserProfileService:
    """Thin async facade over L2 entity catalog + ToM snapshots."""

    def __init__(self, unified_memory=None):
        self._unified_memory = unified_memory

    async def get_display_name(self, user_id: str) -> str:
        """Return the canonical display name for *user_id* from L2 entity catalog."""
        if not user_id or self._unified_memory is None:
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

    async def get_preference_summary(self, user_id: str) -> Dict[str, Any]:
        """Return aggregated user preferences from L2 ToM snapshot."""
        if not user_id or self._unified_memory is None:
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
