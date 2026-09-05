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


@pytest.mark.asyncio
async def test_rejected_summary_is_hidden_and_same_input_cannot_resurface(store):
    candidate = L3Candidate(
        content="A proposed observation", source_event_ids=["evt-review"],
        summary_category="state_change", summary_type="insight",
        review_state="pending_confirmation", insight_key="observation:one",
    )
    first = await store.upsert_candidate(candidate=candidate)
    await store.set_review_state(summary_id=first["summary_id"], review_state="rejected")
    assert await store.get_summary_by_id(first["summary_id"]) is None
    assert await store.list_summaries() == []
    assert await store.count_summaries() == 0
    repeated = await store.upsert_candidate(candidate=candidate)
    assert repeated["summary_id"] == first["summary_id"]
    assert repeated["review_state"] == "rejected"
    assert (await store.get_summary_by_id(first["summary_id"], include_rejected=True))["review_state"] == "rejected"
    assert len(await store.list_summary_event_links(first["summary_id"])) == 1
    candidate.source_event_ids.append("evt-new-evidence")
    revised = await store.upsert_candidate(candidate=candidate)
    assert revised["review_state"] == "pending_confirmation"
    assert await store.get_summary_by_id(revised["summary_id"]) is not None
    candidate.source_event_ids = ["evt-review"]
    candidate.content = "Old input must not overwrite new evidence"
    replayed = await store.upsert_candidate(candidate=candidate)
    assert replayed["content"] == revised["content"]
    assert replayed["insight_metadata"]["review_history"][0]["review_state"] == "rejected"


@pytest.mark.asyncio
async def test_rejecting_context_hides_derived_summary(store):
    await _insert_summary(store, "context")
    child = await store.upsert_candidate(candidate=L3Candidate(
        content="Derived observation", source_event_ids=["evt-test", "evt-child"],
        summary_category="state_change", summary_type="insight",
        insight_metadata={"dependency_summary_ids": ["context"]},
    ))
    assert await store.get_summary_by_id(child["summary_id"]) is not None
    await store.set_review_state(summary_id="context", review_state="rejected")
    assert await store.get_summary_by_id(child["summary_id"]) is None
