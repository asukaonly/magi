"""Source-aware upsert: an inferred candidate must NEVER supersede an
authoritative (user-stated) assertion.

Invariant under test (write.py ``_upsert_assertion`` guard):
- conflict  (inferred value != authoritative value) -> authoritative row is
  untouched; the inferred candidate is persisted as a ``status='shadow'``
  sibling on the same active key.
- agreement (inferred value == authoritative value) -> falls through to the
  same-value branch: reinforces the authoritative row (evidence +1, confidence
  not lowered); no shadow row is created.
- override  (authoritative candidate vs an earlier inferred row) -> existing
  supersede path applies; the user's statement wins.

These run through the public ``upsert_assertion_candidate`` entry point and read
rows back via raw SQL so both active and shadow rows are visible (retrieval APIs
hide ``shadow`` by design — Task 3).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async

_ENTITY_ID = "user:src_aware"
_TRAIT_NAME = "music_genre_preference"
_TARGET_ID = "entity:rock_music"


def _candidate(
    *,
    trait_value: str,
    source_domain: str,
    evidence_event: str,
    inferred_at: float,
    temporal_scope: str = "stable",
    decay_policy: str | None = "evidence_only",
    expires_at: float | None = None,
) -> Dict[str, Any]:
    """Build a fully-shaped assertion candidate for ``upsert_assertion_candidate``.

    Mirrors the field set the L2 LLM extraction emits (see test_store.py),
    pinned to a stable + evidence-only preference trait so volatile in-place rewrite
    paths never fire — value differences here must route through supersede
    (authoritative) or the new shadow guard (inferred).
    """
    return {
        "entity_id": _ENTITY_ID,
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": _TRAIT_NAME,
        "trait_value": trait_value,
        "confidence_score": 0.4,
        "evidence_events": [evidence_event],
        "volatility_index": 0.2,
        "source_domain": source_domain,
        "inference_depth": "defensive_psychology",
        "validation_state": "tentative",
        "first_inferred_at": inferred_at,
        "last_validated_at": inferred_at,
        "target_entity_id": _TARGET_ID,
        "target_entity_type": "entity",
        "target_scope": "entity_bound",
        "temporal_scope": temporal_scope,
        "decay_policy": decay_policy,
        "decay_anchor_at": inferred_at,
        "context_ref_id": "",
        "expires_at": expires_at,
        "memory_subdomain": "",
        "natural_summary": "",
    }


async def _all_rows(db_path: str) -> List[Dict[str, Any]]:
    """Return every tom_trait_assertions row on the test key (active + shadow).

    Filtered by (entity_id, trait_name) only — the store normalizes
    target_entity_id's prefix to match the coerced entity_type, so we don't
    couple the query to that internal rewrite; the test entity is isolated.
    """
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM tom_trait_assertions
            WHERE entity_id = ? AND trait_name = ?
            ORDER BY created_at ASC
            """,
            (_ENTITY_ID, _TRAIT_NAME),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


def _active_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows that own the active key (excluded statuses removed)."""
    excluded = {"superseded", "archived", "expired", "user_rejected", "shadow"}
    return [r for r in rows if r["status"] not in excluded]


def _shadow_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r["status"] == "shadow"]


@pytest.mark.asyncio
async def test_inferred_conflict_is_shadowed_not_superseding(l2_store_with_schema):
    """authoritative 'A' then inferred 'B' -> 'A' stays active + not superseded;
    'B' persists as exactly one shadow sibling."""
    store = l2_store_with_schema

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="user_authored",
            evidence_event="evt-auth-1",
            inferred_at=1_710_000_000.0,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="jazz",
            source_domain="external_activity",
            evidence_event="evt-inferred-1",
            inferred_at=1_710_000_100.0,
        )
    )

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    shadow = _shadow_rows(rows)

    # Exactly one active row, still the authoritative 'rock', never superseded.
    assert len(active) == 1, f"expected 1 active row, got {[r['status'] for r in rows]}"
    assert active[0]["trait_value"] == "rock"
    assert active[0]["source_domain"] == "user_authored"
    assert active[0]["status"] != "superseded"
    assert active[0]["superseded_by"] is None
    # The authoritative row's evidence is untouched by the conflicting inferred one.
    assert json.loads(active[0]["evidence_events"]) == ["evt-auth-1"]

    # Exactly one shadow row carrying the inferred 'jazz'.
    assert len(shadow) == 1, f"expected 1 shadow row, got {[r['status'] for r in rows]}"
    assert shadow[0]["trait_value"] == "jazz"
    assert shadow[0]["source_domain"] == "external_activity"
    assert shadow[0]["validation_state"] == "shadow"
    assert json.loads(shadow[0]["evidence_events"]) == ["evt-inferred-1"]


@pytest.mark.asyncio
async def test_inferred_agreement_reinforces_authoritative(l2_store_with_schema):
    """authoritative 'A' then inferred 'A' -> one active 'A', evidence accrued,
    confidence not lowered; no shadow."""
    store = l2_store_with_schema

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="user_authored",
            evidence_event="evt-auth-1",
            inferred_at=1_710_000_000.0,
        )
    )
    before = _active_rows(await _all_rows(store.db_path))
    assert len(before) == 1
    confidence_before = float(before[0]["confidence_score"])

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="external_activity",
            evidence_event="evt-inferred-agree-1",
            inferred_at=1_710_000_100.0,
        )
    )

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)

    assert len(active) == 1, f"expected 1 active row, got {[r['status'] for r in rows]}"
    assert active[0]["trait_value"] == "rock"
    # Agreement accrues the inferred evidence onto the authoritative row (+1).
    assert set(json.loads(active[0]["evidence_events"])) == {"evt-auth-1", "evt-inferred-agree-1"}
    # Reinforced: confidence must not drop.
    assert float(active[0]["confidence_score"]) >= confidence_before
    # No shadow row on agreement.
    assert _shadow_rows(rows) == []


@pytest.mark.asyncio
async def test_same_value_weaker_evidence_cannot_shorten_durable_horizon(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    inferred_at = 1_710_000_000.0

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="user_authored",
            evidence_event="evt-durable",
            inferred_at=inferred_at,
            temporal_scope="stable",
            decay_policy="evidence_only",
            expires_at=None,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="external_activity",
            evidence_event="evt-recent",
            inferred_at=inferred_at + 100,
            temporal_scope="recent",
            decay_policy="standard_decay",
            expires_at=inferred_at + 86_400,
        )
    )

    active = _active_rows(await _all_rows(store.db_path))
    assert len(active) == 1
    assert active[0]["temporal_scope"] == "stable"
    assert active[0]["decay_policy"] == "evidence_only"
    assert active[0]["expires_at"] is None
    assert set(json.loads(active[0]["evidence_events"])) == {
        "evt-durable",
        "evt-recent",
    }


@pytest.mark.asyncio
async def test_same_value_recent_reinforcement_keeps_later_expiry(
    l2_store_with_schema,
):
    store = l2_store_with_schema
    inferred_at = 1_710_000_000.0

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="external_activity",
            evidence_event="evt-longer",
            inferred_at=inferred_at,
            temporal_scope="recent",
            decay_policy="standard_decay",
            expires_at=inferred_at + 14 * 86_400,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="external_activity",
            evidence_event="evt-shorter",
            inferred_at=inferred_at + 100,
            temporal_scope="recent",
            decay_policy="standard_decay",
            expires_at=inferred_at + 7 * 86_400,
        )
    )

    active = _active_rows(await _all_rows(store.db_path))
    assert len(active) == 1
    assert active[0]["temporal_scope"] == "recent"
    assert active[0]["expires_at"] == pytest.approx(inferred_at + 14 * 86_400)


@pytest.mark.asyncio
async def test_authoritative_overrides_earlier_inferred(l2_store_with_schema):
    """inferred 'B' first, then authoritative 'A' -> 'A' active (supersede path);
    the earlier inferred row is superseded. No shadow."""
    store = l2_store_with_schema

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="jazz",
            source_domain="external_activity",
            evidence_event="evt-inferred-1",
            inferred_at=1_710_000_000.0,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="user_authored",
            evidence_event="evt-auth-1",
            inferred_at=1_710_000_100.0,
        )
    )

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)

    # User's statement wins via the existing supersede path.
    assert len(active) == 1, f"expected 1 active row, got {[r['status'] for r in rows]}"
    assert active[0]["trait_value"] == "rock"
    assert active[0]["source_domain"] == "user_authored"
    # The earlier inferred row was superseded, not shadowed.
    assert _shadow_rows(rows) == []
    superseded = [r for r in rows if r["status"] == "superseded"]
    assert len(superseded) == 1
    assert superseded[0]["trait_value"] == "jazz"

    # Superseded rows are historical context, not current user-review items.
    visible = await store.list_tom_assertions(
        entity_id=_ENTITY_ID,
        trait_families=["preference_profile"],
        include_expired=False,
        include_inactive=False,
    )
    assert all(row["status"] != "superseded" for row in visible)
    assert [row["trait_value"] for row in visible] == ["rock"]

    pending_count = await store.count_tom_assertions(
        entity_id=_ENTITY_ID,
        validation_states=["tentative", "contradicted"],
        include_expired=False,
        include_inactive=False,
    )
    assert pending_count == 0


@pytest.mark.asyncio
async def test_repeated_inferred_conflict_never_crashes_or_promotes(l2_store_with_schema):
    """A re-observed inferred conflict must not raise and must never become
    active. The 'existing' key query excludes 'shadow' (consistent with the
    active-unique index post-migration 0013), so resolution always targets the
    authoritative row — never a shadow it could promote into a 2nd active row."""
    store = l2_store_with_schema

    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rock",
            source_domain="user_authored",
            evidence_event="evt-auth-1",
            inferred_at=1_710_000_000.0,
        )
    )
    # Same inferred conflict observed twice (sources re-emit constantly).
    for i, ev in enumerate(("evt-inferred-1", "evt-inferred-2")):
        await store.upsert_assertion_candidate(
            _candidate(
                trait_value="jazz",
                source_domain="external_activity",
                evidence_event=ev,
                inferred_at=1_710_000_100.0 + i,
            )
        )

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)

    # Invariant holds: the authoritative 'rock' is the sole active owner.
    assert len(active) == 1, f"expected 1 active row, got {[(r['trait_value'], r['status']) for r in rows]}"
    assert active[0]["trait_value"] == "rock"
    # Every inferred conflict landed as a shadow; none promoted to active.
    assert all(r["trait_value"] == "jazz" for r in _shadow_rows(rows))
    assert len(_shadow_rows(rows)) >= 1
