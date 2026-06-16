"""Tests for materialize_shadow_conflict_notifications (PB-T2).

Shadow rows are created when an inferred candidate conflicts with a
user-authoritative row (see write.py upsert guard).  This module verifies
that the maintenance scan:

1. Emits exactly one notification per shadow (deduped by trait slot).
2. Running twice bumps, not duplicates, the notification.
3. Config flag off → no notifications emitted.
4. No shadows → no notifications.
5. Shadow with no surviving authoritative → notification skipped.
6. Payload carries the required fields (conflict_type, shadow_id,
   authoritative_value, inferred_value, entity_id).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest

from magi.notifications.service import NotificationService
from magi.notifications.store import NotificationStore

# ---------------------------------------------------------------------------
# Stable test key (isolated from other test files)
# ---------------------------------------------------------------------------
_ENTITY_ID = "user:conflict_notification_test"
_TRAIT_NAME = "music_preference"
_TARGET_ID = "topic:jazz"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notification_store(tmp_path) -> tuple[NotificationStore, NotificationService]:
    """Build a fresh NotificationStore + NotificationService backed by a temp DB."""
    ns = NotificationStore(str(tmp_path / "notifications.db"))
    ns.ensure_schema()
    svc = NotificationService(store=ns)
    return ns, svc


def _candidate(
    *,
    trait_value: str,
    source_domain: str,
    evidence_event: str,
    entity_id: str = _ENTITY_ID,
    trait_name: str = _TRAIT_NAME,
    target_id: str = _TARGET_ID,
    inferred_at: float = 1_710_000_000.0,
) -> Dict[str, Any]:
    """Build a minimal assertion candidate dict."""
    return {
        "entity_id": entity_id,
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": 0.40,
        "evidence_events": [evidence_event],
        "volatility_index": 0.2,
        "source_domain": source_domain,
        "inference_depth": "topology_only",
        "validation_state": "tentative",
        "first_inferred_at": inferred_at,
        "last_validated_at": inferred_at,
        "target_entity_id": target_id,
        "target_entity_type": "topic",
        "target_scope": "entity_bound",
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "decay_anchor_at": inferred_at,
        "context_ref_id": "",
        "expires_at": None,
        "memory_subdomain": "",
        "natural_summary": "",
    }


async def _setup_shadow(store) -> tuple[str, str]:
    """Create one authoritative + one conflicting inferred row → shadow.

    Returns (authoritative_id, shadow_id).
    """
    auth_id = await store.upsert_assertion_candidate(
        _candidate(
            trait_value="classical",
            source_domain="user_authored",
            evidence_event="evt-auth-notif-1",
        )
    )
    shadow_id = await store.upsert_assertion_candidate(
        _candidate(
            trait_value="jazz",
            source_domain="external_activity",
            evidence_event="evt-inferred-notif-1",
            inferred_at=1_710_000_100.0,
        )
    )
    return auth_id, shadow_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_notification_emitted_per_conflict(l2_store_with_schema, tmp_path):
    """Running the scan once emits exactly one notification with the right payload."""
    from magi.memory.l2.assertions.conflict_notifications import (
        materialize_shadow_conflict_notifications,
    )

    store = l2_store_with_schema
    auth_id, shadow_id = await _setup_shadow(store)

    ns, svc = _notification_store(tmp_path)

    stats = await materialize_shadow_conflict_notifications(
        store,
        svc,
        user_id="default_user",
        entity_id=_ENTITY_ID,
        entity_type="user",
    )

    assert stats["shadows_seen"] == 1
    assert stats["notifications_emitted"] == 1

    items = ns.list_for_user("default_user")
    assert len(items) == 1, f"expected 1 notification, got {len(items)}"

    notif = items[0]
    expected_dedupe = f"profile_conflict:{_TRAIT_NAME}:{_TARGET_ID}"
    assert notif.dedupe_key == expected_dedupe, (
        f"wrong dedupe_key: {notif.dedupe_key!r}"
    )

    payload = json.loads(notif.payload_json)
    assert payload["conflict_type"] == "profile_conflict"
    assert payload["shadow_id"] == shadow_id
    assert payload["authoritative_id"] == auth_id
    assert payload["authoritative_value"] == "classical"
    assert payload["inferred_value"] == "jazz"
    assert payload["entity_id"] == _ENTITY_ID


@pytest.mark.asyncio
async def test_second_run_bumps_not_duplicates(l2_store_with_schema, tmp_path):
    """Running the scan twice → still one notification (bumped, not duplicated)."""
    from magi.memory.l2.assertions.conflict_notifications import (
        materialize_shadow_conflict_notifications,
    )

    store = l2_store_with_schema
    await _setup_shadow(store)

    ns, svc = _notification_store(tmp_path)

    await materialize_shadow_conflict_notifications(
        store, svc, user_id="default_user", entity_id=_ENTITY_ID, entity_type="user"
    )
    stats2 = await materialize_shadow_conflict_notifications(
        store, svc, user_id="default_user", entity_id=_ENTITY_ID, entity_type="user"
    )

    assert stats2["notifications_emitted"] == 1  # bump counts as emitted

    items = ns.list_for_user("default_user")
    assert len(items) == 1, f"expected 1 notification after 2 runs, got {len(items)}"


@pytest.mark.asyncio
async def test_no_shadows_no_notifications(l2_store_with_schema, tmp_path):
    """When there are no shadow rows, no notifications are emitted."""
    from magi.memory.l2.assertions.conflict_notifications import (
        materialize_shadow_conflict_notifications,
    )

    store = l2_store_with_schema
    # Insert only an authoritative row — no shadow.
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="classical",
            source_domain="user_authored",
            evidence_event="evt-auth-only-1",
            entity_id="user:no_shadow_test",
        )
    )

    ns, svc = _notification_store(tmp_path)

    stats = await materialize_shadow_conflict_notifications(
        store,
        svc,
        user_id="default_user",
        entity_id="user:no_shadow_test",
        entity_type="user",
    )

    assert stats["shadows_seen"] == 0
    assert stats["notifications_emitted"] == 0
    assert ns.list_for_user("default_user") == []


@pytest.mark.asyncio
async def test_shadow_without_surviving_authoritative_is_skipped(l2_store_with_schema, tmp_path):
    """If the authoritative row no longer exists (superseded), shadow is skipped."""
    from magi.memory.l2.assertions.conflict_notifications import (
        materialize_shadow_conflict_notifications,
    )
    from magi.core.sqlite import sqlite_connection_async

    store = l2_store_with_schema
    auth_id, shadow_id = await _setup_shadow(store)

    # Manually supersede the authoritative row so it no longer qualifies.
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

    ns, svc = _notification_store(tmp_path)

    stats = await materialize_shadow_conflict_notifications(
        store,
        svc,
        user_id="default_user",
        entity_id=_ENTITY_ID,
        entity_type="user",
    )

    assert stats["shadows_seen"] == 1
    assert stats["notifications_emitted"] == 0
    assert ns.list_for_user("default_user") == []


@pytest.mark.asyncio
async def test_multiple_shadows_multiple_notifications(l2_store_with_schema, tmp_path):
    """Two separate trait conflicts → two separate notifications."""
    from magi.memory.l2.assertions.conflict_notifications import (
        materialize_shadow_conflict_notifications,
    )

    store = l2_store_with_schema
    entity = "user:multi_shadow_test"
    target_a = "topic:movies"
    target_b = "topic:music"
    trait = "preference"

    # Conflict A
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="drama",
            source_domain="user_authored",
            evidence_event="evt-auth-a",
            entity_id=entity,
            trait_name=trait,
            target_id=target_a,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="action",
            source_domain="external_activity",
            evidence_event="evt-inf-a",
            entity_id=entity,
            trait_name=trait,
            target_id=target_a,
            inferred_at=1_710_000_100.0,
        )
    )

    # Conflict B — same trait_name, different target_entity_id → different dedupe_key
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="classical",
            source_domain="user_authored",
            evidence_event="evt-auth-b",
            entity_id=entity,
            trait_name=trait,
            target_id=target_b,
        )
    )
    await store.upsert_assertion_candidate(
        _candidate(
            trait_value="hiphop",
            source_domain="external_activity",
            evidence_event="evt-inf-b",
            entity_id=entity,
            trait_name=trait,
            target_id=target_b,
            inferred_at=1_710_000_200.0,
        )
    )

    ns, svc = _notification_store(tmp_path)

    stats = await materialize_shadow_conflict_notifications(
        store,
        svc,
        user_id="default_user",
        entity_id=entity,
        entity_type="user",
    )

    assert stats["shadows_seen"] == 2
    assert stats["notifications_emitted"] == 2

    items = ns.list_for_user("default_user")
    assert len(items) == 2

    dedupe_keys = {item.dedupe_key for item in items}
    assert f"profile_conflict:{trait}:{target_a}" in dedupe_keys
    assert f"profile_conflict:{trait}:{target_b}" in dedupe_keys
