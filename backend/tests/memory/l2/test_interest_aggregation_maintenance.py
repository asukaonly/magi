"""Tests for interest aggregation after the DT-1 split.

The interest aggregation step now lives in ``handle_l2_derive``, NOT in
``handle_l2_entity_maintenance``.  This file verifies:

1. Config defaults — ``interest_aggregation_enabled=True``, ``interest_observation_threshold=3``.
2. Derive handler enabled — seeds INTERESTED_IN edges (≥ threshold), runs
   ``handle_l2_derive``, asserts the snapshot contains an inferred
   interest_profile assertion.
3. Derive handler disabled — same setup but ``interest_aggregation_enabled=False``;
   asserts no interest assertion appears in the snapshot.
4. Maintenance handler no longer emits ``interest_topics_aggregated`` in its stats.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.config.memory_models import MemoryL2Settings
from magi.identity.defaults import CANONICAL_LOCAL_USER
from magi.memory.l2.store import L2CognitionStore

from .test_derived_assertion_rules import _EvidenceEventStore


DEFAULT_USER_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_interested_in_edge(
    store: L2CognitionStore,
    *,
    object_id: str,
    event_ids: list[str],
    confidence: float = 0.8,
    entity_id: str = DEFAULT_USER_ENTITY_ID,
) -> None:
    """Seed one INTERESTED_IN edge row per unique event_id."""
    now = time.time()
    for i, eid in enumerate(event_ids):
        await store.upsert_knowledge_edge(
            subject_id=entity_id,
            subject_type="person",
            predicate="INTERESTED_IN",
            object_id=object_id,
            object_type="topic",
            evidence_event_ids=[eid],
            confidence=confidence,
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
    """Insert an entity_catalog row for name resolution."""
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


def _make_dummy_context() -> Any:
    """Return a minimal execution context — handler ignores it entirely."""
    return MagicMock()


def _build_mock_unified(store: L2CognitionStore, db_path: str) -> Any:
    """Build a mock unified-memory object that the derive handler can navigate."""
    catalog_mock = MagicMock()
    catalog_mock.db_path = db_path
    catalog_mock.embedding_service = None
    catalog_mock.edge_vector_index = None

    # l2_pipeline._cognition_store — the handler uses getattr chaining
    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = store

    unified = MagicMock()
    unified.l1 = _EvidenceEventStore()
    unified.l2_entity_catalog = catalog_mock
    unified.l2_pipeline = pipeline_mock
    return unified


def _build_mock_unified_for_maintenance(store: L2CognitionStore, db_path: str) -> Any:
    """Build a mock unified-memory object that the maintenance handler can navigate."""
    catalog_mock = MagicMock()
    catalog_mock.db_path = db_path
    catalog_mock.embedding_service = None
    catalog_mock.edge_vector_index = None

    counter_mock = MagicMock()
    counter_mock.prune_stale = AsyncMock(return_value=0)

    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = store

    unified = MagicMock()
    unified.l2_entity_catalog = catalog_mock
    unified.l2_promotion_counter = counter_mock
    unified.l2_pipeline = pipeline_mock
    return unified


def _build_derive_config_mock(*, enabled: bool) -> Any:
    """Build a minimal config mock for the derive handler."""
    l2_cfg = MemoryL2Settings(
        enabled=True,
        derive_schedule_enabled=True,
        interest_aggregation_enabled=enabled,
        interest_observation_threshold=3,
    )
    memory_cfg = SimpleNamespace(l2=l2_cfg)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))
    return cfg


def _build_maintenance_config_mock() -> Any:
    """Build a config mock for the maintenance handler (interest aggregation irrelevant)."""
    l2_cfg = MemoryL2Settings(
        enabled=True,
        maintenance_enabled=True,
        interest_aggregation_enabled=True,  # even if True, maintenance must not run it
        interest_observation_threshold=3,
        shadow_conflict_notification_enabled=False,
    )
    memory_cfg = SimpleNamespace(l2=l2_cfg)
    cfg = SimpleNamespace(agent=SimpleNamespace(memory=memory_cfg))
    return cfg


# ---------------------------------------------------------------------------
# Test 1 — Config default values
# ---------------------------------------------------------------------------

def test_memory_l2_settings_interest_defaults() -> None:
    """interest_aggregation_enabled defaults to True and threshold to 3."""
    settings = MemoryL2Settings()
    assert settings.interest_aggregation_enabled is True
    assert settings.interest_observation_threshold == 3


# ---------------------------------------------------------------------------
# Test 2 — Derive handler with interest_aggregation_enabled=True produces snapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_aggregates_interests_when_enabled(tmp_path):
    """Full derive handler run with enabled=True seeds INTERESTED_IN and finds inferred pref."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    # Seed 3 unique events → observation_count=3 → qualifies at threshold=3
    await _seed_interested_in_edge(
        store,
        object_id="topic:python",
        event_ids=["py-e1", "py-e2", "py-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:python", canonical_name="Python")

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_derive_config_mock(enabled=True)

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.message == "derive_ok"
    assert result.stats.get("interest_topics_aggregated", 0) >= 1

    # Verify the snapshot was written by the handler itself.
    snapshot = await store.get_tom_snapshot(entity_id=DEFAULT_USER_ENTITY_ID, entity_type="user")
    assert snapshot is not None, "tom_snapshots row not found — handler did not refresh"
    preferences = snapshot.get("preferences") or {}
    assert "interest.python" in preferences, (
        f"'interest.python' not found in snapshot preferences. Keys: {list(preferences.keys())}"
    )
    assert preferences["interest.python"]["source_tier"] == "inferred"


# ---------------------------------------------------------------------------
# Test 3 — Derive handler with interest_aggregation_enabled=False skips aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_derive_handler_skips_aggregation_when_disabled(tmp_path):
    """Derive handler run with enabled=False must NOT produce any inferred interest assertions."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    # Same seed as Test 2 — would qualify if aggregation ran
    await _seed_interested_in_edge(
        store,
        object_id="topic:rust",
        event_ids=["rs-e1", "rs-e2", "rs-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:rust", canonical_name="Rust")

    unified_mock = _build_mock_unified(store, db_path)
    cfg_mock = _build_derive_config_mock(enabled=False)

    from magi.memory.l2.derive_schedule import handle_l2_derive

    with (
        patch("magi.memory.l2.derive_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.derive_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_derive(_make_dummy_context())

    assert result.success is True
    assert result.stats.get("interest_topics_aggregated", 0) == 0

    # Snapshot must NOT contain any preference_profile assertion from aggregation
    snapshot = await store.refresh_entity_snapshot(entity_id=DEFAULT_USER_ENTITY_ID, entity_type="user")
    preferences = (snapshot or {}).get("preferences") or {}
    interest_keys = [k for k in preferences if k.startswith("interest.")]
    assert interest_keys == [], (
        f"Expected no interest preferences when aggregation disabled, got: {interest_keys}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Maintenance handler no longer emits interest_topics_aggregated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maintenance_handler_does_not_aggregate_interests(tmp_path):
    """After DT-1, maintenance must NOT emit interest_topics_aggregated in its stats."""
    db_path = str(tmp_path / "l2.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    # Seed qualifying edges — would have been aggregated in the old maintenance handler.
    await _seed_interested_in_edge(
        store,
        object_id="topic:golang",
        event_ids=["go-e1", "go-e2", "go-e3"],
    )
    await _seed_canonical_name(store, entity_id="topic:golang", canonical_name="Go")

    unified_mock = _build_mock_unified_for_maintenance(store, db_path)
    cfg_mock = _build_maintenance_config_mock()

    from magi.memory.l2.maintenance_schedule import handle_l2_entity_maintenance

    with (
        patch("magi.memory.l2.maintenance_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.maintenance_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_entity_maintenance(_make_dummy_context())

    assert result.success is True
    assert result.message == "maintenance_ok"
    # maintenance must NOT include these keys after the split
    assert "interest_topics_aggregated" not in result.stats, (
        f"maintenance still emits interest_topics_aggregated: {result.stats}"
    )
    assert "shadow_notifications_emitted" not in result.stats, (
        f"maintenance still emits shadow_notifications_emitted: {result.stats}"
    )


@pytest.mark.asyncio
async def test_maintenance_handler_skips_episode_consolidation_and_experience_promotion(tmp_path):
    """Entity maintenance is cleanup-only; episode/experience consolidation has its own target."""
    from magi.memory.l2.entities.maintenance import L2EntityMaintenanceStats
    from magi.memory.l2.experiences.models import ExperiencePromotionStats
    from magi.memory.l2.maintenance_schedule import handle_l2_entity_maintenance

    l2_store = MagicMock()
    l1_store = MagicMock()
    l3_store = MagicMock()
    l3_store.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 2, "errors": ["ep-b: timeout"]}
    )
    l3_store.get_episodic_summary_by_experience_id = AsyncMock(return_value=None)
    l3_store.generate_experience_summary = AsyncMock(return_value={
        "summary_id": "sum-exp-a",
        "content": "Experience recap",
    })

    catalog_mock = MagicMock()
    catalog_mock.db_path = str(tmp_path / "l2.db")
    catalog_mock.embedding_service = None
    catalog_mock.edge_vector_index = None

    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = l2_store

    unified_mock = MagicMock()
    unified_mock.l2_entity_catalog = catalog_mock
    unified_mock.l2_promotion_counter = None
    unified_mock.l2_pipeline = pipeline_mock
    unified_mock.l1 = l1_store
    unified_mock.l3 = l3_store

    maintenance_stats = L2EntityMaintenanceStats(episodes_promoted=2)
    maintenance_stats.promoted_episode_ids = ["ep-a", "ep-b"]
    fake_maintenance: Any = None

    class _FakeMaintenance:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal fake_maintenance
            self._cognition_store = kwargs["cognition_store"]
            self.run_kwargs: dict[str, Any] = {}
            fake_maintenance = self

        async def run(self, **kwargs: Any) -> L2EntityMaintenanceStats:
            self.run_kwargs = dict(kwargs)
            return maintenance_stats

    promote_mock = AsyncMock(return_value=ExperiencePromotionStats(
        candidates=1,
        promoted=1,
        promoted_experience_ids=["exp-a"],
    ))

    with (
        patch("magi.memory.l2.maintenance_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.maintenance_schedule.get_config", return_value=_build_maintenance_config_mock()),
        patch("magi.memory.l2.maintenance_schedule.L2EntityMaintenance", _FakeMaintenance),
        patch(
            "magi.memory.l2.experiences.promotion.promote_experiences_from_episodes",
            new=promote_mock,
        ),
    ):
        result = await handle_l2_entity_maintenance(_make_dummy_context())

    assert result.success is True
    assert fake_maintenance is not None
    assert fake_maintenance.run_kwargs["consolidate_episodes"] is False
    promote_mock.assert_not_awaited()
    l3_store.generate_missing_episodic_summaries.assert_not_awaited()
    l3_store.generate_experience_summary.assert_not_awaited()
    assert "episodic_summaries_generated" not in result.stats
    assert "experience_candidates" not in result.stats
