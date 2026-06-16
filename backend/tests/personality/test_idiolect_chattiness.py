from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.personality.loader import Idiolect, PersonalityConfig


def test_idiolect_defaults_chattiness_to_half() -> None:
    assert Idiolect().chattiness == 0.5


def test_personality_config_from_dict_parses_chattiness() -> None:
    cfg = PersonalityConfig.from_dict(
        {"name": "T", "idiolect": {"sentence_style": "x", "chattiness": 0.8}}
    )
    assert cfg.idiolect.chattiness == 0.8


def test_personality_config_from_dict_missing_chattiness_defaults() -> None:
    cfg = PersonalityConfig.from_dict({"name": "T", "idiolect": {"sentence_style": "x"}})
    assert cfg.idiolect.chattiness == 0.5


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


@pytest.mark.skipif(not _PRESETS.exists(), reason="preset dir not present")
@pytest.mark.parametrize("rel,expected", list(_EXPECTED.items()))
def test_preset_has_expected_chattiness(rel: str, expected: float) -> None:
    data = json.loads((_PRESETS / rel).read_text(encoding="utf-8"))
    assert data["idiolect"]["chattiness"] == expected
