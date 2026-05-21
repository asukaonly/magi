"""Tests for EpisodicSummaryLLMService — fallback path (no LLM)."""

from __future__ import annotations

import pytest

from magi.memory.l3.episodic_service import EpisodicSummaryLLMService
from magi.memory.l3.models import EpisodicEvidenceItem, EpisodicEvidencePack


def _pack() -> EpisodicEvidencePack:
    return EpisodicEvidencePack(
        episode_id="ep-1",
        episode_type="activity",
        time_start=1700000000.0,
        time_end=1700003600.0,
        primary_entity_ids=["software:v2ex", "product:kimi"],
        primary_topic_keys=[],
        source_event_count=2,
        source_event_ids=["evt-a", "evt-b"],
        events=[
            EpisodicEvidenceItem(
                event_id="evt-a",
                event_type="SENSOR_EVENT",
                content="Chrome 浏览 v2ex 首页",
                timestamp=1700000500.0,
            ),
            EpisodicEvidenceItem(
                event_id="evt-b",
                event_type="SENSOR_EVENT",
                content="Chrome 浏览 Kimi 聊天页",
                timestamp=1700002000.0,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_fallback_when_disabled():
    """When service is disabled, returns the fallback candidate."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    result = await service.generate_episodic_candidate(
        _pack(),
        fallback_label="lab",
        fallback_content="cont",
    )
    assert result.used_fallback is True
    assert result.candidate.summary_category == "episodic"
    assert result.candidate.summary_type == "thematic"
    assert result.candidate.content == "cont"
    assert result.candidate.insight_metadata["source_episode_id"] == "ep-1"
    assert result.candidate.insight_metadata["label"] == "lab"
    assert result.candidate.insight_metadata.get("fallback") is True


@pytest.mark.asyncio
async def test_fallback_when_no_pool():
    """When no LLM pool is wired, also fallback."""
    service = EpisodicSummaryLLMService(enabled=True, scenario_llm_pool=None)
    result = await service.generate_episodic_candidate(
        _pack(), fallback_label="x", fallback_content="y",
    )
    assert result.used_fallback is True


def test_evidence_pack_builder_caps_and_sorts():
    """build_episodic_evidence_pack caps at max_events and sorts by timestamp asc."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {"event_id": "z", "timestamp": 30.0, "content": "third", "event_type": "T"},
        {"event_id": "a", "timestamp": 10.0, "content": "first", "event_type": "T"},
        {"event_id": "m", "timestamp": 20.0, "content": "second", "event_type": "T"},
    ]
    episode = {
        "episode_id": "ep",
        "episode_type": "activity",
        "time_start": 0.0,
        "time_end": 100.0,
        "primary_entity_ids": [],
        "primary_topic_keys": [],
    }
    pack = service.build_episodic_evidence_pack(episode=episode, events=events, max_events=2)
    # Sorted ascending, capped at 2:
    assert [e.event_id for e in pack.events] == ["a", "m"]
    assert pack.source_event_ids == ["a", "m"]
    assert pack.source_event_count == 2


def test_evidence_pack_builder_skips_missing_event_id():
    """Events without an event_id are skipped."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {"event_id": "", "timestamp": 1.0, "content": "no id", "event_type": "T"},
        {"event_id": "good", "timestamp": 2.0, "content": "has id", "event_type": "T"},
    ]
    episode = {
        "episode_id": "ep2",
        "episode_type": "activity",
        "time_start": 0.0,
        "time_end": 10.0,
        "primary_entity_ids": [],
        "primary_topic_keys": [],
    }
    pack = service.build_episodic_evidence_pack(episode=episode, events=events)
    assert len(pack.events) == 1
    assert pack.events[0].event_id == "good"


def test_evidence_pack_truncates_long_content():
    """Content longer than 200 chars gets truncated with ellipsis."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    long_content = "x" * 300
    events = [{"event_id": "e1", "timestamp": 1.0, "content": long_content, "event_type": "T"}]
    episode = {
        "episode_id": "ep3",
        "episode_type": "activity",
        "time_start": 0.0,
        "time_end": 10.0,
        "primary_entity_ids": [],
        "primary_topic_keys": [],
    }
    pack = service.build_episodic_evidence_pack(episode=episode, events=events)
    assert len(pack.events[0].content) <= 203  # 200 + "..."
    assert pack.events[0].content.endswith("...")


def test_fallback_source_event_ids_populated():
    """Fallback result carries source_event_ids from the pack."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    pack = _pack()
    # Access internal helper directly
    result = service._build_fallback_result(pack, "lbl", "the content")
    assert result.candidate.source_event_ids == ["evt-a", "evt-b"]


def test_parse_output_valid():
    """_parse_output returns EpisodicSummaryLLMOutput for valid JSON."""
    import json

    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    raw = json.dumps({
        "label": "技术探索",
        "content": "用户在 v2ex 和 Kimi 之间穿梭，探索 AI 工具。",
        "key_topics": ["AI", "社区"],
        "key_entities": [{"id": "software:v2ex", "label": "V2EX"}],
    })
    parsed = service._parse_output(raw)
    assert parsed is not None
    assert parsed.label == "技术探索"
    assert len(parsed.key_topics) == 2
    assert parsed.key_entities[0]["id"] == "software:v2ex"


def test_parse_output_missing_label_returns_none():
    """_parse_output returns None when label is missing."""
    import json

    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    raw = json.dumps({"content": "some content"})
    assert service._parse_output(raw) is None


def test_parse_output_invalid_json_returns_none():
    """_parse_output returns None for malformed JSON."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    assert service._parse_output("not json {{{") is None
