"""Tests for active persona runtime cache helpers."""

from __future__ import annotations

import pytest

from magi.personality import active_persona
from magi.personality.loader import PersonalityConfig


@pytest.fixture(autouse=True)
def reset_active_persona_cache() -> None:
    active_persona.set_current_personality(active_persona.DEFAULT_PERSONALITY, config=None)


def test_active_persona_cache_updates_slug_and_config() -> None:
    config = PersonalityConfig()

    assert active_persona.set_current_personality("nova_assistant", config=config)

    assert active_persona.get_current_personality() == "nova_assistant"
    assert active_persona.get_current_personality_config() is config


@pytest.mark.asyncio
async def test_resolve_persona_config_uses_active_cache() -> None:
    config = PersonalityConfig()
    active_persona.set_current_personality("nova_assistant", config=config)

    resolved = await active_persona.resolve_persona_config("nova_assistant")

    assert resolved is config
