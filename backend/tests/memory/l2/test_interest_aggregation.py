"""Tests for interest_aggregation.aggregate_interests().

Three test scenarios:
1. Basic aggregation: Topics A & C (observation_count >= 3) produce
   ``interest_profile`` assertions; topic B (count < 3) is skipped.
2. Snapshot surfacing: aggregated interests appear in a refreshed snapshot
   under ``preferences`` with ``source_tier == "inferred"``.
3. Idempotency: running aggregate_interests twice yields exactly one assertion
   per topic with no evidence duplication.

Corroboration / snapshot visibility note
-----------------------------------------
``_add_assertion_preferences`` is called with ``active_assertions``, which
``refresh_entity_snapshot`` defines as assertions with
``status in {"stable", "corroborated"}``.  The state machine promotes to
``corroborated`` when ``evidence_count >= 2``.  We therefore seed edges with
at least 2 distinct event IDs so the assertion is corroborated immediately
and is visible in the snapshot.  A single-event assertion stays ``tentative``
and does NOT appear in the snapshot preferences (see state_machine.py line 71).
"""

from __future__ import annotations

import json
import time

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.identity.defaults import CANONICAL_LOCAL_USER
from magi.memory.l2.assertions.interest_aggregation import aggregate_interests

from .test_derived_assertion_rules import _EvidenceEventStore


DEFAULT_USER_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_interested_in_edge(
    store,
    *,
    object_id: str,
    object_type: str = "topic",
    event_ids: list[str],
    confidence: float = 0.8,
    entity_id: str = DEFAULT_USER_ENTITY_ID,
    spread_days: bool = True,
) -> None:
    """Seed an INTERESTED_IN edge with the given evidence event IDs.

    Each unique event_id in ``event_ids`` is ingested as a separate call to
    upsert_knowledge_edge so the graph accumulates observation_count correctly
    (one increment per new event id).
    """
    now = time.time()
    interval = 86_400 if spread_days else 0.001
    for i, eid in enumerate(event_ids):
        await store.upsert_knowledge_edge(
            subject_id=entity_id,
            subject_type="person",
            predicate="INTERESTED_IN",
            object_id=object_id,
            object_type=object_type,
            evidence_event_ids=[eid],
            confidence=confidence,
            observed_at=now + i * interval,
            source_type="chrome_history",
        )


async def _seed_canonical_name(store, *, entity_id: str, canonical_name: str, entity_type: str = "topic") -> None:
    """Insert an entity_catalog row so get_canonical_names can resolve it."""
    now = time.time()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO entity_catalog(entity_id, canonical_name, entity_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                entity_type = excluded.entity_type,
                updated_at = excluded.updated_at
            """,
            (entity_id, canonical_name, entity_type, now, now),
        )
        await db.commit()


async def _get_assertions(store, entity_id: str = DEFAULT_USER_ENTITY_ID) -> list[dict]:
    """Fetch raw assertion rows (active + shadow) from the database."""
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tom_trait_assertions WHERE entity_id = ?",
            (entity_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Test 1 – Basic aggregation filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_filters_by_min_observations(l2_store_with_schema):
    """Topics with obs_count >= 3 produce assertions; below-threshold topics do not."""
    store = l2_store_with_schema

    # Topic A: 5 observations (5 unique event IDs) → qualifies
    await _seed_interested_in_edge(
        store,
        object_id="topic:machine-learning",
        event_ids=["ml-e1", "ml-e2", "ml-e3", "ml-e4", "ml-e5"],
    )
    await _seed_canonical_name(store, entity_id="topic:machine-learning", canonical_name="Machine Learning")

    # Topic B: 2 observations → below threshold, must be skipped
    await _seed_interested_in_edge(
        store,
        object_id="topic:astronomy",
        event_ids=["ast-e1", "ast-e2"],
    )
    await _seed_canonical_name(store, entity_id="topic:astronomy", canonical_name="Astronomy")

    # Topic C: 3 observations → qualifies
    await _seed_interested_in_edge(
        store,
        object_id="topic:rust-lang",
        event_ids=["rust-e1", "rust-e2", "rust-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:rust-lang", canonical_name="Rust Programming Language")

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )

    assert stats["edges_seen"] == 3
    assert stats["topics_aggregated"] == 2

    assertions = await _get_assertions(store)
    trait_names = {a["trait_name"] for a in assertions}

    # A & C must be present
    assert "interest.machine-learning" in trait_names
    assert "interest.rust-lang" in trait_names
    # B must be absent
    assert "interest.astronomy" not in trait_names

    # Verify families and source_domain
    for a in assertions:
        if a["trait_name"] in {"interest.machine-learning", "interest.rust-lang"}:
            assert a["trait_family"] == "interest_profile", a
            assert a["source_domain"] == "external_activity", a


# ---------------------------------------------------------------------------
# Test 2 – Snapshot surfacing with source_tier="inferred"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_surfaces_in_snapshot_as_inferred(l2_store_with_schema):
    """Aggregated interests (with >=2 evidence events) appear in the snapshot
    as source_tier=``"inferred"`` preferences."""
    store = l2_store_with_schema

    # 3 unique events → observation_count=3, evidence_event_ids=["e1","e2","e3"]
    # State machine: evidence_count >= 2 → corroborated → visible in snapshot
    await _seed_interested_in_edge(
        store,
        object_id="topic:python",
        event_ids=["py-e1", "py-e2", "py-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:python", canonical_name="Python")

    # Seed a below-threshold topic (only 1 event → stays tentative → absent from snapshot)
    await _seed_interested_in_edge(
        store,
        object_id="topic:fortran",
        event_ids=["ft-e1"],
    )
    await _seed_canonical_name(store, entity_id="topic:fortran", canonical_name="Fortran")

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )
    assert stats["topics_aggregated"] == 1

    # Verify assertion validation_state is at least corroborated
    assertions = await _get_assertions(store)
    # Only the python assertion should have been written (fortran < threshold)
    written_names = {a["trait_name"] for a in assertions}
    assert "interest.python" in written_names
    assert "interest.fortran" not in written_names, (
        "Below-threshold topic 'fortran' should not have produced an assertion"
    )
    row = next(a for a in assertions if a["trait_name"] == "interest.python")
    assert row["validation_state"] in {"corroborated", "stable"}, (
        f"Expected corroborated or stable, got {row['validation_state']!r}. "
        f"evidence_events={row['evidence_events']!r}"
    )

    # Refresh snapshot and assert the interest is present as inferred preference
    snapshot = await store.refresh_entity_snapshot(entity_id=DEFAULT_USER_ENTITY_ID, entity_type="user")
    assert snapshot is not None, "refresh_entity_snapshot returned None"

    preferences = snapshot.get("preferences") or {}
    assert "interest.python" in preferences, (
        f"'interest.python' not in snapshot preferences. Got: {list(preferences.keys())}"
    )
    pref = preferences["interest.python"]
    assert pref["source_tier"] == "inferred", (
        f"Expected source_tier='inferred', got {pref['source_tier']!r}"
    )
    assert pref["value"] == "Python", f"Expected value='Python', got {pref['value']!r}"
    assert pref["family"] == "interest_profile", (
        f"Expected family='interest_profile', got {pref['family']!r}"
    )

    # Negative invariant: below-threshold topic must be absent from snapshot preferences
    assert "interest.fortran" not in preferences, (
        "Below-threshold topic 'fortran' must not appear in snapshot preferences"
    )


# ---------------------------------------------------------------------------
# Test 3 – Idempotency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_is_idempotent(l2_store_with_schema):
    """Running aggregate_interests twice produces exactly one assertion per topic
    with no evidence duplication."""
    store = l2_store_with_schema

    await _seed_interested_in_edge(
        store,
        object_id="topic:go-lang",
        event_ids=["go-e1", "go-e2", "go-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:go-lang", canonical_name="Go Programming Language")

    l1_store = _EvidenceEventStore()
    stats1 = await aggregate_interests(
        store, l1_store=l1_store, min_observations=3
    )
    assert stats1["topics_aggregated"] == 1

    stats2 = await aggregate_interests(
        store, l1_store=l1_store, min_observations=3
    )
    assert stats2["topics_aggregated"] == 1

    # Must be exactly ONE non-shadow assertion row for this trait
    assertions = await _get_assertions(store)
    active = [
        a for a in assertions
        if a["trait_name"] == "interest.go-lang"
        and a.get("status") not in ("superseded", "archived", "expired", "user_rejected", "shadow")
    ]
    assert len(active) == 1, f"Expected exactly one active assertion, got {len(active)}: {active}"

    # Evidence events must not be duplicated
    ev = json.loads(active[0]["evidence_events"] or "[]")
    assert len(ev) == len(set(ev)), f"Duplicate evidence events found: {ev}"


# ---------------------------------------------------------------------------
# Test 4 – Below-threshold edge produces no assertions and zero aggregated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_returns_zero_when_all_below_threshold(l2_store_with_schema):
    """When all edges are below min_observations, no assertions are written."""
    store = l2_store_with_schema

    await _seed_interested_in_edge(
        store,
        object_id="topic:haskell",
        event_ids=["hk-e1"],  # only 1 event
    )

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )
    assert stats["edges_seen"] == 1
    assert stats["topics_aggregated"] == 0

    assertions = await _get_assertions(store)
    assert len(assertions) == 0


@pytest.mark.asyncio
async def test_aggregate_interests_skips_single_day_repetition(l2_store_with_schema):
    """Repeated same-day browsing should remain graph evidence, not a profile assertion."""
    store = l2_store_with_schema

    await _seed_interested_in_edge(
        store,
        object_id="topic:one-off-news",
        event_ids=["news-e1", "news-e2", "news-e3", "news-e4"],
        spread_days=False,
    )
    await _seed_canonical_name(store, entity_id="topic:one-off-news", canonical_name="One-off news")

    stats = await aggregate_interests(
        store,
        l1_store=_EvidenceEventStore(spread_days=False),
        min_observations=3,
    )

    assert stats["edges_seen"] == 1
    assert stats["topics_aggregated"] == 0
    assert await _get_assertions(store) == []


@pytest.mark.asyncio
async def test_aggregate_interests_skips_non_profile_object_types(l2_store_with_schema):
    """Generic software entities should not become portrait interests by default."""
    store = l2_store_with_schema

    await _seed_interested_in_edge(
        store,
        object_id="software:random-tool",
        object_type="software",
        event_ids=["tool-e1", "tool-e2", "tool-e3"],
    )
    await _seed_canonical_name(
        store,
        entity_id="software:random-tool",
        canonical_name="Random Tool",
        entity_type="software",
    )

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )

    assert stats["edges_seen"] == 1
    assert stats["topics_aggregated"] == 0
    assert await _get_assertions(store) == []


# ---------------------------------------------------------------------------
# Test 5 – Slug collision: lossy sanitization produces distinct trait_names
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_slug_collision_produces_distinct_trait_names(l2_store_with_schema):
    """Two topics whose object_ids differ only in non-slug chars (e.g. 'c++ lang'
    vs 'c# lang') both appear in the snapshot under distinct trait_names —
    neither is silently lost to a slug collision.
    """
    store = l2_store_with_schema

    # Both sanitize naively to "c__lang"; the hash suffix must distinguish them.
    await _seed_interested_in_edge(
        store,
        object_id="topic:c++ lang",
        event_ids=["cpp-e1", "cpp-e2", "cpp-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:c++ lang", canonical_name="C++")

    await _seed_interested_in_edge(
        store,
        object_id="topic:c# lang",
        event_ids=["cs-e1", "cs-e2", "cs-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:c# lang", canonical_name="C#")

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )
    assert stats["topics_aggregated"] == 2, (
        f"Both topics should be aggregated, got topics_aggregated={stats['topics_aggregated']}"
    )

    assertions = await _get_assertions(store)
    trait_names = {a["trait_name"] for a in assertions}

    # Both must be present and distinct
    assert len(trait_names) == 2, f"Expected 2 distinct trait_names, got: {trait_names}"

    # Neither should be a plain "interest.c__lang" without a disambiguating suffix
    assert all(name.startswith("interest.c") for name in trait_names), trait_names
    # The two names must differ (no silent overwrite)
    names_list = [a["trait_name"] for a in assertions]
    assert names_list[0] != names_list[1], f"Slug collision: both traits got name {names_list[0]!r}"


# ---------------------------------------------------------------------------
# Test 6 – Empty slug: "topic:" is skipped, no assertion written, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aggregate_interests_skips_empty_slug(l2_store_with_schema):
    """A topic whose object_id is exactly 'topic:' (empty slug after stripping
    prefix) is skipped without crashing; no assertion is written for it.
    """
    store = l2_store_with_schema

    # Seed the degenerate topic with enough events to pass the threshold
    await _seed_interested_in_edge(
        store,
        object_id="topic:",
        event_ids=["empty-e1", "empty-e2", "empty-e3"],
    )

    # Also seed a valid topic to confirm aggregation still runs for good topics
    await _seed_interested_in_edge(
        store,
        object_id="topic:typescript",
        event_ids=["ts-e1", "ts-e2", "ts-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:typescript", canonical_name="TypeScript")

    stats = await aggregate_interests(
        store, l1_store=_EvidenceEventStore(), min_observations=3
    )

    # "topic:" should be skipped; only "topic:typescript" should be aggregated
    assert stats["topics_aggregated"] == 1, (
        f"Expected 1 (only 'typescript'), got topics_aggregated={stats['topics_aggregated']}"
    )

    assertions = await _get_assertions(store)
    trait_names = {a["trait_name"] for a in assertions}

    # The poisoned "interest." key must not appear
    assert "interest." not in trait_names, (
        f"Empty-slug topic should have been skipped, but 'interest.' appeared in: {trait_names}"
    )
    assert "interest.typescript" in trait_names
