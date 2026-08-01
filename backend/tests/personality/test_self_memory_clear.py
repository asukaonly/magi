"""Tests for clearing persona-learned state without deleting persona config."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import pytest

from _shared.sqlite_privacy import assert_sqlite_fragment_absent
from magi.personality.behavior_evolution import BehaviorEvolutionEngine
from magi.personality.emotional_state import EmotionalStateEngine
from magi.personality.growth_memory import GrowthMemoryEngine
from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState
from magi.personality.self_memory import SelfMemory


BEHAVIOR_SCHEMA = """
CREATE TABLE task_interactions (task_id TEXT PRIMARY KEY);
CREATE TABLE category_statistics (category TEXT PRIMARY KEY);
CREATE TABLE behavior_profiles (task_category TEXT PRIMARY KEY);
"""

EMOTIONAL_SCHEMA = """
CREATE TABLE emotional_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE emotional_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT
);
"""

GROWTH_SCHEMA = """
CREATE TABLE milestones (id TEXT PRIMARY KEY);
CREATE TABLE relationships (user_id TEXT PRIMARY KEY);
CREATE TABLE personality_evolution (id INTEGER PRIMARY KEY AUTOINCREMENT);
CREATE TABLE growth_statistics (key TEXT PRIMARY KEY);
"""


async def _prepare_database(path: Path, schema: str, inserts: str) -> None:
    async with aiosqlite.connect(path) as db:
        await db.executescript(schema)
        await db.executescript(inserts)
        await db.commit()


async def _table_count(path: Path, table_name: str) -> int:
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute(f"SELECT COUNT(*) FROM {table_name}")
        row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_clear_learned_state_removes_all_persona_rows_and_caches(
    tmp_path: Path,
) -> None:
    private_markers = {
        "behavior": "magi-behavior-private-marker-that-must-not-survive",
        "emotion": "magi-emotion-private-marker-that-must-not-survive",
        "growth": "magi-growth-private-marker-that-must-not-survive",
    }
    behavior_path = tmp_path / "behavior.db"
    emotional_path = tmp_path / "emotional.db"
    growth_path = tmp_path / "growth.db"
    await _prepare_database(
        behavior_path,
        BEHAVIOR_SCHEMA,
        f"""
        INSERT INTO task_interactions VALUES ('{private_markers["behavior"]}');
        INSERT INTO task_interactions VALUES ('task-b');
        INSERT INTO category_statistics VALUES ('chat');
        INSERT INTO behavior_profiles VALUES ('chat');
        """,
    )
    await _prepare_database(
        emotional_path,
        EMOTIONAL_SCHEMA,
        f"""
        INSERT INTO emotional_state VALUES (
            'current:a', '{json.dumps(EmotionalState().__dict__)}', 1.0
        );
        INSERT INTO emotional_state VALUES (
            'current:b', '{json.dumps(EmotionalState().__dict__)}', 1.0
        );
        INSERT INTO emotional_events (persona_id) VALUES ('{private_markers["emotion"]}');
        INSERT INTO emotional_events (persona_id) VALUES ('b');
        """,
    )
    await _prepare_database(
        growth_path,
        GROWTH_SCHEMA,
        f"""
        INSERT INTO milestones VALUES ('{private_markers["growth"]}');
        INSERT INTO relationships VALUES ('user-a');
        INSERT INTO personality_evolution DEFAULT VALUES;
        INSERT INTO growth_statistics VALUES ('total_interactions');
        """,
    )

    behavior = BehaviorEvolutionEngine(str(behavior_path), persona_id="a")
    emotion = EmotionalStateEngine(str(emotional_path), persona_id="a")
    growth = GrowthMemoryEngine(str(growth_path), persona_id="a")
    behavior._cache["chat"] = object()  # type: ignore[assignment]
    behavior._stats_cache["chat"] = object()  # type: ignore[assignment]
    emotion._current_state = EmotionalState(current_mood="happy")
    emotion._event_history.append(object())  # type: ignore[arg-type]
    growth._relationship_cache["user-a"] = object()  # type: ignore[assignment]
    growth._milestone_cache = [object()]  # type: ignore[list-item]

    config = PersonalityConfig(name="kept-persona")
    self_memory = SelfMemory(
        personality_name="kept-persona",
        personality_config=config,
    )
    self_memory._behavior_engine = behavior
    self_memory._emotion_engine = emotion
    self_memory._growth_engine = growth

    deleted = await self_memory.clear_learned_state()

    assert deleted == 12
    assert self_memory._personality_config is config
    assert behavior._cache == {}
    assert behavior._stats_cache == {}
    assert emotion._current_state is not None
    assert emotion._current_state.current_mood == "neutral"
    assert emotion._current_state.recent_active_trigger_ids == []
    assert emotion._event_history == []
    assert growth._relationship_cache == {}
    assert growth._milestone_cache is None
    for path, tables in (
        (
            behavior_path,
            ("task_interactions", "category_statistics", "behavior_profiles"),
        ),
        (emotional_path, ("emotional_state", "emotional_events")),
        (
            growth_path,
            (
                "milestones",
                "relationships",
                "personality_evolution",
                "growth_statistics",
            ),
        ),
    ):
        for table_name in tables:
            assert await _table_count(path, table_name) == 0
    assert_sqlite_fragment_absent(behavior_path, private_markers["behavior"])
    assert_sqlite_fragment_absent(emotional_path, private_markers["emotion"])
    assert_sqlite_fragment_absent(growth_path, private_markers["growth"])


@pytest.mark.asyncio
async def test_clear_learned_state_is_noop_when_evolution_is_disabled() -> None:
    self_memory = SelfMemory(
        personality_name="static",
        enable_evolution=False,
        personality_config=PersonalityConfig(name="static"),
    )

    assert await self_memory.clear_learned_state() == 0
