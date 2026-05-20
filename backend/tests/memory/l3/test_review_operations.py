"""Unit tests for L3 review-state operations."""

from __future__ import annotations

import pytest

from magi.memory.l3.models import L3Candidate
from magi.memory.l3.summary_store import L3SummaryStore


@pytest.fixture
async def store(tmp_path):
    db_path = str(tmp_path / "l3.db")
    s = L3SummaryStore(db_path=db_path, vector_enabled=False)
    await s.initialize()
    return s


async def _insert_summary(
    store: L3SummaryStore,
    summary_id: str,
    review_state: str = "neutral",
) -> None:
    """Insert a minimal summary row via upsert_candidate with a fixed summary_id."""
    candidate = L3Candidate(
        content="test content",
        source_event_ids=["evt-test"],
        summary_category="state_change",
        summary_type="insight",
        review_state=review_state,
    )
    await store.upsert_candidate(
        candidate=candidate,
        summary_overrides={
            "summary_id": summary_id,
            "period_start": 0.0,
            "period_end": 1.0,
        },
    )


@pytest.mark.asyncio
async def test_set_review_state_updates_row(store):
    await _insert_summary(store, "sum-1", review_state="pending_confirmation")
    ok = await store.set_review_state(
        summary_id="sum-1", review_state="confirmed", user_note=None
    )
    assert ok is True
    row = await store.get_summary_by_id("sum-1")
    assert row is not None
    assert row["review_state"] == "confirmed"


@pytest.mark.asyncio
async def test_set_review_state_returns_false_for_unknown_id(store):
    ok = await store.set_review_state(
        summary_id="nope", review_state="confirmed", user_note=None
    )
    assert ok is False


@pytest.mark.asyncio
async def test_set_review_state_persists_user_note(store):
    await _insert_summary(store, "sum-2")
    await store.set_review_state(
        summary_id="sum-2", review_state="confirmed", user_note="me too"
    )
    row = await store.get_summary_by_id("sum-2")
    assert row is not None
    assert (row.get("insight_metadata") or {}).get("user_note") == "me too"


@pytest.mark.asyncio
async def test_set_review_state_raises_for_invalid_state(store):
    await _insert_summary(store, "sum-3")
    with pytest.raises(ValueError, match="invalid review_state"):
        await store.set_review_state(
            summary_id="sum-3", review_state="bogus", user_note=None
        )


@pytest.mark.asyncio
async def test_get_summary_by_id_returns_none_for_missing(store):
    result = await store.get_summary_by_id("does-not-exist")
    assert result is None
