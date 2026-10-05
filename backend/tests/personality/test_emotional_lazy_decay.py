"""Tests for lazy time-based decay applied at ``get_current_state`` time."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import pytest_asyncio

from magi.personality.emotional_contracts import EmotionalConfig, MoodType
from magi.personality.emotional_state import (
    EmotionalStateEngine,
    apply_decay_to_state,
)
from magi.personality.models import EmotionalState


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> EmotionalStateEngine:
    db_path = str(tmp_path / "emotional.db")
    # The emotional_state DB schema is alembic-managed; create the minimal
    # table here so tests do not depend on a migration run.
    import aiosqlite
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


# ---------- Pure-function tests for apply_decay_to_state ----------


@pytest.mark.parametrize("elapsed", [0.0, -5.0])
def test_nonpositive_elapsed_time_preserves_complete_emotional_state(elapsed):
    from dataclasses import asdict

    state = EmotionalState(
        energy_level=0.7,
        stress_level=0.5,
        current_mood=MoodType.HAPPY.value,
        mood_intensity=0.8,
        social_state="engaged",
    )
    before = asdict(state)
    apply_decay_to_state(state, elapsed_minutes=elapsed, config=EmotionalConfig())
    assert asdict(state) == before


def test_apply_decay_drops_energy_linearly() -> None:
    cfg = EmotionalConfig(energy_decay_rate=0.01)
    state = EmotionalState(energy_level=0.8, stress_level=0.0)
    apply_decay_to_state(state, elapsed_minutes=10.0, config=cfg)
    assert state.energy_level == pytest.approx(0.7, rel=1e-3)


def test_apply_decay_recovers_stress() -> None:
    cfg = EmotionalConfig(stress_recovery_rate=0.05)
    state = EmotionalState(energy_level=1.0, stress_level=0.8)
    apply_decay_to_state(state, elapsed_minutes=4.0, config=cfg)
    # 4 minutes * 0.05/min = 0.2 stress recovered
    assert state.stress_level == pytest.approx(0.6, rel=1e-3)


def test_apply_decay_clamps_at_zero() -> None:
    cfg = EmotionalConfig(energy_decay_rate=0.5)
    state = EmotionalState(energy_level=0.1, stress_level=0.0)
    apply_decay_to_state(state, elapsed_minutes=10.0, config=cfg)
    assert state.energy_level == 0.0


def test_apply_decay_snaps_mood_back_to_neutral() -> None:
    cfg = EmotionalConfig()
    state = EmotionalState(
        current_mood=MoodType.HAPPY.value,
        mood_intensity=0.15,
        energy_level=1.0,
        stress_level=0.0,
    )
    # 60 minutes * (0.1 / 60) = 0.1 intensity drop → 0.05, below threshold
    apply_decay_to_state(state, elapsed_minutes=60.0, config=cfg)
    assert state.current_mood == MoodType.NEUTRAL.value
    assert state.mood_intensity == 0.5  # snaps to default


def test_apply_decay_keeps_high_intensity_mood() -> None:
    cfg = EmotionalConfig()
    state = EmotionalState(
        current_mood=MoodType.EXCITED.value,
        mood_intensity=0.9,
        energy_level=1.0,
        stress_level=0.0,
    )
    apply_decay_to_state(state, elapsed_minutes=5.0, config=cfg)
    # 5 minutes * 0.1/60 = 0.0083 → still high, mood persists
    assert state.current_mood == MoodType.EXCITED.value
    assert state.mood_intensity == pytest.approx(0.892, rel=1e-2)


# ---------- Integration tests for engine.get_current_state ----------


@pytest.mark.asyncio
async def test_get_current_state_skips_decay_when_recent(engine: EmotionalStateEngine) -> None:
    state = await engine.get_current_state()
    state.energy_level = 0.6
    state.updated_at = time.time() - 5  # 5 seconds ago, below threshold
    await engine._save_current_state()
    engine._current_state = None  # force reload

    refreshed = await engine.get_current_state()
    # Energy must not have decayed
    assert refreshed.energy_level == pytest.approx(0.6, rel=1e-6)


@pytest.mark.asyncio
async def test_get_current_state_applies_decay_after_threshold(engine: EmotionalStateEngine) -> None:
    state = await engine.get_current_state()
    state.energy_level = 0.7
    state.stress_level = 0.5
    state.updated_at = time.time() - 600  # 10 minutes ago
    await engine._save_current_state()
    engine._current_state = None

    refreshed = await engine.get_current_state()

    # 10 minutes * 0.01 = 0.1 energy drop
    assert refreshed.energy_level == pytest.approx(0.6, abs=0.02)
    # 10 minutes * 0.05 = 0.5 stress recovered; clamped at 0
    assert refreshed.stress_level == pytest.approx(0.0, abs=0.02)
    # updated_at refreshed to current time
    assert refreshed.updated_at == pytest.approx(time.time(), abs=2.0)


@pytest.mark.asyncio
async def test_get_current_state_decay_is_persisted(engine, monkeypatch):
    import json
    import sqlite3
    from dataclasses import asdict

    monkeypatch.setattr(time, "time", lambda: 1_800_000_000.0)
    state = await engine.get_current_state()
    state.energy_level = 0.8
    state.stress_level = 0.5
    state.updated_at = time.time() - 300
    await engine._save_current_state()
    engine._current_state = None
    first = await engine.get_current_state()
    assert first.energy_level == pytest.approx(0.75)
    assert first.stress_level == pytest.approx(0.25)
    assert first.updated_at == time.time()
    with sqlite3.connect(engine.db_path) as db:
        value, saved_at = db.execute(
            "SELECT value, updated_at FROM emotional_state WHERE key = ?", ("current:test",)
        ).fetchone()
    assert json.loads(value) == asdict(first)
    assert saved_at == time.time()
    engine._current_state = None
    assert asdict(await engine.get_current_state()) == asdict(first)
