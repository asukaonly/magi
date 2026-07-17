"""Timeline view projection helpers for L1 event retrieval."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

from ...evidence import USER_VISIBLE_L1_RETRIEVAL_SCOPES
from .common import L1EventQueryHostProtocol


class L1TimelineQueryMixin:
    """Project canonical L1 events into timeline-shaped views."""

    async def get_timeline_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Return a minimal timeline-shaped view from canonical L1 columns."""
        host = cast(L1EventQueryHostProtocol, self)
        event = await host.get_user_visible_event(event_id)
        return host._to_timeline_view(event)

    async def list_timeline_events(
        self, *, limit: int = 100, source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List timeline-shaped views with optional source filtering."""
        host = cast(L1EventQueryHostProtocol, self)
        events = await host.query_events(
            limit=max(limit * 10, limit),
            l1_retrieval_scopes=list(USER_VISIBLE_L1_RETRIEVAL_SCOPES),
        )
        items: List[Dict[str, Any]] = []
        for event in events:
            item = host._to_timeline_view(event)
            if item is None:
                continue
            if source_type and item["source_type"] != source_type:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items


__all__ = ["L1TimelineQueryMixin"]
