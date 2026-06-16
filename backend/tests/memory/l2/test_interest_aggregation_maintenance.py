"""Integration tests for interest aggregation wired into the L2 maintenance handler.

Tests:
1. Config defaults — ``interest_aggregation_enabled=True``, ``interest_observation_threshold=3``.
2. Handler enabled — seeds INTERESTED_IN edges (≥ threshold), runs the full
   ``handle_l2_entity_maintenance`` handler (with ``get_unified_memory`` and
   ``get_config`` patched), then asserts the snapshot contains an inferred
   preference_profile assertion.
3. Handler disabled — same setup, but ``interest_aggregation_enabled=False``; asserts
   no interest assertion appears in the snapshot.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.config.memory_models import MemoryL2Settings
from magi.memory.l2.store import L2CognitionStore


# ---------------------------------------------------------------------------
# Helpers shared with test_interest_aggregation.py
# ---------------------------------------------------------------------------

async def _seed_interested_in_edge(
    store: L2CognitionStore,
    *,
    object_id: str,
    event_ids: list[str],
    confidence: float = 0.8,
    entity_id: str = "user:self",
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
            observed_at=now + i * 0.001,
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
    """Build a mock unified-memory object that the handler can navigate."""
    # The handler reads: unified.l2_entity_catalog, unified.l2_promotion_counter, unified.l2_pipeline
    catalog_mock = MagicMock()
    catalog_mock.db_path = db_path
    catalog_mock.embedding_service = None
    catalog_mock.edge_vector_index = None

    counter_mock = MagicMock()
    counter_mock.prune_stale = AsyncMock(return_value=0)

    # l2_pipeline._cognition_store — the handler uses getattr chaining
    pipeline_mock = MagicMock()
    pipeline_mock._cognition_store = store

    unified = MagicMock()
    unified.l2_entity_catalog = catalog_mock
    unified.l2_promotion_counter = counter_mock
    unified.l2_pipeline = pipeline_mock
    return unified


def _build_config_mock(*, enabled: bool) -> Any:
    """Build a minimal config mock with both l2.enabled flags and interest settings."""
    l2_cfg = MemoryL2Settings(
        enabled=True,
        maintenance_enabled=True,
        interest_aggregation_enabled=enabled,
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
# Test 2 — Handler with interest_aggregation_enabled=True produces snapshot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maintenance_handler_aggregates_interests_when_enabled(tmp_path):
    """Full handler run with enabled=True seeds INTERESTED_IN and finds inferred pref."""
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
    cfg_mock = _build_config_mock(enabled=True)

    from magi.memory.l2.maintenance_schedule import handle_l2_entity_maintenance

    with (
        patch("magi.memory.l2.maintenance_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.maintenance_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_entity_maintenance(_make_dummy_context())

    assert result.success is True
    assert result.message == "maintenance_ok"
    # The handler itself calls refresh_entity_snapshot when topics_aggregated > 0,
    # so the aggregated interest must surface within the SAME maintenance run.
    assert result.stats.get("interest_topics_aggregated", 0) >= 1

    # Verify the snapshot was written by the handler itself: use the read-only
    # get_tom_snapshot (no rebuild) — if the handler's internal refresh_entity_snapshot
    # fired, the row is already in tom_snapshots and we read it back here without
    # triggering another refresh cycle.
    snapshot = await store.get_tom_snapshot(entity_id="user:self", entity_type="user")
    assert snapshot is not None, "tom_snapshots row not found — handler did not refresh"
    preferences = snapshot.get("preferences") or {}
    assert "interest.python" in preferences, (
        f"'interest.python' not found in snapshot preferences. Keys: {list(preferences.keys())}"
    )
    assert preferences["interest.python"]["source_tier"] == "inferred"


# ---------------------------------------------------------------------------
# Test 3 — Handler with interest_aggregation_enabled=False skips aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_maintenance_handler_skips_aggregation_when_disabled(tmp_path):
    """Full handler run with enabled=False must NOT produce any inferred interest assertions."""
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
    cfg_mock = _build_config_mock(enabled=False)

    from magi.memory.l2.maintenance_schedule import handle_l2_entity_maintenance

    with (
        patch("magi.memory.l2.maintenance_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.maintenance_schedule.get_config", return_value=cfg_mock),
    ):
        result = await handle_l2_entity_maintenance(_make_dummy_context())

    assert result.success is True
    assert result.stats.get("interest_topics_aggregated", 0) == 0

    # Snapshot must NOT contain any preference_profile assertion from aggregation
    snapshot = await store.refresh_entity_snapshot(entity_id="user:self", entity_type="user")
    preferences = (snapshot or {}).get("preferences") or {}
    interest_keys = [k for k in preferences if k.startswith("interest.")]
    assert interest_keys == [], (
        f"Expected no interest preferences when aggregation disabled, got: {interest_keys}"
    )


@pytest.mark.asyncio
async def test_maintenance_handler_generates_summaries_for_promoted_episodes(tmp_path):
    """Newly-promoted episodes trigger eager L3 episodic summary generation."""
    from magi.memory.l2.entities.maintenance import L2EntityMaintenanceStats
    from magi.memory.l2.maintenance_schedule import handle_l2_entity_maintenance

    l2_store = MagicMock()
    l1_store = MagicMock()
    l3_store = MagicMock()
    l3_store.generate_missing_episodic_summaries = AsyncMock(
        return_value={"generated": 2, "errors": ["ep-b: timeout"]}
    )

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

    class _FakeMaintenance:
        def __init__(self, **kwargs: Any) -> None:
            self._cognition_store = kwargs["cognition_store"]

        async def run(self, **_: Any) -> L2EntityMaintenanceStats:
            return maintenance_stats

    with (
        patch("magi.memory.l2.maintenance_schedule.get_unified_memory", return_value=unified_mock),
        patch("magi.memory.l2.maintenance_schedule.get_config", return_value=_build_config_mock(enabled=False)),
        patch("magi.memory.l2.maintenance_schedule.L2EntityMaintenance", _FakeMaintenance),
    ):
        result = await handle_l2_entity_maintenance(_make_dummy_context())

    assert result.success is True
    l3_store.generate_missing_episodic_summaries.assert_awaited_once()
    call_kwargs = l3_store.generate_missing_episodic_summaries.await_args.kwargs
    assert call_kwargs["l1_store"] is l1_store
    assert call_kwargs["l2_store"] is l2_store
    assert call_kwargs["episode_ids"] == ["ep-a", "ep-b"]
    assert result.stats["episodic_summaries_generated"] == 2
    assert result.stats["episodic_summary_errors"] == ["ep-b: timeout"]
