"""L3 summary generation helpers for the unified memory store."""

from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple


def _period_bounds(period_type: str, ts: float) -> Tuple[float, float]:
    """Return ``[start, end)`` for the period containing ``ts`` (local time)."""
    dt = datetime.datetime.fromtimestamp(ts)
    if period_type == "day":
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), (start + datetime.timedelta(days=1)).timestamp()
    if period_type == "week":  # ISO week, Monday start
        monday = (dt - datetime.timedelta(days=dt.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return monday.timestamp(), (monday + datetime.timedelta(days=7)).timestamp()
    raise ValueError(f"unsupported period_type for backfill: {period_type}")


def _enumerate_closed_periods(
    period_type: str,
    range_start: float,
    range_end: float,
    now: float,
) -> List[Tuple[float, float]]:
    """All ``[pstart, pend)`` of ``period_type`` overlapping ``[range_start, range_end]``
    that are fully CLOSED (``pend <= start of the current period``).

    The current (still-open) period is intentionally excluded — it is owned by the
    recurring scheduler, never by the backfill.
    """
    cur_start, _ = _period_bounds(period_type, now)
    out: List[Tuple[float, float]] = []
    cursor = _period_bounds(period_type, range_start)[0]
    while cursor < range_end:
        pstart, pend = _period_bounds(period_type, cursor)
        if pend <= cur_start:  # strictly past, already closed
            out.append((pstart, pend))
        cursor = pend + 1  # +1s to step robustly into the next period (DST-safe)
    return out


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
        async with self.memory_operation_guard():  # type: ignore[attr-defined]
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

    async def backfill_l3_gaps(
        self,
        *,
        range_start: float,
        range_end: float,
        period_types: Tuple[str, ...] = ("day", "week"),
        min_events: int = 3,
        max_periods: int = 60,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Idempotently summarize CLOSED past periods (day/week) that have L1 events
        but no L3 summary.

        This fills the historical "Stories" gap left by the recurring scheduler, which
        only ever summarizes a trailing ``[now - period, now]`` window. It does NOT
        touch the recurring scheduler or the current (still-open) period.

        Idempotency: gap-checked against existing summaries via
        ``list_summaries_by_category`` — re-runs (e.g. after a re-import) add no
        duplicates. Sparse periods (fewer than ``min_events`` L1 events) are skipped.
        """
        result: Dict[str, Any] = {
            "generated": [],
            "skipped_existing": 0,
            "skipped_sparse": 0,
        }
        if self.l1 is None or self.l3 is None:
            return result
        now = now if now is not None else time.time()

        for period_type in period_types:
            periods = _enumerate_closed_periods(
                period_type, range_start, range_end, now
            )
            if len(periods) > max_periods:
                periods = periods[-max_periods:]  # cap cost; keep the newest gaps

            existing = await self.l3.list_summaries_by_category(
                summary_categories=[period_type],
                period_start=range_start,
                period_end=range_end,
                limit=10_000,
            )
            existing_starts = {
                _period_bounds(period_type, float(s["period_start"]))[0]
                for s in existing
            }

            for pstart, pend in periods:
                if pstart in existing_starts:
                    result["skipped_existing"] += 1
                    continue
                count = await self.l1.count_events(start_time=pstart, end_time=pend)
                if count < min_events:
                    result["skipped_sparse"] += 1
                    continue
                summary = await self.generate_summary(
                    period_type=period_type,
                    period_start=pstart,
                    period_end=pend,
                    summary_category=period_type,
                    min_events=min_events,
                )
                if summary is not None:
                    result["generated"].append((period_type, pstart))
                    existing_starts.add(pstart)
        return result

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
        async with self.memory_operation_guard():  # type: ignore[attr-defined]
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
