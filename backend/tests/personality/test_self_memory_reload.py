from __future__ import annotations

import pytest

from magi.personality.loader import PersonalityConfig
from magi.personality.self_memory import SelfMemory


def _config(name: str) -> PersonalityConfig:
    return PersonalityConfig.from_dict(
        {
            "name": name,
            "identity_core": {"identity_statement": f"{name} identity."},
        }
    )


@pytest.mark.asyncio
async def test_reload_personality_restores_previous_fields_when_loading_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_config = _config("Previous")
    memory = SelfMemory(
        "previous_persona",
        enable_evolution=False,
        personality_config=previous_config,
    )

    async def fail_load() -> None:
        raise RuntimeError("personality load failed")

    monkeypatch.setattr(memory, "_load_personality", fail_load)

    with pytest.raises(RuntimeError, match="personality load failed"):
        await memory.reload_personality("target_persona")

    assert memory.personality_name == "previous_persona"
    assert memory._personality_config is previous_config


@pytest.mark.asyncio
async def test_reload_personality_keeps_success_when_milestone_recording_fails() -> None:
    previous_config = _config("Previous")
    target_config = _config("Target")
    memory = SelfMemory(
        "previous_persona",
        enable_evolution=True,
        personality_config=previous_config,
    )

    class _FailingGrowthEngine:
        async def record_milestone(self, **kwargs) -> None:
            _ = kwargs
            raise RuntimeError("milestone write failed")

    memory._growth_engine = _FailingGrowthEngine()

    await memory.reload_personality(
        "target_persona",
        personality_config=target_config,
    )

    assert memory.personality_name == "target_persona"
    assert memory._personality_config is target_config
