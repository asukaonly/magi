"""P3.4: persona journal voice-drift guard.

A reflection that contains multiple vocab_avoided phrases is the persona
drifting out of character. Because past reflections feed into future
system prompts via "# Internal Reflections", a drifted entry becomes
the next call's few-shot anchor — the drift then compounds. The guard
drops such entries instead of persisting them.
"""

from __future__ import annotations

import pytest

from magi.personality.loader import Idiolect, PersonalityConfig
from magi.personality.persona_journal_service import _detect_voice_drift


def _config(avoided: list[str]) -> PersonalityConfig:
    return PersonalityConfig(
        name="七号",
        idiolect=Idiolect(vocab_avoided=avoided),
    )


def test_clean_text_passes() -> None:
    config = _config(["您好", "请问有什么可以帮您", "非常感谢"])
    text = "今天聊得还行。技术问题有进展，对方的脾气也稳定一点。"
    assert _detect_voice_drift(text, config) is None


def test_single_avoided_hit_is_tolerated() -> None:
    """Single hit is treated as noise — "总的来说" can appear naturally in
    Chinese even when the persona normally avoids it."""
    config = _config(["总的来说", "您好", "请问有什么可以帮您"])
    text = "总的来说今天没什么特别的，技术那边推进一点。"
    assert _detect_voice_drift(text, config) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("今天还行", None),
        ("您好", None),
        ("您好，非常感谢", ["您好", "非常感谢"]),
        ("您好，非常感谢，希望这对你有帮助", ["您好", "非常感谢", "希望这对你有帮助"]),
    ],
)
def test_distinct_avoided_phrase_threshold(text, expected):
    assert _detect_voice_drift(text, _config(["您好", "非常感谢", "希望这对你有帮助"])) == expected


@pytest.mark.parametrize("config", [None, _config([])])
def test_absent_drift_policy_accepts_text(config):
    assert _detect_voice_drift("您好，非常感谢", config) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("非常感谢。用户请问了一个问题", None),
        ("非常感谢。请问有什么可以帮您", ["请问有什么可以帮您", "非常感谢"]),
    ],
)
def test_partial_phrase_cannot_supply_second_drift_hit(text, expected):
    assert _detect_voice_drift(text, _config(["请问有什么可以帮您", "非常感谢"])) == expected


def test_whitespace_only_avoided_entries_are_ignored() -> None:
    config = _config(["", "   ", "您好", "请问有什么"])
    text = "您好。请问有什么。"
    drift = _detect_voice_drift(text, config)
    assert drift is not None
    assert "" not in drift
    assert "   " not in drift
