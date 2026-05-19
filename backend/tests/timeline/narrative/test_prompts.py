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


def test_user_prompt_injects_event_excerpts_under_each_episode():
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    episodes = [
        {"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "morning"},
        {"episode_id": "ep-2", "time_start": 300.0, "time_end": 400.0, "label": "afternoon"},
    ]
    excerpts = {
        "ep-1": ["Anthropic sleep agency 论文导读", "Constitutional AI 后续讨论"],
        "ep-2": ["GitHub Copilot memory 设计文档"],
    }
    prompt = build_diary_narrative_user_prompt(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=episodes, place_hints=[],
        excerpts_by_episode=excerpts,
    )
    # All three excerpt strings appear verbatim
    assert "Anthropic sleep agency 论文导读" in prompt
    assert "Constitutional AI 后续讨论" in prompt
    assert "GitHub Copilot memory 设计文档" in prompt
    # Excerpts use the "事件证据" tag so the LLM can spot the section
    assert "事件证据" in prompt


def test_user_prompt_excerpts_optional_and_default_empty():
    """Excerpts are optional; absent dict should not break the builder."""
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    episodes = [{"episode_id": "ep-x", "time_start": 0.0, "time_end": 100.0, "label": "x"}]
    prompt = build_diary_narrative_user_prompt(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=episodes, place_hints=[],
    )
    assert "ep-x" in prompt
    assert "事件证据" not in prompt  # nothing to inject


def test_system_prompt_describes_event_excerpts_contract():
    """System prompt should brief the LLM on the 事件证据 section so it
    knows to ground prose in the snippets rather than the abstract labels."""
    from magi.timeline.narrative.prompts import DIARY_NARRATIVE_SYSTEM_PROMPT

    assert "事件证据" in DIARY_NARRATIVE_SYSTEM_PROMPT
