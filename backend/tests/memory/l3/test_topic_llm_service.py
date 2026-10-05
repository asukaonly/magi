"""Tests for thematic topic LLM service contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.l3.models import ThematicEvidenceItem, ThematicEvidencePack
from magi.memory.l3.topic_llm_service import TopicSummaryLLMService
from magi.llm.concurrency_limiter import LLMRequestPriority


def test_build_topic_evidence_pack_preserves_topic_and_ids() -> None:
    service = TopicSummaryLLMService()

    pack = service.build_evidence_pack(
        topic="job",
        events=[
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "content": "I want to switch jobs this year.",
                "importance_score": 0.8,
                "timestamp": 100.0,
            },
            {
                "event_id": "evt-2",
                "event_type": "AIResponse",
                "content": "The job market looks stronger for remote roles.",
                "importance_score": 0.6,
                "timestamp": 120.0,
            },
        ],
    )

    assert pack.topic == "job"
    assert pack.source_event_ids == ["evt-1", "evt-2"]
    assert pack.importance_aggregate == pytest.approx(0.7)
    assert pack.rule_hints["top_terms"] == ["market", "remote"]
    assert pack.rule_hints["high_importance_event_ids"] == ["evt-1", "evt-2"]
    assert pack.rule_hints["repeated_event_types"] == []


def test_topic_prompt_marks_first_context_question_as_non_evidence() -> None:
    service = TopicSummaryLLMService()
    question = "最近有什么内容，是你会忍不住反复看或听的？"
    pack = service.build_evidence_pack(
        topic="MyGO",
        events=[
            {
                "event_id": "evt-mygo",
                "event_type": "UserMessage",
                "content": "MyGO",
                "importance_score": 0.6,
                "timestamp": 100.0,
                "metadata_json": {
                    "interaction_kind": "first_context_story",
                    "first_context": {
                        "question_id": "repeating_content",
                        "question_text": question,
                    },
                },
            }
        ],
    )

    assert pack.events[0].content == "MyGO"
    assert pack.events[0].interpretation_context == {
        "kind": "first_context_question",
        "question_id": "repeating_content",
        "question_text": question,
        "evidence_semantics": "interpretation_context_only",
    }
    prompt = service.render_topic_prompt(pack)
    assert question in prompt
    assert "product-authored question is not evidence" in prompt


def test_parse_topic_llm_output_into_candidate() -> None:
    service = TopicSummaryLLMService()
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="switch jobs"),
            ThematicEvidenceItem(event_id="evt-2", event_type="AIResponse", content="job market"),
        ],
    )

    candidate, overrides = service.parse_llm_output(
        {
            "content": "Job planning recurred across multiple events and focused on remote roles.",
            "key_topics": ["job", "remote_roles"],
            "importance_aggregate": 0.75,
        },
        pack=pack,
    )

    assert candidate.summary_type == "thematic"
    assert candidate.summary_category == "topic"
    assert overrides["key_topics"] == ["job", "remote_roles"]
    assert overrides["importance_aggregate"] == 0.75


def test_parse_topic_llm_output_rejects_out_of_range_importance() -> None:
    service = TopicSummaryLLMService()
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="switch jobs"),
        ],
    )

    with pytest.raises(ValueError, match="importance_aggregate"):
        service.parse_llm_output(
            {
                "content": "Job planning recurred across multiple events.",
                "importance_aggregate": 1.5,
            },
            pack=pack,
        )


@pytest.mark.asyncio
async def test_generate_topic_candidate_falls_back_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TopicSummaryLLMService(llm_timeout_seconds=0.01)
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="switch jobs"),
            ThematicEvidenceItem(event_id="evt-2", event_type="AIResponse", content="job market"),
        ],
    )

    async def _slow_call(_pack):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.1)
        return "should never arrive"

    monkeypatch.setattr(service, "_call_topic_prose_model", _slow_call)

    result = await service.generate_topic_candidate(pack, fallback_summary="rule topic text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule topic text"


@pytest.mark.asyncio
async def test_generate_topic_candidate_keeps_prose_when_structure_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TopicSummaryLLMService()
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="我在考虑换工作"),
            ThematicEvidenceItem(event_id="evt-2", event_type="AIResponse", content="远程岗位更值得先看"),
        ],
    )

    class _FakeBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            if kwargs.get("json_mode"):
                return SimpleNamespace(content="not-json")
            return SimpleNamespace(content="围绕换工作的话题，重点一直落在远程岗位和成长空间上。")

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _FakeBridge()))

    result = await service.generate_topic_candidate(pack, fallback_summary="rule topic text")

    assert result.used_fallback is False
    assert result.candidate.content == "围绕换工作的话题，重点一直落在远程岗位和成长空间上。"
    assert result.summary_overrides["key_topics"] == []


@pytest.mark.asyncio
async def test_call_topic_model_parses_json_from_llm_target(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TopicSummaryLLMService()
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="switch jobs"),
        ],
    )

    class _FakeBridge:
        async def chat_response(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(content='{"content":"LLM topic summary","key_topics":["job_search"]}')

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _FakeBridge()))

    payload = await service._call_topic_model(pack)

    assert payload == {"content": "LLM topic summary", "key_topics": ["job_search"]}


@pytest.mark.asyncio
async def test_call_topic_model_uses_low_priority_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TopicSummaryLLMService()
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[
            ThematicEvidenceItem(event_id="evt-1", event_type="UserMessage", content="switch jobs"),
        ],
    )
    captured_kwargs: dict[str, object] = {}

    class _FakeBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            captured_kwargs.update(kwargs)
            return SimpleNamespace(content='{"content":"LLM topic summary","key_topics":["job_search"]}')

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _FakeBridge()))

    await service._call_topic_model(pack)

    assert captured_kwargs["priority"] is LLMRequestPriority.LOW


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "label"), [("zh", "Simplified Chinese (zh-CN)"), ("en", "English")]
)
async def test_topic_generation_forwards_language_and_structured_hints(
    monkeypatch, language, label
):
    import json
    from magi.i18n import language_context

    service = TopicSummaryLLMService()
    hints = {
        "top_terms": ["hint-canary-growth"],
        "high_importance_event_ids": ["evt-2"],
        "repeated_event_types": ["UserMessage"],
    }
    pack = ThematicEvidencePack(
        topic="job",
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        rule_hints=hints,
        events=[
            ThematicEvidenceItem(
                event_id="evt-1", event_type="UserMessage", content="I submitted an application."
            ),
            ThematicEvidenceItem(
                event_id="evt-2", event_type="UserMessage", content="The interview is on Friday."
            ),
        ],
    )
    calls = []

    class Bridge:
        async def chat_response(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                content=(
                    '{"key_topics": ["job_search"]}'
                    if kwargs["json_mode"]
                    else "Accepted topic prose."
                )
            )

    monkeypatch.setattr(
        service,
        "_get_llm_target",
        lambda: (SimpleNamespace(provider_name="test", model_name="test"), Bridge()),
    )
    with language_context(language):
        result = await service.generate_topic_candidate(pack, fallback_summary="fallback")
    assert result.used_fallback is False
    assert result.candidate.content == "Accepted topic prose."
    assert [call["json_mode"] for call in calls] == [False, True]
    for call in calls:
        assert label in call["system_prompt"]
        prompt = call["messages"][0]["content"]
        assert label in prompt
        evidence, _ = json.JSONDecoder().raw_decode(prompt.split("Evidence Pack:\n", 1)[1])
        assert evidence["rule_hints"] == hints
        assert [(row["event_id"], row["content"]) for row in evidence["events"]] == [
            ("evt-1", "I submitted an application."),
            ("evt-2", "The interview is on Friday."),
        ]
        assert call["priority"] is LLMRequestPriority.LOW
    assert (
        "Accepted User-Facing Summary:\nAccepted topic prose." in calls[1]["messages"][0]["content"]
    )
