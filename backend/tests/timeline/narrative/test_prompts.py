"""Tests for diary narrative prompt builders."""

from __future__ import annotations

import pytest


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


@pytest.mark.parametrize(
    "count,excerpts",
    [
        (0, None),
        (1, None),
        (
            2,
            {
                "ep-2": ["second evidence"],
                "ep-1": ["first evidence A", "first evidence B"],
                "unrelated": ["DO NOT INCLUDE"],
            },
        ),
    ],
)
def test_diary_prompt_keeps_evidence_under_its_own_episode(count, excerpts):
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    episodes = [
        {
            "episode_id": f"ep-{i}",
            "time_start": 100 * i,
            "time_end": 100 * i + 50,
            "label": f"label-{i}",
        }
        for i in range(1, count + 1)
    ]
    prompt = build_diary_narrative_user_prompt(
        scale="day",
        period_start=0,
        period_end=86400,
        episodes=episodes,
        excerpts_by_episode=excerpts,
    )
    blocks = prompt.split("- id=")[1:]
    assert len(blocks) == count
    for index, block in enumerate(blocks, start=1):
        assert block.startswith(f"ep-{index} ·")
        assert f"label-{index}" in block
        expected = (excerpts or {}).get(f"ep-{index}", [])
        for evidence in expected:
            assert f"事件证据：{evidence}" in block
        for other, evidence_list in (excerpts or {}).items():
            if other != f"ep-{index}":
                for evidence in evidence_list:
                    assert evidence not in block
    assert "DO NOT INCLUDE" not in prompt
    if not excerpts:
        assert "事件证据" not in prompt
    if count == 0:
        assert "slices 返回空数组" in prompt


@pytest.mark.parametrize("ids", [["uuid-1", "ulid-2", "ep-x"], ["uuid-1", None, ""]])
def test_short_id_mapping_preserves_episode_fields_and_input(ids):
    from copy import deepcopy
    from magi.timeline.narrative.prompts import assign_short_ids

    episodes = [{"episode_id": value, "label": f"label-{index}"} for index, value in enumerate(ids)]
    original = deepcopy(episodes)
    relabeled, mapping = assign_short_ids(episodes)
    assert relabeled == [
        {"episode_id": f"e{index+1}", "label": f"label-{index}"} for index in range(3)
    ]
    assert mapping == {f"e{index+1}": value for index, value in enumerate(ids) if value}
    assert episodes == original
