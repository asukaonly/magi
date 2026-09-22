"""Ordinary graph recurrence creates a new factual period without erasing gaps."""

from __future__ import annotations

import time

import pytest

from magi.memory.l2.corrections.models import CorrectionKind
from .test_claim_text_pipeline import APPLE_ID
from .test_preference_exclusions import _open, _read, _say


@pytest.fixture
async def graph_memory(tmp_path):
    store, adapter = await _open(tmp_path)
    try:
        yield store, adapter
    finally:
        await store.shutdown()


async def _current(store, at=None):
    return await store.l2.list_current_relationships(
        subject_id="user:u1", object_id=APPLE_ID,
        predicates=["LIKES", "DISLIKES"], effective_at=at,
    )


async def _repeat_edge(store, predicate, event_id, observed_at):
    return await store.l2.upsert_knowledge_edge(
        subject_id="user:u1", subject_type="user", predicate=predicate,
        object_id=APPLE_ID, object_type="other", fact_kind="stable_preference",
        evidence_event_ids=[event_id], confidence=0.9, observed_at=observed_at,
        source_type="conversation", extraction_method="explicit",
        evidence_class="user_self_report",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("first, opposite", [("LIKES", "DISLIKES"), ("DISLIKES", "LIKES")])
async def test_repeated_preference_starts_a_new_period_with_its_own_evidence(graph_memory, first, opposite):
    store, adapter = graph_memory
    t1 = time.time() - 300
    t2, t3 = t1 + 100, t1 + 200
    for event, predicate, observed in [("first", first, t1), ("opposite", opposite, t2), ("again", first, t3)]:
        await _say(store, adapter, event, predicate=predicate, observed_at=observed)
    current = await _current(store)
    assert [(row["predicate"], row["valid_from"], row["valid_to"], row["evidence_event_ids"]) for row in current] == [
        (first, t3, None, ["again"])
    ]
    for at, predicate, start, end, evidence in [
        (t1 + 1, first, t1, t2, ["first"]),
        (t2 + 1, opposite, t2, t3, ["opposite"]),
        (t3 + 1, first, t3, None, ["again"]),
    ]:
        rows = await _current(store, at)
        assert [(row["predicate"], row["valid_from"], row["valid_to"], row["evidence_event_ids"]) for row in rows] == [
            (predicate, start, end, evidence)
        ]
    versions = await _read(store, "SELECT * FROM knowledge_graph_versions")
    await _repeat_edge(store, first, "again", t3)
    assert len(await _read(store, "SELECT * FROM knowledge_graph_versions")) == len(versions)
    assert [(row["predicate"], row["valid_from"]) for row in await _current(store)] == [(first, t3)]


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate", ["LIKES", "DISLIKES"])
async def test_withdrawal_then_reaffirmation_preserves_the_unknown_gap(graph_memory, predicate):
    store, adapter = graph_memory
    t1 = time.time() - 300
    t2, t3 = t1 + 100, t1 + 200
    await _say(store, adapter, "first", predicate=predicate, observed_at=t1)
    await _say(store, adapter, "withdrawn", predicate=predicate, negative=True, observed_at=t2)
    assert not await _current(store)
    await _say(store, adapter, "again", predicate=predicate, observed_at=t3)
    assert [(row["predicate"], row["valid_from"], row["evidence_event_ids"]) for row in await _current(store)] == [
        (predicate, t3, ["again"])
    ]
    assert [(row["predicate"], row["valid_to"]) for row in await _current(store, t1 + 1)] == [(predicate, t2)]
    assert not await _current(store, t2 + 1)
    assert [(row["predicate"], row["valid_from"]) for row in await _current(store, t3 + 1)] == [(predicate, t3)]


@pytest.mark.asyncio
async def test_late_conflicting_observation_keeps_claim_but_defers_graph_projection(graph_memory):
    store, adapter = graph_memory
    t1 = time.time() - 300
    await _say(store, adapter, "first", observed_at=t1)
    await _say(store, adapter, "latest", observed_at=t1 + 200)
    before = await _current(store)
    await _say(store, adapter, "late-opposite", predicate="DISLIKES", observed_at=t1 + 100)
    after = await _current(store)
    assert [(row["predicate"], row["valid_from"], row["valid_to"]) for row in after] == [
        (row["predicate"], row["valid_from"], row["valid_to"]) for row in before
    ]
    claims = await _read(store, "SELECT claim_id, availability FROM l2_grounded_claims WHERE canonical_predicate = 'DISLIKES'")
    assert len(claims) == 1 and claims[0]["availability"] == "active"
    receipts = await _read(store, "SELECT outcome, reason_code FROM l2_claim_projection_outcomes WHERE claim_id = ? AND target_kind = 'relationship'", (claims[0]["claim_id"],))
    assert [(row["outcome"], row["reason_code"]) for row in receipts] == [("skipped", "historical_graph_projection_deferred")]


@pytest.mark.asyncio
async def test_late_evidence_in_retained_closed_period_never_changes_current_edge(graph_memory):
    store, adapter = graph_memory
    t1 = time.time() - 300
    await _say(store, adapter, "first", observed_at=t1)
    await _say(store, adapter, "opposite", predicate="DISLIKES", observed_at=t1 + 100)
    await _say(store, adapter, "late-support", observed_at=t1 + 50)
    assert [row["predicate"] for row in await _current(store)] == ["DISLIKES"]
    past = await _current(store, t1 + 75)
    assert len(past) == 1 and past[0]["predicate"] == "LIKES"
    assert set(past[0]["evidence_event_ids"]) == {"first", "late-support"}
    assert past[0]["valid_from"] == t1
    assert past[0]["valid_to"] == t1 + 100


@pytest.mark.asyncio
async def test_reaffirmation_does_not_override_user_relationship_correction(graph_memory):
    store, adapter = graph_memory
    t1 = time.time() - 300
    await _say(store, adapter, "first", observed_at=t1)
    original = (await _current(store))[0]
    corrected = await store.l2.apply_relationship_correction(
        triple_id=original["triple_id"], request_id="correct-preference",
        actor_id="user:u1", correction_kind=CorrectionKind.RECORD_ERROR,
        replacement={"predicate": "DISLIKES"},
    )
    assert corrected is not None
    await _say(store, adapter, "again", observed_at=t1 + 200)
    current = await _current(store)
    assert [row["predicate"] for row in current] == ["DISLIKES"]
    assert current[0]["authority_ref"].startswith("correction:")


@pytest.mark.asyncio
async def test_forgotten_source_cannot_reactivate_a_graph_period(graph_memory):
    store, adapter = graph_memory
    t1 = time.time() - 300
    await _say(store, adapter, "forgotten", observed_at=t1)
    await store.forget_source_events(["forgotten"])
    await _repeat_edge(store, "LIKES", "forgotten", t1)
    assert not await _current(store)


@pytest.mark.asyncio
async def test_corroborated_period_closes_at_source_time_before_recurrence(graph_memory):
    store, adapter = graph_memory
    t1 = time.time() - 300
    await _say(store, adapter, "first", observed_at=t1)
    await _say(store, adapter, "support", observed_at=t1 + 50)
    same_period = (await _current(store))[0]
    assert same_period["first_observed_at"] == t1
    assert same_period["last_observed_at"] == t1 + 50
    await _say(store, adapter, "opposite", predicate="DISLIKES", observed_at=t1 + 100)
    await _say(store, adapter, "again", observed_at=t1 + 200)
    past = await _current(store, t1 + 75)
    assert len(past) == 1 and past[0]["predicate"] == "LIKES"
    assert past[0]["valid_to"] == t1 + 100
    assert set(past[0]["evidence_event_ids"]) == {"first", "support"}
    assert [row["predicate"] for row in await _current(store, t1 + 150)] == ["DISLIKES"]
