"""Accepted persona outcomes survive partial failure and replay without duplicate effects."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import aiosqlite
import pytest
import pytest_asyncio

from magi.personality.interaction_analyzer import DEFAULT_ANALYSIS
from magi.personality.loader import PersonalityConfig
from magi.personality.self_memory import SelfMemory
from magi.utils.runtime import RuntimePaths


@pytest_asyncio.fixture
async def persona(tmp_path, monkeypatch, ensure_db_schema):
    paths = RuntimePaths(base_dir=tmp_path)
    ensure_db_schema("growth_memory", paths.growth_db_path)
    ensure_db_schema("emotional", paths.emotional_db_path)
    monkeypatch.setattr("magi.personality.self_memory.get_runtime_paths", lambda: paths)
    memory = SelfMemory("test", persona_id="original", personality_config=PersonalityConfig(name="test"))
    await memory.init()
    return memory, paths


async def _apply(memory, outcome_id="accepted:one", persona_id="original"):
    return await memory.process_turn_outcome(
        outcome_id=outcome_id, persona_id=persona_id, user_id="user:one",
        user_message="This is a synthetic test.",
        analysis=replace(DEFAULT_ANALYSIS, milestone_keys=["trust_earned"]),
        milestone_conditions={"trust_earned": "Synthetic trust evidence"},
    )


async def _rows(path, sql, args=()):
    async with aiosqlite.connect(path) as db:
        return await (await db.execute(sql, args)).fetchall()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_target", ["growth", "emotional"])
async def test_partial_target_failure_rolls_back_and_restart_finishes_once(persona, failed_target):
    memory, paths = persona
    failing_path = paths.growth_db_path if failed_target == "growth" else paths.emotional_db_path
    original_state = await _rows(paths.emotional_db_path, "SELECT * FROM emotional_state")
    original_statistics = await _rows(paths.growth_db_path, "SELECT * FROM growth_statistics")
    async with aiosqlite.connect(failing_path) as db:
        await db.execute("""CREATE TRIGGER reject_receipt BEFORE INSERT ON persona_outcome_receipts
                            BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END""")
        await db.commit()
    with pytest.raises(aiosqlite.IntegrityError, match="synthetic receipt failure"):
        await _apply(memory)
    assert await _rows(paths.emotional_db_path, "SELECT * FROM emotional_events") == []
    assert await _rows(paths.emotional_db_path, "SELECT * FROM emotional_state") == original_state
    assert await _rows(failing_path, "SELECT * FROM persona_outcome_receipts") == []
    if failed_target == "growth":
        assert await _rows(paths.growth_db_path, "SELECT * FROM relationships") == []
        assert await _rows(paths.growth_db_path, "SELECT * FROM growth_statistics") == original_statistics
        assert await _rows(paths.growth_db_path, "SELECT * FROM milestones WHERE type != 'first_use'") == []
    async with aiosqlite.connect(failing_path) as db:
        await db.execute("DROP TRIGGER reject_receipt")
        await db.commit()
    reopened = SelfMemory("test", persona_id="original", personality_config=PersonalityConfig(name="test"))
    await reopened.init()
    assert await _apply(reopened)
    state = await _rows(paths.emotional_db_path, "SELECT * FROM emotional_state")
    assert not await _apply(reopened)
    assert await _rows(paths.emotional_db_path, "SELECT * FROM emotional_state") == state
    assert await _rows(paths.growth_db_path, "SELECT total_interactions, trust_level FROM relationships") == [(1, 0.52)]
    assert await _rows(paths.growth_db_path, "SELECT value FROM growth_statistics WHERE key='total_interactions'") == [("1",)]
    assert await _rows(paths.growth_db_path, "SELECT COUNT(*) FROM milestones WHERE title='trust_earned'") == [(1,)]
    assert await _rows(paths.emotional_db_path, "SELECT COUNT(*) FROM emotional_events") == [(1,)]


@pytest.mark.asyncio
async def test_concurrent_delivery_uses_database_receipts_not_process_cache(persona):
    memory, paths = persona
    second = SelfMemory("test", persona_id="original", personality_config=PersonalityConfig(name="test"))
    await second.init()
    await asyncio.gather(*[_apply(memory if i % 2 else second) for i in range(8)])
    assert await _rows(paths.growth_db_path, "SELECT total_interactions FROM relationships") == [(1,)]
    assert await _rows(paths.emotional_db_path, "SELECT COUNT(*) FROM emotional_events") == [(1,)]
    await _apply(second, outcome_id="accepted:second")
    assert await _rows(paths.growth_db_path, "SELECT total_interactions FROM relationships") == [(2,)]


@pytest.mark.asyncio
async def test_replay_after_persona_switch_updates_original_owner(persona):
    _, paths = persona
    switched = SelfMemory("new", persona_id="new-persona", personality_config=PersonalityConfig(name="new"))
    await switched.init()
    await _apply(switched, persona_id="original")
    assert await switched.get_relationship("user:one") is None
    await _apply(switched, persona_id="new-persona")
    assert await _rows(paths.growth_db_path, "SELECT persona_id, total_interactions FROM relationships ORDER BY persona_id") == [
        ("new-persona", 1), ("original", 1),
    ]
    assert await _rows(paths.emotional_db_path, "SELECT persona_id, COUNT(*) FROM emotional_events GROUP BY persona_id ORDER BY persona_id") == [
        ("new-persona", 1), ("original", 1),
    ]


@pytest.mark.asyncio
async def test_observer_trust_signal_is_exactly_once_per_outcome_effect(persona):
    memory, paths = persona
    await _apply(memory)
    values = dict(user_id="user:one", persona_id="original", outcome_id="accepted:one",
                  effect_id="0", signal_type="trust_delta", trust_delta=0.1, confidence=0.9)
    assert await memory.record_observer_relationship_signal(**values)
    assert not await memory.record_observer_relationship_signal(**values)
    assert await _rows(paths.growth_db_path, "SELECT trust_level FROM relationships") == [(0.62,)]
    async with aiosqlite.connect(paths.growth_db_path) as db:
        await db.execute("""CREATE TRIGGER reject_signal BEFORE INSERT ON persona_outcome_receipts
                            BEGIN SELECT RAISE(ABORT, 'synthetic signal failure'); END""")
        await db.commit()
    with pytest.raises(aiosqlite.IntegrityError, match="synthetic signal failure"):
        await memory.record_observer_relationship_signal(**{**values, "effect_id": "1"})
    assert await _rows(paths.growth_db_path, "SELECT trust_level FROM relationships") == [(0.62,)]


@pytest.mark.asyncio
async def test_full_clear_removes_receipts_with_their_effects(persona):
    memory, paths = persona
    await _apply(memory)
    await memory.clear_learned_state()
    for path in (paths.growth_db_path, paths.emotional_db_path):
        assert await _rows(path, "SELECT * FROM persona_outcome_receipts") == []
