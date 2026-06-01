"""P3.4: persona journal voice-drift guard.

A reflection that contains multiple vocab_avoided phrases is the persona
drifting out of character. Because past reflections feed into future
system prompts via "# Internal Reflections", a drifted entry becomes
the next call's few-shot anchor — the drift then compounds. The guard
drops such entries instead of persisting them.
"""

from __future__ import annotations

from magi.personality.loader import Idiolect, PersonalityConfig
from magi.personality.persona_journal_service import _detect_voice_drift


def _config(avoided: list[str]) -> PersonalityConfig:
    return PersonalityConfig(
        name="七号",
        idiolect=Idiolect(vocab_avoided=avoided),
    )


def test_no_avoided_vocab_returns_none() -> None:
    config = _config([])
    drift = _detect_voice_drift("anything goes here", config)
    assert drift is None


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


def test_two_avoided_hits_triggers_drift() -> None:
    config = _config(["您好", "请问有什么可以帮您", "非常感谢", "希望这对你有帮助"])
    text = "您好，请问有什么可以帮您。今天和用户聊了很多。"
    drift = _detect_voice_drift(text, config)
    assert drift is not None
    assert "您好" in drift
    assert "请问有什么可以帮您" in drift


def test_three_or_more_hits_still_triggers() -> None:
    config = _config(["您好", "非常感谢", "希望这对你有帮助"])
    text = "您好。非常感谢你的提问。希望这对你有帮助。"
    drift = _detect_voice_drift(text, config)
    assert drift is not None
    assert len(drift) == 3


def test_avoided_phrase_must_match_exactly() -> None:
    """Token-overlap is not used here — only exact substring matches count.
    This avoids false positives where vocab_avoided contains a fragment
    that happens to be a common Chinese substring."""
    config = _config(["请问有什么可以帮您", "非常感谢"])
    # Just "请问" alone shouldn't trigger — the avoided phrase is the longer one.
    text = "用户请问了一个问题，结果发现很有意思。"
    assert _detect_voice_drift(text, config) is None


def test_none_config_returns_none() -> None:
    assert _detect_voice_drift("anything", None) is None


def test_empty_avoided_list_returns_none() -> None:
    config = _config([])
    drift = _detect_voice_drift("您好 请问有什么可以帮您", config)
    assert drift is None


def test_whitespace_only_avoided_entries_are_ignored() -> None:
    config = _config(["", "   ", "您好", "请问有什么"])
    text = "您好。请问有什么。"
    drift = _detect_voice_drift(text, config)
    assert drift is not None
    assert "" not in drift
    assert "   " not in drift
