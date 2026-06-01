"""Tests for the diary narrative LLM output schema."""

from __future__ import annotations

import pytest


def test_diary_narrative_output_from_valid_raw():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    raw = {
        "essence_prose": "周日。你大部分时间在 localhost 之间游走。",
        "narrative_style": "diary_2p",
        "slices": [
            {
                "episode_id": "ep-a",
                "slice_narrative": "下午你读了 timeline-domain 的架构文档。",
                "slice_sensory_detail": "窗外光线很柔。",
            },
            {
                "episode_id": "ep-b",
                "slice_narrative": "深夜又一次打开 GitHub。",
                "slice_sensory_detail": None,
            },
        ],
    }
    out = DiaryNarrativeOutput.from_raw(raw)
    assert out.essence_prose.startswith("周日")
    assert out.narrative_style == "diary_2p"
    assert len(out.slices) == 2
    assert out.slices[0].episode_id == "ep-a"
    assert out.slices[0].slice_sensory_detail == "窗外光线很柔。"
    assert out.slices[1].slice_sensory_detail is None


def test_diary_narrative_output_from_empty_raw():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    out = DiaryNarrativeOutput.from_raw({})
    assert out.essence_prose == ""
    assert out.narrative_style == "default"
    assert out.slices == []


def test_diary_narrative_output_skips_malformed_slices():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    raw = {
        "essence_prose": "x",
        "slices": [
            {"episode_id": "ep-a", "slice_narrative": "ok"},
            {"slice_narrative": "missing episode_id"},  # dropped
            "not a dict",  # dropped
            {"episode_id": "  ", "slice_narrative": "blank id"},  # dropped
        ],
    }
    out = DiaryNarrativeOutput.from_raw(raw)
    assert len(out.slices) == 1
    assert out.slices[0].episode_id == "ep-a"
