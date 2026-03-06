from __future__ import annotations

from pathlib import Path

import pytest

from magi.memory.scenario_prompts import ScenarioPromptsStore, initialize_default_prompts


@pytest.mark.asyncio
async def test_initialize_default_prompts_seeds_analysis_prompt(tmp_path: Path) -> None:
    db_path = tmp_path / "scenario_prompts.db"
    store = ScenarioPromptsStore(db_path=str(db_path))
    await store.init()

    await initialize_default_prompts(store, persona_name="Echo-01")

    default_analysis = await store.get_prompt("default", "analysis")
    echo_analysis = await store.get_prompt("Echo-01", "analysis")

    assert default_analysis is not None
    assert "Analysis Chat" in default_analysis
    assert echo_analysis is not None
    assert "State Uncertainty Clearly" in echo_analysis
