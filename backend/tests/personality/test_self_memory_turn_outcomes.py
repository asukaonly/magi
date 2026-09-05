"""Post-turn persona state persists without collecting unused behavior data."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import aiosqlite
import pytest

from magi.personality.interaction_analyzer import DEFAULT_ANALYSIS
from magi.personality.loader import PersonalityConfig
from magi.personality.models import SatisfactionLevel
from magi.personality.self_memory import SelfMemory
from magi.utils.runtime import RuntimePaths


@pytest.mark.asyncio
@pytest.mark.parametrize("has_historical_behavior", [False, True])
async def test_init_and_turn_outcome_preserve_behavior_data_and_update_persona_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ensure_db_schema,
    has_historical_behavior: bool,
) -> None:
    paths = RuntimePaths(base_dir=tmp_path)
    ensure_db_schema("emotional", paths.emotional_db_path)
    ensure_db_schema("growth_memory", paths.growth_db_path)
    historical_bytes = None
    if has_historical_behavior:
        ensure_db_schema("behavior_evolution", paths.behavior_db_path)
        async with aiosqlite.connect(paths.behavior_db_path) as db:
            await db.execute(
                """INSERT INTO behavior_profiles
                   (task_category, profile_json, updated_at, persona_id)
                   VALUES ('chat', '{"historical": true}', 1.0, 'test')"""
            )
            await db.commit()
        historical_bytes = paths.behavior_db_path.read_bytes()
    monkeypatch.setattr("magi.personality.self_memory.get_runtime_paths", lambda: paths)
    config = PersonalityConfig(name="test-persona")
    memory = SelfMemory(
        personality_name="test-persona",
        persona_id="test",
        personality_config=config,
    )
    await memory.init()
    initial_energy = (await memory.get_emotional_state()).energy_level

    updated = await memory.process_turn_outcome(
        user_id="user:test",
        user_message="Thanks for your help.",
        analysis=replace(
            DEFAULT_ANALYSIS,
            satisfaction=SatisfactionLevel.HIGH,
            milestone_keys=["trust_earned"],
        ),
        milestone_conditions={"trust_earned": "The user expressed trust."},
    )

    assert updated is True
    reloaded = SelfMemory(
        personality_name="test-persona",
        persona_id="test",
        personality_config=config,
    )
    await reloaded.init()
    relationship = await reloaded.get_relationship("user:test")
    assert relationship is not None
    assert relationship["total_interactions"] == 1
    assert (await reloaded.get_emotional_state()).energy_level != initial_energy
    assert "trust_earned" in {item["title"] for item in await reloaded.get_milestones()}
    if historical_bytes is None:
        assert not paths.behavior_db_path.exists()
    else:
        assert paths.behavior_db_path.read_bytes() == historical_bytes
