from __future__ import annotations

from pathlib import Path


from magi.personality.loader import PersonalityConfig


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
