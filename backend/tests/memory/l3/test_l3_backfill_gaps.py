"""Tests for the idempotent L3 historical gap backfill (``backfill_l3_gaps``).

These exercise the summaries-mixin contract:
  * fill CLOSED past day/week periods that have >= min_events L1 events but no
    existing L3 summary,
  * be idempotent (re-running adds no duplicates — gap-checked via
    ``list_summaries_by_category``),
  * skip sparse periods,
  * never touch the current (still-open) period.

The temporal LLM is stubbed exactly like the existing L3 tests
(``test_summary_store.py``): patch ``L3SummaryStore._temporal_llm_service`` prose
and structure calls so ``generate_temporal_summary`` produces a deterministic
candidate with no network call.
"""

from __future__ import annotations

import asyncio
import datetime
import time
from contextlib import asynccontextmanager

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.store_summaries import UnifiedMemorySummaryMixin


def _day_start(ts: float) -> float:
    """Midnight-aligned (local) day start — mirrors the impl's ``_period_bounds('day')``."""
    d = datetime.datetime.fromtimestamp(ts).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return d.timestamp()


class _MixinHost(UnifiedMemorySummaryMixin):
    """Minimal host exposing the attributes the summaries mixin relies on."""

    def __init__(self, l1, l3) -> None:
        self.l1 = l1
        self.l3 = l3
        self._summary_semaphore = asyncio.Semaphore(3)

    @asynccontextmanager
    async def memory_operation_guard(self):  # type: ignore[no-untyped-def]
        yield


def _event(*, ts: float, source: str, content: str, event_id: str):
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={"user_id": "u1", "session_id": "s1", "content": content},
            source=source,
            level=EventLevel.INFO,
            correlation_id=event_id,
            timestamp=ts,
            event_id=event_id,
        ),
    )


@pytest.fixture
async def unified_with_stubbed_l3_llm(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """A summaries-mixin host wired to real L1 + L3 stores with the temporal LLM stubbed."""
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l3.summary_store import L3SummaryStore

    l1 = L1EventStore(db_path=str(tmp_path / "l1_events.db"), vector_enabled=False)
    l3 = L3SummaryStore(db_path=str(tmp_path / "memory.db"), vector_enabled=False)
    await l1.initialize()
    await l3.initialize()

    async def _fake_prose_model(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "Deterministic backfill summary"

    async def _fake_structure_model(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "Deterministic backfill summary"
        return {
            "key_topics": ["browsing"],
            "importance_aggregate": 0.6,
        }

    monkeypatch.setattr(l3._temporal_llm_service, "_call_temporal_prose_model", _fake_prose_model)
    monkeypatch.setattr(l3._temporal_llm_service, "_call_temporal_structure_model", _fake_structure_model)

    host = _MixinHost(l1, l3)
    try:
        yield host
    finally:
        await l3.shutdown()


@pytest.mark.asyncio
async def test_backfill_fills_closed_past_days_only(unified_with_stubbed_l3_llm):
    um = unified_with_stubbed_l3_llm
    now = _day_start(time.time())
    d1 = now - 3 * 86400  # 3 days ago (closed)
    d2 = now - 2 * 86400  # 2 days ago (closed)
    for day in (d1, d2):
        for i in range(3):
            await um.l1.store(
                _event(
                    ts=day + 3600 + i,
                    source="chrome_history",
                    content=f"visit {day}-{i}",
                    event_id=f"e-{int(day)}-{i}",
                )
            )

    res = await um.backfill_l3_gaps(
        range_start=d1,
        range_end=now + 86400,
        period_types=("day", "week"),
        min_events=3,
        now=time.time(),
    )

    day_starts = {ps for (pt, ps) in res["generated"] if pt == "day"}
    assert _day_start(d1) in day_starts
    assert _day_start(d2) in day_starts
    # the current (open) period is left to the scheduler
    assert _day_start(time.time()) not in day_starts

    existing = await um.l3.list_summaries_by_category(
        summary_categories=["day"], period_start=d1, period_end=now + 86400
    )
    assert len({s["period_start"] for s in existing}) >= 2


@pytest.mark.asyncio
async def test_backfill_is_idempotent(unified_with_stubbed_l3_llm):
    um = unified_with_stubbed_l3_llm
    now = _day_start(time.time())
    d1 = now - 2 * 86400
    for i in range(3):
        await um.l1.store(
            _event(
                ts=d1 + 3600 + i,
                source="chrome_history",
                content=f"visit {i}",
                event_id=f"idem-{i}",
            )
        )

    first = await um.backfill_l3_gaps(
        range_start=d1, range_end=now, min_events=3, now=time.time()
    )
    second = await um.backfill_l3_gaps(
        range_start=d1, range_end=now, min_events=3, now=time.time()
    )

    assert len(first["generated"]) >= 1
    assert second["generated"] == []  # already summarized → skipped, no duplicates
    assert second["skipped_existing"] >= 1


@pytest.mark.asyncio
async def test_backfill_skips_sparse_days(unified_with_stubbed_l3_llm):
    um = unified_with_stubbed_l3_llm
    now = _day_start(time.time())
    d1 = now - 2 * 86400
    await um.l1.store(
        _event(
            ts=d1 + 3600,
            source="chrome_history",
            content="lonely visit",
            event_id="sparse-0",
        )
    )  # only 1 event

    res = await um.backfill_l3_gaps(
        range_start=d1, range_end=now, min_events=3, now=time.time()
    )

    assert res["generated"] == []
    assert res["skipped_sparse"] >= 1
