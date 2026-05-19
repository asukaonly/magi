"""Trigger-driven emotional state updates (Plan B from the design discussion).

Before this change, EmotionalStateEngine moved every persona's mood by
the same amount per ``InteractionOutcome``. Seven and Echo handling the
same successful turn would both gain +0.15 mood — even though Seven
cringes at praise while Echo warms to it. By layering per-trigger
impacts on top of the shared outcome math, each persona's already-
configured signature triggers double as their emotional reactivity
profile.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
import pytest_asyncio

from magi.personality.emotional_contracts import EngagementLevel, InteractionOutcome
from magi.personality.emotional_state import EmotionalStateEngine
from magi.personality.loader import SignatureTrigger
from magi.personality.trigger_emotion_impact import (
    DEFAULT_TRIGGER_EMOTION_IMPACTS,
    resolve_emotion_impacts_for_ids,
    resolve_trigger_emotion_impact,
)


# ---------- Resolver unit tests ----------


def test_explicit_emotion_impact_wins_over_family_default() -> None:
    trigger = SignatureTrigger(
        trigger_id="absurdity",
        emotion_impact={"mood": 0.50, "stress": 0.10},
    )
    impact = resolve_trigger_emotion_impact(trigger)
    assert impact == {"mood": 0.50, "stress": 0.10}


def test_known_family_default_applies_when_impact_empty() -> None:
    trigger = SignatureTrigger(trigger_id="absurdity")
    impact = resolve_trigger_emotion_impact(trigger)
    assert impact == DEFAULT_TRIGGER_EMOTION_IMPACTS["absurdity"]


def test_unknown_trigger_id_returns_empty_impact() -> None:
    trigger = SignatureTrigger(trigger_id="never_seen_before_id")
    impact = resolve_trigger_emotion_impact(trigger)
    assert impact == {}


def test_resolver_strips_unknown_impact_keys() -> None:
    trigger = SignatureTrigger(
        trigger_id="x",
        emotion_impact={"mood": 0.1, "garbage": 99.0, "stress": -0.05},
    )
    impact = resolve_trigger_emotion_impact(trigger)
    assert impact == {"mood": 0.1, "stress": -0.05}


def test_resolve_emotion_impacts_for_ids_skips_unknown_ids() -> None:
    triggers = [
        SignatureTrigger(trigger_id="absurdity"),
        SignatureTrigger(trigger_id="hostility"),
    ]
    impacts = resolve_emotion_impacts_for_ids(
        ["absurdity", "ghost_trigger", "hostility"],
        triggers,
    )
    # Two known IDs resolve; one ghost ID is skipped.
    assert len(impacts) == 2


def test_resolve_emotion_impacts_for_ids_filters_empty_impacts() -> None:
    triggers = [
        SignatureTrigger(trigger_id="silent_one", emotion_impact={}),
        SignatureTrigger(trigger_id="absurdity"),
    ]
    impacts = resolve_emotion_impacts_for_ids(
        ["silent_one", "absurdity"],
        triggers,
    )
    # silent_one has no family default and no explicit impact -> dropped.
    assert len(impacts) == 1


# ---------- Integration tests for update_after_interaction ----------


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> EmotionalStateEngine:
    db_path = str(tmp_path / "emotional.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS emotional_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS emotional_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                previous_mood TEXT,
                new_mood TEXT,
                mood_delta REAL,
                energy_delta REAL,
                stress_delta REAL,
                cause TEXT,
                persona_id TEXT
            );
            """
        )
        await db.commit()
    eng = EmotionalStateEngine(db_path=db_path, persona_id="test")
    await eng.init()
    return eng


@pytest.mark.asyncio
async def test_no_triggered_impacts_preserves_outcome_math(engine: EmotionalStateEngine) -> None:
    """Baseline: with no trigger impacts the engine matches its prior behaviour."""
    before = await engine.get_current_state()
    before.energy_level = 0.6
    before.stress_level = 0.4
    before.updated_at = time.time()
    await engine._save_current_state()

    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.MEDIUM,
        complexity=0.5,
        triggered_emotion_impacts=None,
    )
    after = await engine.get_current_state()
    # Outcome-based math: success adds energy, drops stress.
    assert after.energy_level > 0.6
    assert after.stress_level < 0.4


@pytest.mark.asyncio
async def test_positive_trigger_impact_lifts_mood(engine: EmotionalStateEngine) -> None:
    """Absurdity-style trigger firing during a neutral interaction raises mood."""
    before = await engine.get_current_state()
    before.updated_at = time.time()
    await engine._save_current_state()
    baseline_mood = before.current_mood

    impacts = [{"mood": 0.30}]
    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.MEDIUM,
        complexity=0.3,
        triggered_emotion_impacts=impacts,
    )
    after = await engine.get_current_state()
    # With +0.30 mood impact added on top of SUCCESS the mood should move
    # toward a positive transition.
    assert after.current_mood != baseline_mood or after.mood_intensity > before.mood_intensity


@pytest.mark.asyncio
async def test_hostility_trigger_raises_stress(engine: EmotionalStateEngine) -> None:
    state = await engine.get_current_state()
    state.energy_level = 0.7
    state.stress_level = 0.2
    state.updated_at = time.time()
    await engine._save_current_state()

    # Hostility default = {"mood": -0.05, "stress": 0.15}
    impacts = [DEFAULT_TRIGGER_EMOTION_IMPACTS["hostility"]]
    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.MEDIUM,
        complexity=0.5,
        triggered_emotion_impacts=impacts,
    )
    after = await engine.get_current_state()
    # SUCCESS would normally cut stress; the hostility impact dominates and
    # pushes stress UP instead.
    assert after.stress_level > 0.2


@pytest.mark.asyncio
async def test_multiple_impacts_compound(engine: EmotionalStateEngine) -> None:
    state = await engine.get_current_state()
    state.stress_level = 0.5
    state.updated_at = time.time()
    await engine._save_current_state()

    impacts = [{"stress": 0.10}, {"stress": 0.10}, {"stress": 0.05}]
    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.MEDIUM,
        complexity=0.0,  # zero complexity → near-zero outcome math
        triggered_emotion_impacts=impacts,
    )
    after = await engine.get_current_state()
    # Three positive stress impacts (+0.25 total) overpower SUCCESS's
    # outcome-based stress drop.
    assert after.stress_level > 0.5


@pytest.mark.asyncio
async def test_crisis_trigger_drains_energy(engine: EmotionalStateEngine) -> None:
    state = await engine.get_current_state()
    state.energy_level = 0.8
    state.updated_at = time.time()
    await engine._save_current_state()

    impacts = [DEFAULT_TRIGGER_EMOTION_IMPACTS["crisis"]]
    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.HIGH,
        complexity=0.5,
        triggered_emotion_impacts=impacts,
    )
    after = await engine.get_current_state()
    # Crisis default: stress +0.20, energy -0.05. The energy hit overrides
    # the small SUCCESS energy lift.
    assert after.energy_level < 0.8
    assert after.stress_level > 0.0


@pytest.mark.asyncio
async def test_malformed_impact_values_silently_skipped(engine: EmotionalStateEngine) -> None:
    """Bad data from a buggy JSON should not crash the engine."""
    state = await engine.get_current_state()
    state.updated_at = time.time()
    await engine._save_current_state()

    impacts: list[dict[str, Any]] = [
        {"mood": "not_a_number"},
        {"stress": None},
        {"energy": 0.05},  # valid one
    ]
    await engine.update_after_interaction(
        outcome=InteractionOutcome.SUCCESS,
        user_engagement=EngagementLevel.MEDIUM,
        complexity=0.5,
        triggered_emotion_impacts=impacts,
    )
    # If we got here without raising the engine handled the malformed input.
    after = await engine.get_current_state()
    assert 0.0 <= after.energy_level <= 1.0
