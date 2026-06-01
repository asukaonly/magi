"""Tests for TIMELINE_DIARY_NARRATIVE scenario registration."""

from __future__ import annotations

from magi.config.models import LLMScenario


def test_timeline_diary_narrative_scenario_value_exists():
    assert LLMScenario.TIMELINE_DIARY_NARRATIVE.value == "timeline_diary_narrative"


def test_timeline_diary_narrative_falls_back_to_core():
    from magi.llm.scenario_pool import _OPTIONAL_SCENARIO_FALLBACKS

    fallback = _OPTIONAL_SCENARIO_FALLBACKS.get(LLMScenario.TIMELINE_DIARY_NARRATIVE)
    assert fallback == LLMScenario.CORE, (
        "TIMELINE_DIARY_NARRATIVE must fall back to CORE so existing model configs work"
    )
