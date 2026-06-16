"""Tests for the standout gate and consolidate_episodes integration."""

from __future__ import annotations

import time as _time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.l2.episode_formation import (
    EPISODE_MAX_GAP,
    EpisodeConsolidationStats,
    STANDOUT_MIN_DISTINCT_ENTITIES,
    STANDOUT_MIN_DURATION_SECONDS,
    STANDOUT_MIN_EVENTS,
    _passes_standout_gate,
    consolidate_episodes,
    episode_type_for_event,
)


# ─── episode_type_for_event ──────────────────────────────────────────

def test_episode_type_for_event_maps_user_message_to_conversation():
    assert episode_type_for_event("UserMessage") == "conversation"


def test_episode_type_for_event_maps_ai_response_to_conversation():
    assert episode_type_for_event("AIResponse") == "conversation"


def test_episode_type_for_event_maps_location_to_visit():
    assert episode_type_for_event("LocationVisit") == "visit"


def test_episode_type_for_event_maps_unknown_to_activity():
    assert episode_type_for_event("ActionExecuted") == "activity"
    assert episode_type_for_event("") == "activity"
    assert episode_type_for_event("SomethingNobodyDefined") == "activity"


def test_episode_type_for_event_returns_gap_table_keys():
    for event_type in ("UserMessage", "LocationVisit", "anything"):
        assert episode_type_for_event(event_type) in EPISODE_MAX_GAP


# ─── _passes_standout_gate ───────────────────────────────────────────

def _episode(**overrides):
    base = {
        "episode_id": "ep-1",
        "source_event_count": 10,
        "time_start": 0.0,
        "time_end": 60 * 60.0,  # 1 hour
        "primary_entity_ids": ["a", "b", "c"],
        "created_at": _time.time() - 3600,
        "status": "candidate",
        "episode_type": "activity",
    }
    base.update(overrides)
    return base


def test_standout_gate_passes_with_rich_episode():
    assert _passes_standout_gate(_episode()) is True


def test_standout_gate_rejects_few_events():
    assert _passes_standout_gate(_episode(source_event_count=STANDOUT_MIN_EVENTS - 1)) is False


def test_standout_gate_rejects_short_duration():
    ep = _episode(time_start=0.0, time_end=STANDOUT_MIN_DURATION_SECONDS - 1)
    assert _passes_standout_gate(ep) is False


def test_standout_gate_rejects_thin_entities():
    ep = _episode(primary_entity_ids=["only_one"])
    assert _passes_standout_gate(ep) is False


def test_standout_gate_handles_missing_fields():
    # Should not crash on missing or wrongly-typed fields
    assert _passes_standout_gate({}) is False
    assert _passes_standout_gate({"source_event_count": None}) is False
    assert _passes_standout_gate({
        "source_event_count": 99,
        "time_start": None,
        "time_end": None,
        "primary_entity_ids": "not-a-list",
    }) is False


# ─── consolidate_episodes integration ────────────────────────────────

@pytest.mark.asyncio
async def test_consolidate_promotes_and_marks_standout():
    """A mature, rich candidate gets promoted AND marked magi_standout."""
    now = _time.time()
    candidates = [
        _episode(
            episode_id="ep-rich",
            source_event_count=10,
            time_start=now - 7200,
            time_end=now - 3600,  # 1 hour duration
            primary_entity_ids=["a", "b", "c"],
            created_at=now - 7200,  # >30 min old
        ),
        _episode(
            episode_id="ep-thin",
            source_event_count=4,  # below STANDOUT_MIN_EVENTS but above MIN_EVENTS_TO_PROMOTE (3)
            time_start=now - 7200,
            time_end=now - 3600,
            primary_entity_ids=["a"],
            created_at=now - 7200,
        ),
    ]

    store = MagicMock()
    store.list_episodes = AsyncMock(side_effect=[
        candidates,         # for status="candidate"
        [],                 # for status="active"
        [],                 # for statuses=["candidate", "active"] (invalidate scan)
    ])
    store.update_episode = AsyncMock()
    store.list_episode_events = AsyncMock(return_value=[])
    store.add_episode_events = AsyncMock()

    stats = await consolidate_episodes(store)

    # Both candidates met the promotion gate (>=3 events, >=30 min old)
    assert stats.promoted == 2
    # Only the rich one met the standout gate (>=5 events AND >=20 min AND >=2 entities)
    assert stats.standouts == 1

    # Verify update_episode was called with magi_standout for ep-rich only
    rich_calls = [c for c in store.update_episode.await_args_list if c.kwargs.get("episode_id") == "ep-rich"]
    thin_calls = [c for c in store.update_episode.await_args_list if c.kwargs.get("episode_id") == "ep-thin"]
    assert any(call.kwargs.get("magi_standout") is True for call in rich_calls)
    assert all("magi_standout" not in call.kwargs for call in thin_calls)

    # Both newly-promoted episodes (standout AND non-standout) are exposed so the
    # caller can eagerly generate an L3 episodic summary for each.
    assert set(stats.promoted_episode_ids) == {"ep-rich", "ep-thin"}


@pytest.mark.asyncio
async def test_consolidate_exposes_promoted_ids_real_store(tmp_path):
    """Against a real L2CognitionStore: only mature candidates land in promoted_episode_ids."""
    import sqlite3

    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "l2.db")
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()

    now = _time.time()

    # Mature candidate: enough events + old enough → should promote.
    await store.create_episode(
        episode_id="ep-mature",
        episode_type="activity",
        time_start=now - 7200,
        time_end=now - 3600,
        primary_entity_ids=["a", "b", "c"],
        source_event_count=10,
    )
    # Fresh candidate: enough events but created_at is "now" → blocked by age gate.
    await store.create_episode(
        episode_id="ep-fresh",
        episode_type="activity",
        time_start=now - 600,
        time_end=now,
        primary_entity_ids=["a", "b"],
        source_event_count=10,
    )

    # Backdate the mature candidate so it clears MIN_AGE_TO_PROMOTE (created_at is
    # not an updatable field via the store API).
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE episodes SET created_at = ? WHERE episode_id = ?",
        (now - 7200, "ep-mature"),
    )
    conn.commit()
    conn.close()

    stats = await consolidate_episodes(store)

    assert "ep-mature" in stats.promoted_episode_ids
    assert "ep-fresh" not in stats.promoted_episode_ids
    assert stats.promoted == len(stats.promoted_episode_ids)
