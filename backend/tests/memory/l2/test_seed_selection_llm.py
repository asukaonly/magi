"""Tests for LLM-backed experience seed selection."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _seed() -> dict[str, object]:
    return {
        "seed_id": "seed-tokyo",
        "seed_type": "project",
        "status": "candidate",
        "title": "Repeated activity around tokyo",
        "description": "Candidate project seed.",
        "anchor_entity_ids": ["place:tokyo"],
        "anchor_place_ids": [],
        "anchor_topic_keys": ["travel"],
        "time_start": 100.0,
        "time_end": 400.0,
        "confidence": 0.84,
    }


def _evidence_pack() -> dict[str, object]:
    return {
        "seed": _seed(),
        "seed_evidence": [
            {"ref_type": "episode", "ref_id": "ep-ticket", "role": "trigger"},
        ],
        "trigger_episode_ids": ["ep-ticket"],
        "candidate_episodes": [
            {
                "episode_id": "ep-ticket",
                "label": "订新干线车票",
                "summary": "你查询了东京行的新干线票。",
                "time_start": 100.0,
                "time_end": 140.0,
                "primary_entity_ids": ["place:tokyo"],
                "primary_place_ids": [],
                "primary_topic_keys": ["travel"],
            },
            {
                "episode_id": "ep-hotel",
                "label": "筛东京住宿",
                "summary": "你对比了东京住宿位置。",
                "time_start": 200.0,
                "time_end": 280.0,
                "primary_entity_ids": ["place:tokyo"],
                "primary_place_ids": [],
                "primary_topic_keys": ["travel"],
            },
        ],
        "candidate_event_ids": ["evt-1", "evt-2"],
    }


class _FakeBridge:
    def __init__(self, payload: dict[str, object] | Exception) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    async def chat_response(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(dict(kwargs))
        if isinstance(self.payload, Exception):
            raise self.payload
        return SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))


@pytest.mark.asyncio
async def test_llm_selector_returns_validated_selection():
    from magi.memory.l2.experiences.seed_selection_llm import (
        ExperienceSeedSelectionLLMService,
    )

    bridge = _FakeBridge({
        "is_experience": True,
        "title": "东京行前规划",
        "one_sentence_review": "你围绕东京行程完成了车票和住宿的关键选择。",
        "included_episode_ids": ["ep-hotel", "ep-hallucinated"],
        "excluded_refs": [{"ref_type": "episode", "ref_id": "ep-ticket", "reason": "准备较早"}],
        "time_start": 999.0,
        "time_end": 1000.0,
        "confidence": 0.9,
        "reason": "LLM selected the concrete travel-planning arc.",
        "primary_entity_ids": ["place:tokyo", "made-up:entity"],
        "primary_place_ids": [],
        "primary_topic_keys": ["travel"],
    })
    service = ExperienceSeedSelectionLLMService(enabled=True, scenario_llm_pool=object())
    service._get_llm_target = lambda: (SimpleNamespace(provider_name="fake", model_name="fake"), bridge)  # type: ignore[method-assign]

    result = await service.select(dict(_seed()), _evidence_pack())

    assert result["is_experience"] is True
    assert result["title"] == "东京行前规划"
    assert result["included_episode_ids"] == ["ep-hotel"]
    assert result["time_start"] == 200.0
    assert result["time_end"] == 280.0
    assert result["primary_entity_ids"] == ["place:tokyo"]
    assert bridge.calls[0]["json_mode"] is True


@pytest.mark.asyncio
async def test_llm_selector_falls_back_on_failure():
    from dataclasses import asdict

    from magi.memory.l2.experiences.seed_selection import _default_selection
    from magi.memory.l2.experiences.seed_selection_llm import (
        ExperienceSeedSelectionLLMService,
    )

    bridge = _FakeBridge(RuntimeError("llm unavailable"))
    service = ExperienceSeedSelectionLLMService(enabled=True, scenario_llm_pool=object())
    service._get_llm_target = lambda: (SimpleNamespace(provider_name="fake", model_name="fake"), bridge)  # type: ignore[method-assign]

    result = await service.select(dict(_seed()), _evidence_pack())

    assert result == asdict(_default_selection(dict(_seed()), _evidence_pack()))


@pytest.mark.asyncio
async def test_llm_selector_all_hallucinated_ids_falls_back_to_default():
    from dataclasses import asdict

    from magi.memory.l2.experiences.seed_selection import _default_selection
    from magi.memory.l2.experiences.seed_selection_llm import (
        ExperienceSeedSelectionLLMService,
    )

    service = ExperienceSeedSelectionLLMService(enabled=True, scenario_llm_pool=object())
    service._get_llm_target = lambda: (  # type: ignore[method-assign]
        SimpleNamespace(provider_name="fake", model_name="fake"),
        _FakeBridge({
            "is_experience": True,
            "title": "幻觉选择",
            "one_sentence_review": "这一结果只包含不存在的 episode。",
            "included_episode_ids": ["missing-1", "missing-2"],
            "confidence": 0.9,
        }),
    )

    result = await service.select(dict(_seed()), _evidence_pack())

    assert result == asdict(_default_selection(dict(_seed()), _evidence_pack()))


@pytest.mark.asyncio
async def test_selector_rejection_is_not_replaced_by_default_selection():
    from magi.memory.l2.experiences.seed_selection import select_experience_from_seed
    from magi.memory.l2.experiences.seed_selection_llm import (
        ExperienceSeedSelectionLLMService,
    )

    service = ExperienceSeedSelectionLLMService(enabled=True, scenario_llm_pool=object())
    service._get_llm_target = lambda: (  # type: ignore[method-assign]
        SimpleNamespace(provider_name="fake", model_name="fake"),
        _FakeBridge({
            "is_experience": False,
            "title": "东京行前规划",
            "one_sentence_review": "",
            "included_episode_ids": [],
            "confidence": 0.2,
            "reason": "Low-information browsing does not form a real experience.",
        }),
    )

    selection = await select_experience_from_seed(
        seed=dict(_seed()),
        evidence_pack=_evidence_pack(),
        selector=service.select,
    )

    assert selection.is_experience is False
    assert selection.reason == "Low-information browsing does not form a real experience."
