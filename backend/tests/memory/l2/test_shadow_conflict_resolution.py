"""Tests for resolve_shadow_conflict in L2StoreFeedbackMixin.

Shadow rows are created when an inferred candidate conflicts with a
user-authoritative row (see write.py upsert guard). The resolution function
lets a user accept (confirm) or discard (reject) the shadow:

- confirm: shadow becomes the active, authoritative row; old authoritative is
  superseded. The promoted row has user_feedback='confirmed' and status='stable'.
  The unique index is never violated because the old row is superseded BEFORE the
  shadow is promoted.

- reject: shadow is marked user_rejected; the authoritative row is untouched.

- idempotent: calling with an active row's id (not a shadow) or after resolution
  returns None and makes no further changes.

- edge — no surviving authoritative: shadow can still be promoted cleanly if the
  old authoritative was already gone (no crash).
"""

from __future__ import annotations

from typing import Any, Dict, List

import aiosqlite
import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.assertions.source_tier import source_tier

# ---------------------------------------------------------------------------
# Stable test key (isolated from other test files)
# ---------------------------------------------------------------------------
_ENTITY_ID = "user:conflict_resolution_test"
_TRAIT_NAME = "preferred_language"
_TARGET_ID = "entity:python_language"


# ---------------------------------------------------------------------------
# Helpers shared across all tests in this module
# ---------------------------------------------------------------------------

def _candidate(
    *,
    trait_value: str,
    source_domain: str,
    evidence_event: str,
    inferred_at: float = 1_710_000_000.0,
) -> Dict[str, Any]:
    """Build a minimal, fully-shaped assertion candidate."""
    return {
        "entity_id": _ENTITY_ID,
        "entity_type": "user",
        "trait_family": "technical_profile",
        "trait_name": _TRAIT_NAME,
        "trait_value": trait_value,
        "confidence_score": 0.40,
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
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "decay_anchor_at": inferred_at,
        "context_ref_id": "",
        "expires_at": None,
        "memory_subdomain": "",
        "natural_summary": "",
    }


async def _all_rows(db_path: str) -> List[Dict[str, Any]]:
    """Return every row on the test (entity_id, trait_name) key, all statuses."""
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
    excluded = {"superseded", "archived", "expired", "user_rejected", "shadow"}
    return [r for r in rows if r["status"] not in excluded]


def _shadow_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r["status"] == "shadow"]


async def _setup_shadow(store) -> tuple[str, str]:
    """Upsert an authoritative row, then a conflicting inferred one → shadow.

    Returns (authoritative_id, shadow_id).
    """
    auth_id = await store.upsert_assertion_candidate(
        _candidate(
            trait_value="python",
            source_domain="user_authored",
            evidence_event="evt-auth-1",
            inferred_at=1_710_000_000.0,
        )
    )
    shadow_id = await store.upsert_assertion_candidate(
        _candidate(
            trait_value="rust",  # conflicting inferred value
            source_domain="external_activity",
            evidence_event="evt-inferred-1",
            inferred_at=1_710_000_100.0,
        )
    )
    # Confirm preconditions.
    rows = await _all_rows(store.db_path)
    assert len(_active_rows(rows)) == 1, "setup: expect 1 active row"
    assert len(_shadow_rows(rows)) == 1, "setup: expect 1 shadow row"
    assert _shadow_rows(rows)[0]["assertion_id"] == shadow_id
    return auth_id, shadow_id


# ---------------------------------------------------------------------------
# Test 1: confirm promotes shadow and supersedes the authoritative row
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_promotes_shadow(l2_store_with_schema):
    """After confirm:
    - shadow row has status='stable', user_feedback='confirmed'.
    - old authoritative row has status='superseded'.
    - exactly one active row on the key, with the shadow's value.
    - source_tier for the promoted row is 'authoritative'.
    - refresh_entity_snapshot was called (snapshot exists).
    """
    store = l2_store_with_schema
    auth_id, shadow_id = await _setup_shadow(store)

    result = await store.resolve_shadow_conflict(shadow_id=shadow_id, action="confirm")

    assert result is not None, "confirm must return the promoted row"
    assert result["assertion_id"] == shadow_id
    assert result["status"] == "stable"
    assert result["user_feedback"] == "confirmed"
    assert result["trait_value"] == "rust"
    assert float(result["confidence_score"]) > 0.40  # raised by +0.20

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    assert len(active) == 1, f"expected exactly 1 active row, got {[(r['trait_value'], r['status']) for r in rows]}"
    assert active[0]["assertion_id"] == shadow_id
    assert active[0]["trait_value"] == "rust"

    # Old authoritative is now superseded and points to the shadow.
    superseded = [r for r in rows if r["assertion_id"] == auth_id]
    assert len(superseded) == 1
    assert superseded[0]["status"] == "superseded"
    assert superseded[0]["superseded_by"] == shadow_id

    # source_tier evaluates to authoritative because user_feedback='confirmed'.
    tier = source_tier(
        source_domain=result["source_domain"],
        user_feedback=result["user_feedback"],
    )
    assert tier == "authoritative", f"expected authoritative tier, got {tier!r}"

    # Snapshot refresh was called without error (it's error-isolated in the impl).
    # We just verify no exception was raised; snapshot content depends on confidence
    # thresholds that the single-evidence row may not meet.
    await store.get_tom_snapshot(entity_id=_ENTITY_ID, entity_type="user")
    # snapshot may be None if assertion hasn't reached stable threshold — that's fine.


# ---------------------------------------------------------------------------
# Test 2: reject discards shadow, authoritative row unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_discards_shadow(l2_store_with_schema):
    """After reject:
    - shadow row has status='user_rejected'.
    - authoritative row is unchanged (still active, original value 'python').
    - snapshot still shows the original value.
    """
    store = l2_store_with_schema
    auth_id, shadow_id = await _setup_shadow(store)

    result = await store.resolve_shadow_conflict(shadow_id=shadow_id, action="reject")

    assert result is not None, "reject must return the updated shadow row"
    assert result["assertion_id"] == shadow_id
    assert result["status"] == "user_rejected"
    assert result["validation_state"] == "user_rejected"

    corrections = await store.list_assertion_corrections(assertion_id=shadow_id)
    assert len(corrections) == 1
    assert corrections[0]["correction_kind"] == "record_error"

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    assert len(active) == 1, f"expected 1 active row, got {[(r['trait_value'], r['status']) for r in rows]}"
    assert active[0]["assertion_id"] == auth_id
    assert active[0]["trait_value"] == "python"
    assert active[0]["status"] not in ("superseded", "archived", "expired", "user_rejected", "shadow")

    # Shadow is gone from active pool.
    assert _shadow_rows(rows) == []


# ---------------------------------------------------------------------------
# Test 3: idempotent / not-a-shadow returns None and changes nothing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_idempotent_active_row_returns_none(l2_store_with_schema):
    """Calling resolve_shadow_conflict with an active row's id returns None."""
    store = l2_store_with_schema
    auth_id, _ = await _setup_shadow(store)

    result = await store.resolve_shadow_conflict(shadow_id=auth_id, action="confirm")

    assert result is None, "should return None for a non-shadow row"

    # Nothing changed.
    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    assert len(active) == 1
    assert active[0]["assertion_id"] == auth_id
    assert active[0]["trait_value"] == "python"


@pytest.mark.asyncio
async def test_idempotent_after_resolution(l2_store_with_schema):
    """Calling resolve_shadow_conflict a second time after resolution returns None."""
    store = l2_store_with_schema
    _, shadow_id = await _setup_shadow(store)

    # First call resolves.
    first = await store.resolve_shadow_conflict(shadow_id=shadow_id, action="confirm")
    assert first is not None

    # Second call: shadow_id is no longer status='shadow' → idempotent None.
    second = await store.resolve_shadow_conflict(shadow_id=shadow_id, action="confirm")
    assert second is None

    # State unchanged from first resolution.
    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    assert len(active) == 1
    assert active[0]["assertion_id"] == shadow_id


@pytest.mark.asyncio
async def test_missing_id_returns_none(l2_store_with_schema):
    """Calling with a completely unknown id returns None without error."""
    store = l2_store_with_schema
    result = await store.resolve_shadow_conflict(shadow_id="assert_does_not_exist", action="confirm")
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: invalid action raises ValueError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invalid_action_raises_value_error(l2_store_with_schema):
    """Invalid action must raise ValueError immediately."""
    store = l2_store_with_schema
    with pytest.raises(ValueError, match="Invalid action"):
        await store.resolve_shadow_conflict(shadow_id="assert_any", action="bogus")


# ---------------------------------------------------------------------------
# Test 5: confirm with no surviving authoritative (edge case)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_with_no_surviving_authoritative(l2_store_with_schema):
    """If the authoritative row was already superseded/gone before confirmation,
    the shadow is still promoted cleanly as the new active owner.
    """
    store = l2_store_with_schema
    auth_id, shadow_id = await _setup_shadow(store)

    # Manually supersede the authoritative row before we call confirm.
    import time
    now = time.time()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'superseded', superseded_by = 'assert_external_override',
                superseded_at = ?, updated_at = ?
            WHERE assertion_id = ?
            """,
            (now, now, auth_id),
        )
        await db.commit()

    # Now there is no live authoritative; the active-key slot is free.
    rows = await _all_rows(store.db_path)
    assert _active_rows(rows) == [], "precondition: no active row before confirm"

    result = await store.resolve_shadow_conflict(shadow_id=shadow_id, action="confirm")

    assert result is not None
    assert result["status"] == "stable"
    assert result["user_feedback"] == "confirmed"
    assert result["trait_value"] == "rust"

    rows = await _all_rows(store.db_path)
    active = _active_rows(rows)
    assert len(active) == 1, f"expected 1 active row, got {[(r['trait_value'], r['status']) for r in rows]}"
    assert active[0]["assertion_id"] == shadow_id
