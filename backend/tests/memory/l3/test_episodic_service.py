"""Tests for EpisodicSummaryLLMService — fallback path (no LLM)."""

from __future__ import annotations

from types import SimpleNamespace

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
                event_type="SOURCE_EVENT",
                content="Chrome 浏览 v2ex 首页",
                timestamp=1700000500.0,
            ),
            EpisodicEvidenceItem(
                event_id="evt-b",
                event_type="SOURCE_EVENT",
                content="Chrome 浏览 Kimi 聊天页",
                timestamp=1700002000.0,
            ),
        ],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["generate_episodic_candidate", "generate_experience_review"])
@pytest.mark.parametrize("availability", ["disabled", "missing_pool", "enabled"])
async def test_generation_availability_preserves_evidence_and_controls_model_calls(
    monkeypatch, method, availability
):
    import json
    from unittest.mock import AsyncMock, MagicMock
    from magi.memory.l3.episodic_service import LLMProviderBridge

    pool = MagicMock()
    pool.get.return_value = SimpleNamespace(provider_name="fake", model_name="fake-model")
    bridge = AsyncMock(
        side_effect=lambda **kwargs: SimpleNamespace(
            content=(
                json.dumps(
                    {
                        "label": "Generated label",
                        "content": "Generated prose",
                        "narrative": "Generated prose",
                        "key_topics": [],
                        "key_entities": [],
                    }
                )
                if kwargs.get("json_mode")
                else "Generated prose"
            )
        )
    )
    monkeypatch.setattr(LLMProviderBridge, "chat_response", bridge)
    service = EpisodicSummaryLLMService(
        enabled=availability != "disabled",
        scenario_llm_pool=None if availability == "missing_pool" else pool,
    )
    result = await getattr(service, method)(
        _pack(), fallback_label="Fallback label", fallback_content="Fallback prose"
    )
    fallback = availability != "enabled"
    assert result.used_fallback is fallback
    assert (
        result.candidate.summary_category,
        result.candidate.summary_type,
        result.candidate.source_event_ids,
    ) == ("episodic", "thematic", ["evt-a", "evt-b"])
    assert result.candidate.content == ("Fallback prose" if fallback else "Generated prose")
    if fallback:
        assert result.candidate.insight_metadata == {
            "source_episode_id": "ep-1",
            "label": "Fallback label",
            "fallback": True,
        }
        bridge.assert_not_awaited()
        pool.get.assert_not_called()
    else:
        assert result.candidate.insight_metadata["label"] == "Generated label"
        assert result.candidate.insight_metadata.get("fallback") is not True
        assert bridge.await_count == (2 if method == "generate_episodic_candidate" else 1)


@pytest.mark.asyncio
async def test_keeps_prose_when_structure_fails():
    service = EpisodicSummaryLLMService(enabled=True, scenario_llm_pool=object())

    class _FakeBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            if kwargs.get("json_mode"):
                return SimpleNamespace(content="{not-json")
            return SimpleNamespace(
                content="这段经历主要是在 V2EX 和 Kimi 之间切换，围绕 AI 工具做轻量探索。"
            )

    service._get_llm_target = lambda: (SimpleNamespace(provider_name="fake", model_name="fake-model"), _FakeBridge())  # type: ignore[method-assign]

    result = await service.generate_episodic_candidate(
        _pack(),
        fallback_label="V2EX 与 Kimi",
        fallback_content="fallback content",
    )

    assert result.used_fallback is False
    assert (
        result.candidate.content
        == "这段经历主要是在 V2EX 和 Kimi 之间切换，围绕 AI 工具做轻量探索。"
    )
    assert result.candidate.insight_metadata["label"] == "V2EX 与 Kimi"
    assert result.candidate.insight_metadata.get("fallback") is not True


def test_parse_experience_review_output_truncates_long_fields():
    import json

    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    parsed = service._parse_experience_review_output(
        json.dumps(
            {
                "label": "日本旅行路线规划和动漫巡礼准备",
                "narrative": "你围绕日本夏季旅行持续整理路线。" * 40,
                "intent": "你想把交通、住宿和巡礼地点收束成可执行计划。" * 10,
                "outcome": "最终保留了更安静的目的地，并把东京到京都的路线先定下来。" * 10,
                "key_topics": ["travel", "anime"],
                "key_entities": [{"id": "place:japan", "label": "Japan"}],
            }
        )
    )

    assert parsed is not None
    assert parsed.label == "日本旅行路线规划和动漫巡礼准备"[:48]
    assert len(parsed.narrative) == 400
    assert len(parsed.intent) == 180
    assert len(parsed.outcome) == 180
    assert parsed.key_topics == ["travel", "anime"]
    assert parsed.key_entities == [{"id": "place:japan", "label": "Japan"}]


def test_parse_experience_review_output_rejects_missing_required_fields():
    import json

    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)

    assert service._parse_experience_review_output(json.dumps({"label": "日本旅行"})) is None
    assert (
        service._parse_experience_review_output(json.dumps({"narrative": "你整理了日本旅行。"}))
        is None
    )


@pytest.mark.asyncio
async def test_generate_experience_review_uses_single_json_call():
    service = EpisodicSummaryLLMService(enabled=True, scenario_llm_pool=object())
    calls: list[dict[str, object]] = []

    class _FakeBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            calls.append(dict(kwargs))
            return SimpleNamespace(
                content=(
                    '{"label":"日本旅行规划","narrative":"你先比较车票和住宿，'
                    '随后把东京、京都和巡礼地点串成一条更安静的路线。",'
                    '"intent":"你想把夏季日本旅行整理成可执行计划。",'
                    '"outcome":"路线初步收束，保留了更适合独处的目的地。",'
                    '"key_topics":["travel"],'
                    '"key_entities":[{"id":"place:japan","label":"Japan"}]}'
                )
            )

    service._get_llm_target = lambda: (  # type: ignore[method-assign]
        SimpleNamespace(provider_name="fake", model_name="fake-model"),
        _FakeBridge(),
    )

    result = await service.generate_experience_review(
        _pack(),
        fallback_label="fallback",
        fallback_content="fallback content",
    )

    assert result.used_fallback is False
    assert len(calls) == 1
    assert calls[0]["json_mode"] is True
    assert result.candidate.content.startswith("你先比较车票和住宿")
    assert result.candidate.insight_metadata["label"] == "日本旅行规划"
    assert result.candidate.insight_metadata["intent"] == "你想把夏季日本旅行整理成可执行计划。"
    assert (
        result.candidate.insight_metadata["outcome"] == "路线初步收束，保留了更适合独处的目的地。"
    )
    assert result.candidate.insight_metadata["key_topics"] == ["travel"]


def test_evidence_pack_builder_caps_and_sorts():
    """build_episodic_evidence_pack caps VERBATIM at max_events and sorts by timestamp asc."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {
            "event_id": "z",
            "timestamp": 30.0,
            "content": "third",
            "event_type": "T",
            "source": "chat_projector",
        },
        {
            "event_id": "a",
            "timestamp": 10.0,
            "content": "first",
            "event_type": "T",
            "source": "chat_projector",
        },
        {
            "event_id": "m",
            "timestamp": 20.0,
            "content": "second",
            "event_type": "T",
            "source": "chat_projector",
        },
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
    # Verbatim list capped at 2, sorted ascending by timestamp:
    assert [e.event_id for e in pack.events] == ["a", "m"]
    # source_event_ids covers all events, not just verbatim:
    assert pack.source_event_ids == ["a", "m", "z"]
    assert pack.source_event_count == 3


def test_evidence_pack_builder_skips_missing_event_id():
    """Events without an event_id are skipped from verbatim list."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {
            "event_id": "",
            "timestamp": 1.0,
            "content": "no id",
            "event_type": "T",
            "source": "chat_projector",
        },
        {
            "event_id": "good",
            "timestamp": 2.0,
            "content": "has id",
            "event_type": "T",
            "source": "chat_projector",
        },
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


@pytest.mark.parametrize("length", [199, 200, 201])
def test_evidence_pack_preserves_exact_prefix_at_content_limit(length):
    service = EpisodicSummaryLLMService(enabled=False)
    content = ("abcdefghijklmnopqrstuvwxyz0123456789" * 6)[:length]
    pack = service.build_episodic_evidence_pack(
        episode={"episode_id": "ep-content"},
        events=[
            {
                "event_id": "e1",
                "timestamp": 1.0,
                "content": content,
                "event_type": "T",
                "source": "chat_projector",
            }
        ],
    )
    assert [(event.event_id, event.content) for event in pack.events] == [
        ("e1", content if length <= 200 else content[:200] + "...")
    ]
    assert pack.source_event_ids == ["e1"]


def test_parse_output_valid():
    """_parse_output returns EpisodicSummaryLLMOutput for valid JSON."""
    import json

    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    raw = json.dumps(
        {
            "label": "技术探索",
            "content": "用户在 v2ex 和 Kimi 之间穿梭，探索 AI 工具。",
            "key_topics": ["AI", "社区"],
            "key_entities": [{"id": "software:v2ex", "label": "V2EX"}],
        }
    )
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


# ---------------------------------------------------------------------------
# New tests for folding, derived topics, prompt rendering
# ---------------------------------------------------------------------------


def test_chrome_history_folded_into_summary_line():
    """chrome_history events collapse into one folded group line."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {
            "event_id": "c1",
            "timestamp": 10.0,
            "content": "Chrome 浏览 v2ex 首页",
            "event_type": "SOURCE_EVENT",
            "source": "chrome_history",
        },
        {
            "event_id": "c2",
            "timestamp": 20.0,
            "content": "Chrome 浏览 Kimi 聊天页",
            "event_type": "SOURCE_EVENT",
            "source": "chrome_history",
        },
        {
            "event_id": "c3",
            "timestamp": 30.0,
            "content": "Chrome 浏览 v2ex 热门帖子（访问 2 次）",
            "event_type": "SOURCE_EVENT",
            "source": "chrome_history",
        },
    ]
    episode = {
        "episode_id": "ep",
        "episode_type": "activity",
        "time_start": 0.0,
        "time_end": 100.0,
        "primary_entity_ids": [],
        "primary_topic_keys": [],
    }
    pack = service.build_episodic_evidence_pack(episode=episode, events=events)
    # All chrome_history collapsed:
    assert pack.events == []
    assert len(pack.folded_groups) == 1
    line = pack.folded_groups[0]
    assert "浏览" in line
    assert "v2ex 首页" in line
    assert "Kimi 聊天页" in line
    assert "共 3 次" in line


def test_chat_events_stay_verbatim_with_role():
    """chat_projector events stay verbatim, with role label derived from author_type."""
    service = EpisodicSummaryLLMService(enabled=False, scenario_llm_pool=None)
    events = [
        {
            "event_id": "m1",
            "timestamp": 10.0,
            "content": "我在调记忆系统",
            "event_type": "user_message",
            "source": "chat_projector",
            "author_type": 1,
        },
        {
            "event_id": "m2",
            "timestamp": 20.0,
            "content": "你想看 L3 字段吗？",
            "event_type": "assistant_message",
            "source": "chat_projector",
            "author_type": 2,
        },
    ]
    episode = {
        "episode_id": "ep",
        "episode_type": "conversation",
        "time_start": 0.0,
        "time_end": 100.0,
        "primary_entity_ids": [],
        "primary_topic_keys": [],
    }
    pack = service.build_episodic_evidence_pack(episode=episode, events=events)
    assert len(pack.events) == 2
    assert pack.events[0].role == "user"
    assert pack.events[1].role == "assistant"
    assert pack.folded_groups == []


def test_derived_topics_rank_frequency_ahead_of_first_encounter():
    import json

    service = EpisodicSummaryLLMService(enabled=False)
    events = [
        {
            "event_id": f"e{i}",
            "timestamp": float(i),
            "content": "听歌",
            "source": "netease_music",
            "metadata_json": json.dumps({"structured_entity_hints": hints}),
        }
        for i, hints in enumerate(
            [
                [{"mention_text": "塞壬唱片", "entity_type": "organization"}],
                [{"canonical_name_hint": "Summer Fizz Pop", "entity_type": "media"}],
                [{"canonical_name_hint": "Summer Fizz Pop", "entity_type": "media"}],
            ]
        )
    ]
    pack = service.build_episodic_evidence_pack(
        episode={"episode_id": "ep", "primary_topic_keys": []}, events=events
    )
    assert pack.derived_topics == ["Summer Fizz Pop", "塞壬唱片"]


@pytest.mark.asyncio
@pytest.mark.parametrize("has_folded", [False, True])
async def test_generation_delivers_verbatim_and_optional_folded_evidence_to_provider(
    monkeypatch, has_folded
):
    from unittest.mock import AsyncMock, MagicMock
    from magi.memory.l3.episodic_service import LLMProviderBridge

    bridge = AsyncMock(
        side_effect=[SimpleNamespace(content="A grounded summary."), SimpleNamespace(content="{}")]
    )
    monkeypatch.setattr(LLMProviderBridge, "chat_response", bridge)
    pool = MagicMock()
    pool.get.return_value = SimpleNamespace(provider_name="fake", model_name="fake-model")
    service = EpisodicSummaryLLMService(scenario_llm_pool=pool)
    events = [
        {
            "event_id": "m1",
            "timestamp": 20.0,
            "content": "我在调记忆系统",
            "event_type": "user_message",
            "source": "chat_projector",
            "author_type": 1,
        }
    ]
    if has_folded:
        events.append(
            {
                "event_id": "c1",
                "timestamp": 10.0,
                "content": "Chrome 浏览 v2ex",
                "event_type": "SOURCE_EVENT",
                "source": "chrome_history",
            }
        )
    pack = service.build_episodic_evidence_pack(
        episode={"episode_id": "ep", "primary_entity_ids": ["software:v2ex", "user:local_user"]},
        events=events,
    )
    result = await service.generate_episodic_candidate(
        pack, fallback_label="Review", fallback_content="Fallback"
    )
    assert result.used_fallback is False
    assert result.candidate.source_event_ids == (["c1", "m1"] if has_folded else ["m1"])
    assert bridge.await_count == 2
    rendered = bridge.await_args_list[0].kwargs["messages"][0]["content"]
    assert ("Activity summary" in rendered) is has_folded
    assert ("浏览：v2ex（共 1 次）" in rendered) is has_folded
    assert "Notable events" in rendered
    assert "v2ex (software)" in rendered
    assert "user: 我在调记忆系统" in rendered
