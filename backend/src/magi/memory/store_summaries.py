"""L3 summary generation helpers for the unified memory store."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional


class UnifiedMemorySummaryMixin:
    """Generate temporal and thematic L3 summaries through the unified store."""

    l1: Any
    l3: Any
    _summary_semaphore: Any

    async def generate_summary(
        self,
        period_type: str = "day",
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        summary_category: Optional[str] = None,
        source_filter: Optional[list[str]] = None,
        min_events: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Generate a temporal L3 summary for a time window."""
        if self.l1 is None or self.l3 is None:
            return None

        now = time.time()
        if period_end is None:
            period_end = now
        if period_start is None:
            period_start = period_end - self._period_seconds(period_type)
        async with self._summary_semaphore:
            return await self.l3.generate_temporal_summary(
                l1_store=self.l1,
                summary_category=summary_category or period_type,
                period_start=period_start,
                period_end=period_end,
                source_filter=source_filter,
                min_events=min_events,
            )

    async def generate_source_activity_summary(
        self,
        *,
        summary_category: str,
        source_filter: list[str],
        period_type: str = "day",
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        min_events: int = 4,
    ) -> Optional[Dict[str, Any]]:
        """Generate an L3 activity summary scoped to one or more sensor sources."""
        return await self.generate_summary(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
            summary_category=summary_category,
            source_filter=source_filter,
            min_events=min_events,
        )

    async def generate_thematic_summary(
        self,
        *,
        topic: str,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        min_source_count: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Generate a topic-oriented thematic L3 summary."""
        if self.l1 is None or self.l3 is None:
            return None
        return await self.l3.generate_thematic_summary(
            l1_store=self.l1,
            topic=topic,
            period_start=period_start,
            period_end=period_end,
            min_source_count=min_source_count,
        )

    def _period_seconds(self, period_type: str) -> int:
        return {
            "hour": 60 * 60,
            "day": 24 * 60 * 60,
            "week": 7 * 24 * 60 * 60,
            "month": 30 * 24 * 60 * 60,
        }.get(period_type, 24 * 60 * 60)


__all__ = ["UnifiedMemorySummaryMixin"]
