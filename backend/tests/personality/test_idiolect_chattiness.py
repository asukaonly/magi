from __future__ import annotations

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
