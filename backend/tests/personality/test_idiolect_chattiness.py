from __future__ import annotations

from pathlib import Path

import pytest


from magi.personality.loader import PersonalityConfig


@pytest.mark.parametrize("extra, expected", [({"chattiness": 0.8}, 0.8), ({}, 0.5)])
def test_personality_config_parses_optional_chattiness(extra, expected):
    cfg = PersonalityConfig.from_dict({"name": "T", "idiolect": {"sentence_style": "x", **extra}})
    assert cfg.idiolect.chattiness == expected


_PRESETS = Path(__file__).resolve().parents[2] / "personalities"

_EXPECTED = {
    "en/nova_assistant.json": 0.50,
    "en/ember.json": 0.45,
    "en/halberd.json": 0.30,
    "en/jinx_hacker.json": 0.65,
    "zh/echo_ai_assistant.json": 0.35,
    "zh/sichen.json": 0.30,
    "zh/sumen_listener.json": 0.40,
    "zh/seven_hacker.json": 0.75,
}
