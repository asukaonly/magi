"""Tests for diary narrative prompt builders."""

from __future__ import annotations


def test_system_prompt_includes_forbidden_patterns():
    from magi.timeline.narrative.prompts import DIARY_NARRATIVE_SYSTEM_PROMPT

    assert "第二人称" in DIARY_NARRATIVE_SYSTEM_PROMPT
    # Forbidden patterns from spec §Voice and writing
    for forbidden in ("id", "markdown", "metric"):
        assert forbidden.lower() in DIARY_NARRATIVE_SYSTEM_PROMPT.lower(), (
            f"system prompt should mention forbidden: {forbidden}"
        )


def test_user_prompt_contains_all_episode_ids():
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    episodes = [
        {"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "morning"},
        {"episode_id": "ep-2", "time_start": 300.0, "time_end": 400.0, "label": "afternoon"},
    ]
    prompt = build_diary_narrative_user_prompt(
        scale="day",
        period_start=0.0,
        period_end=86400.0,
        episodes=episodes,
        place_hints=["家"],
    )
    assert "ep-1" in prompt
    assert "ep-2" in prompt
    assert "morning" in prompt
    assert "afternoon" in prompt
    assert "家" in prompt
    assert "day" in prompt.lower()


def test_user_prompt_handles_empty_episodes():
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    prompt = build_diary_narrative_user_prompt(
        scale="day",
        period_start=0.0,
        period_end=86400.0,
        episodes=[],
        place_hints=[],
    )
    # Should still produce something — orchestrator decides whether to call LLM at all
    assert prompt
    assert "day" in prompt.lower()
