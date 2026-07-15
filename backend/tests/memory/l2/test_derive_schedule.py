"""Tests for the MEMORY_L2_DERIVE independent scheduled task (DT-1).

Verifies:

1. ``MEMORY_L2_DERIVE`` is a valid ``ScheduledTargetType`` value.
2. ``L2DeriveScheduleContrib.register_schedules`` registers the handler plus
   periodic derive and correction-recovery schedules.
3. ``handle_l2_derive``: interest aggregation surfaces in the canonical user's snapshot when enabled.
4. ``handle_l2_derive``: a seeded canonical-user shadow produces a conflict notification when enabled.
5. ``handle_l2_derive``: ``interest_aggregation_enabled=False`` gates the step.
6. ``handle_l2_derive``: ``shadow_conflict_notification_enabled=False`` gates the step.
7. ``handle_l2_derive``: ``l2.enabled=False`` produces l2_disabled_skip.
8. ``handle_l2_derive``: ``derive_schedule_enabled=False`` produces l2_derive_disabled_skip.
9. ``handle_l2_derive``: unified memory unavailable produces unified_memory_unavailable_skip.
10. ``handle_l2_derive``: l2_entity_catalog None produces l2_catalog_uninitialized_skip.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.config.memory_models import MemoryL2Settings
from magi.memory.l2.store import L2CognitionStore
from magi.notifications.service import NotificationService
from magi.notifications.store import NotificationStore
from magi.scheduler.contracts import ScheduledTargetType

from .test_derived_assertion_rules import _EvidenceEventStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dummy_context() -> Any:
    return MagicMock()


def _build_mock_unified(store: L2CognitionStore, db_path: str) -> Any:
    catalog_mock = MagicMock()
    catalog_mock.db_path = db_path

    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = store

    unified = MagicMock()
    unified.l1 = _EvidenceEventStore()
    unified.l2_entity_catalog = catalog_mock
    unified.l2_pipeline = pipeline_mock
    return unified


def _build_config(
    *,
    l2_enabled: bool = True,
    derive_schedule_enabled: bool = True,
    interest_aggregation_enabled: bool = True,
    shadow_conflict_notification_enabled: bool = True,
    interest_observation_threshold: int = 3,
) -> Any:
    l2_cfg = MemoryL2Settings(
        enabled=l2_enabled,
        derive_schedule_enabled=derive_schedule_enabled,
        interest_aggregation_enabled=interest_aggregation_enabled,
        shadow_conflict_notification_enabled=shadow_conflict_notification_enabled,
        interest_observation_threshold=interest_observation_threshold,
    )
    memory_cfg = SimpleNamespace(l2=l2_cfg)
    return SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))


async def _seed_interested_in_edge(
    store: L2CognitionStore,
    *,
    object_id: str,
    event_ids: list[str],
    entity_id: str = "user:local_user",
) -> None:
    now = time.time()
    for i, eid in enumerate(event_ids):
        await store.upsert_knowledge_edge(
            subject_id=entity_id,
            subject_type="person",
            predicate="INTERESTED_IN",
            object_id=object_id,
            object_type="topic",
            evidence_event_ids=[eid],
            confidence=0.8,
            observed_at=now + i * 86_400,
            source_type="chrome_history",
        )


async def _seed_canonical_name(
    store: L2CognitionStore,
    *,
    entity_id: str,
    canonical_name: str,
    entity_type: str = "topic",
) -> None:
    from magi.core.sqlite import sqlite_connection_async
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


def _candidate(
    *,
    trait_value: str,
    source_domain: str,
    evidence_event: str,
    entity_id: str = "user:local_user",
    trait_name: str = "music_preference",
    target_id: str = "topic:jazz",
) -> dict[str, Any]:
    ts = 1_710_000_000.0
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
        "first_inferred_at": ts,
        "last_validated_at": ts,
        "target_entity_id": target_id,
        "target_entity_type": "topic",
        "target_scope": "entity_bound",
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "decay_anchor_at": ts,
        "context_ref_id": "",
        "expires_at": None,
        "memory_subdomain": "",
        "natural_summary": "",
    }


async def _setup_shadow(store: L2CognitionStore, *, entity_id: str = "user:local_user") -> tuple[str, str]:
    auth_id = await store.upsert_assertion_candidate(
        _candidate(trait_value="classical", source_domain="user_authored",
                   evidence_event="evt-auth-derive-1", entity_id=entity_id)
    )
    shadow_id = await store.upsert_assertion_candidate(
        _candidate(trait_value="jazz", source_domain="external_activity",
                   evidence_event="evt-inferred-derive-1", entity_id=entity_id,
                   target_id="topic:jazz")
    )
    # Bump inferred_at so it's newer than the authoritative
    from magi.core.sqlite import sqlite_connection_async
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE tom_trait_assertions SET first_inferred_at = 1710000100.0 WHERE assertion_id = ?",
            (shadow_id,),
        )
        await db.commit()
    return auth_id, shadow_id


def _notification_store(tmp_path) -> tuple[NotificationStore, NotificationService]:
    ns = NotificationStore(str(tmp_path / "notifications.db"))
    ns.ensure_schema()
    return ns, NotificationService(store=ns)


# ---------------------------------------------------------------------------
# Test 1 — Enum membership
# ---------------------------------------------------------------------------

def test_scheduled_target_type_includes_memory_l2_derive():
    """MEMORY_L2_DERIVE must be a valid ScheduledTargetType member."""
    assert ScheduledTargetType.MEMORY_L2_DERIVE == "memory_l2_derive"
    assert ScheduledTargetType("memory_l2_derive") is ScheduledTargetType.MEMORY_L2_DERIVE


# ---------------------------------------------------------------------------
# Test 2 — Contrib registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_l2_derive_contrib_registers_handler_and_schedule():
    """L2DeriveScheduleContrib wires derive and correction intervals."""
    from magi.memory.l2.derive_schedule import (
        CORRECTION_DERIVATION_SWEEP_INTERVAL_SECONDS,
        L2DeriveScheduleContrib,
        SCHEDULE_ID_L2_CORRECTION_DERIVE,
        SCHEDULE_ID_L2_DERIVE,
        TARGET_KEY_L2_CORRECTION_DERIVE,
        TARGET_KEY_L2_DERIVE,
    )

    registered_handlers: dict[ScheduledTargetType, Any] = {}
    scheduled_intervals: list[dict[str, Any]] = []

    class FakeScheduler:
        def register_handler(self, target_type, handler):
            registered_handlers[target_type] = handler

        async def schedule_interval(self, *, schedule_id, target_type, target_key, seconds, target_payload):
            scheduled_intervals.append({
                "schedule_id": schedule_id,
                "target_type": target_type,
                "target_key": target_key,
                "seconds": seconds,
            })

        async def unschedule(self, schedule_id, *, target_type, target_key):
            pass

    l2_cfg = MemoryL2Settings(derive_schedule_interval_seconds=21_600.0)
    cfg_mock = SimpleNamespace(agent=SimpleNamespace(memory=SimpleNamespace(l2=l2_cfg)))

    contrib = L2DeriveScheduleContrib()
    with patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock):
        await contrib.register_schedules(FakeScheduler())

    assert ScheduledTargetType.MEMORY_L2_DERIVE in registered_handlers
    assert callable(registered_handlers[ScheduledTargetType.MEMORY_L2_DERIVE])

    assert len(scheduled_intervals) == 2
    si = next(
        item for item in scheduled_intervals if item["schedule_id"] == SCHEDULE_ID_L2_DERIVE
    )
    assert si["schedule_id"] == SCHEDULE_ID_L2_DERIVE
    assert si["target_type"] == ScheduledTargetType.MEMORY_L2_DERIVE
    assert si["target_key"] == TARGET_KEY_L2_DERIVE
    assert si["seconds"] == 21_600.0
    correction = next(
        item
        for item in scheduled_intervals
        if item["schedule_id"] == SCHEDULE_ID_L2_CORRECTION_DERIVE
    )
    assert correction["target_type"] == ScheduledTargetType.MEMORY_L2_DERIVE
    assert correction["target_key"] == TARGET_KEY_L2_CORRECTION_DERIVE
    assert correction["seconds"] == CORRECTION_DERIVATION_SWEEP_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# Test 3 — Interest aggregation surfaces in snapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_interest_surfaces_in_canonical_user_snapshot(tmp_path):
    """Seeded canonical-user INTERESTED_IN edges appear as inferred preference_profile in the snapshot."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    await _seed_interested_in_edge(store, object_id="topic:rust", event_ids=["r1", "r2", "r3"])
    await _seed_canonical_name(store, entity_id="topic:rust", canonical_name="Rust")

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_config(shadow_conflict_notification_enabled=False)

    from magi.memory.l2.derive_schedule import handle_l2_derive
    schedule_portrait_refresh = AsyncMock()

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(
            _make_dummy_context(),
            portrait_refresh_scheduler=schedule_portrait_refresh,
        )

    assert result.success is True
    assert result.message == "derive_ok"
    assert result.stats.get("interest_topics_aggregated", 0) >= 1
    schedule_portrait_refresh.assert_awaited_once_with(unified_mock, "local_user")

    snapshot = await store.get_tom_snapshot(entity_id="user:local_user", entity_type="user")
    assert snapshot is not None
    preferences = snapshot.get("preferences") or {}
    assert "interest.rust" in preferences
    assert preferences["interest.rust"]["source_tier"] == "inferred"
    assert await store.get_tom_snapshot(entity_id="user:self", entity_type="user") is None


# ---------------------------------------------------------------------------
# Test 4 — Shadow produces a conflict notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_emits_shadow_conflict_notification(tmp_path):
    """A seeded shadow assertion produces a profile_conflict notification."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    await _setup_shadow(store, entity_id="user:local_user")

    ns, svc = _notification_store(tmp_path)

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_config(interest_aggregation_enabled=False)

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
        # Both imports are inline (local) inside the handler, patch at their canonical location
        patch("magi.notifications.store.get_notification_store", return_value=ns),
        patch("magi.notifications.service.NotificationService", return_value=svc),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.stats.get("shadow_notifications_emitted", 0) >= 1
    assert len(ns.list_for_user("local_user")) == 1
    assert ns.list_for_user("default_user") == []


# ---------------------------------------------------------------------------
# Test 5 — interest_aggregation_enabled=False gates aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_interest_when_disabled(tmp_path):
    """interest_aggregation_enabled=False: no interest topics aggregated."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    await _seed_interested_in_edge(store, object_id="topic:go", event_ids=["g1", "g2", "g3"])
    await _seed_canonical_name(store, entity_id="topic:go", canonical_name="Go")

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_config(
        interest_aggregation_enabled=False,
        shadow_conflict_notification_enabled=False,
    )

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.stats.get("interest_topics_aggregated", 0) == 0
    # No snapshot row should exist
    snapshot = await store.get_tom_snapshot(entity_id="user:local_user", entity_type="user")
    preferences = (snapshot or {}).get("preferences") or {}
    assert not any(k.startswith("interest.") for k in preferences)


# ---------------------------------------------------------------------------
# Test 6 — shadow_conflict_notification_enabled=False gates notifications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_shadow_when_disabled(tmp_path):
    """shadow_conflict_notification_enabled=False: no notifications emitted."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    await _setup_shadow(store, entity_id="user:shadow_gate_test")

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_config(
        interest_aggregation_enabled=False,
        shadow_conflict_notification_enabled=False,
    )

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.stats.get("shadow_notifications_emitted", 0) == 0


# ---------------------------------------------------------------------------
# Test 7 — l2.enabled=False → l2_disabled_skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_when_l2_disabled():
    cfg_mock = _build_config(l2_enabled=False)
    from magi.memory.l2.derive_schedule import handle_l2_derive

    with patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.message == "l2_disabled_skip"


# ---------------------------------------------------------------------------
# Test 8 — derive_schedule_enabled=False → l2_derive_disabled_skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_when_derive_disabled():
    cfg_mock = _build_config(derive_schedule_enabled=False)
    from magi.memory.l2.derive_schedule import handle_l2_derive

    with patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.message == "l2_derive_disabled_skip"


# ---------------------------------------------------------------------------
# Test 9 — Unified memory unavailable → unified_memory_unavailable_skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_when_unified_memory_unavailable():
    cfg_mock = _build_config()
    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
        patch("magi.memory.l2.derive_schedule.get_unified_memory", side_effect=RuntimeError("no binding")),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.message == "unified_memory_unavailable_skip"


# ---------------------------------------------------------------------------
# Test 10 — l2_entity_catalog is None → l2_catalog_uninitialized_skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_when_catalog_uninitialized():
    cfg_mock = _build_config()
    unified_mock = MagicMock()
    unified_mock.l2_entity_catalog = None

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.message == "l2_catalog_uninitialized_skip"
