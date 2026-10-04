"""Tests for temporal L3 evidence-pack and LLM service contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack
from magi.memory.l3.summary_store import _temporal_fallback_summary
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService


@pytest.fixture(autouse=True)
def _use_english_temporal_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="zh-CN": "en",
    )


@pytest.mark.asyncio
async def test_build_temporal_evidence_pack_filters_runtime_and_preserves_importance() -> None:
    service = TemporalSummaryLLMService()

    pack = service.build_evidence_pack(
        events=[
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "content": "I care more about growth than salary.",
                "memory_domain": "user_authored",
                "importance_score": 0.8,
                "timestamp": 100.0,
            },
            {
                "event_id": "evt-2",
                "event_type": "TimelineEvent",
                "content": "Read several remote-work job posts.",
                "memory_domain": "external_activity",
                "importance_score": 0.6,
                "timestamp": 120.0,
            },
            {
                "event_id": "evt-3",
                "event_type": "TaskCompleted",
                "content": "worker finished",
                "memory_domain": "runtime_telemetry",
                "importance_score": 0.2,
                "timestamp": 130.0,
            },
        ],
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
    )

    assert pack.source_event_ids == ["evt-1", "evt-2"]
    assert pack.source_event_count == 2
    assert pack.importance_aggregate == pytest.approx(0.7)
    assert pack.event_type_distribution == {"UserMessage": 1, "TimelineEvent": 1}
    assert {"growth", "salary", "remote-work"} <= set(pack.rule_hints["top_terms"])
    assert pack.rule_hints["high_importance_event_ids"] == ["evt-1", "evt-2"]
    assert pack.rule_hints["repeated_event_types"] == []
    assert pack.rule_hints["window_change_candidates"] == [
        {
            "kind": "first_last_focus_shift",
            "from_event_id": "evt-1",
            "to_event_id": "evt-2",
            "early_terms": ["growth", "salary"],
            "late_terms": ["remote-work"],
            "new_terms": ["remote-work"],
            "dropped_terms": ["growth", "salary"],
        }
    ]
    assert pack.rule_hints["recurring_constraints"] == []


@pytest.mark.asyncio
async def test_first_context_short_answer_keeps_question_as_non_evidence_context() -> None:
    service = TemporalSummaryLLMService(enabled=False)
    question = "最近有什么内容，是你会忍不住反复看或听的？"
    events = [
        {
            "event_id": "evt-mygo",
            "event_type": "UserMessage",
            "content": "MyGO",
            "memory_domain": "user_authored",
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
    ]

    pack = service.build_evidence_pack(
        events=events,
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
    )

    assert pack.events[0].content == "MyGO"
    assert pack.events[0].interpretation_context == {
        "kind": "first_context_question",
        "question_id": "repeating_content",
        "question_text": question,
        "evidence_semantics": "interpretation_context_only",
    }
    prompt = service._render_temporal_context_prompt(pack)
    assert question in prompt
    assert "product-authored question is not evidence" in prompt

    result = await service.generate_temporal_candidate(
        pack,
        fallback_summary=_temporal_fallback_summary(events),
    )
    assert result.used_fallback is True
    assert result.candidate.content == "MyGO"
    assert question not in result.candidate.content


def test_parse_temporal_llm_output_into_candidate() -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="finish portfolio"),
        ],
    )

    candidate, summary_overrides = service.parse_llm_output(
        {
            "content": "The day centered on clarifying job-switch priorities.",
            "key_topics": ["job_search"],
            "key_entities": [{"entity_id": "user:self", "entity_type": "user"}],
            "sentiment_summary": {"tone": "serious_but_constructive"},
            "change_and_pattern": {
                "timeline": ["morning exploration moved into afternoon planning"],
                "source_signals": ["chat centered on job-switch priorities"],
                "decisions_and_actions": ["finish the portfolio before applying"],
                "changes": ["moved from exploration to planning"],
                "patterns": [],
                "open_threads": ["compare growth and salary tradeoffs"],
            },
            "importance_aggregate": 0.8,
        },
        pack=pack,
    )

    assert candidate.summary_type == "temporal"
    assert candidate.summary_category == "day"
    assert candidate.content == "The day centered on clarifying job-switch priorities."
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    assert summary_overrides["key_topics"] == ["job_search"]
    assert summary_overrides["change_and_pattern"]["timeline"] == ["morning exploration moved into afternoon planning"]
    assert summary_overrides["change_and_pattern"]["decisions_and_actions"] == ["finish the portfolio before applying"]
    assert summary_overrides["change_and_pattern"]["open_threads"] == ["compare growth and salary tradeoffs"]
    assert summary_overrides["importance_aggregate"] == 0.8


def test_parse_temporal_llm_output_rejects_english_when_target_is_zh(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="今天在写代码"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="继续处理摘要"),
        ],
    )
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="en": "zh-CN",
    )

    with pytest.raises(ValueError, match="target language"):
        service.parse_llm_output(
            {
                "content": "The session began with browsing activity and then shifted to development work.",
                "key_topics": ["browsing", "development"],
                "change_and_pattern": {
                    "changes": ["shifted from passive consumption to active development"],
                    "patterns": ["browsing was confined to a small set of domains"],
                },
                "importance_aggregate": 0.7,
            },
            pack=pack,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"importance_aggregate": 1.5},
        {"change_and_pattern": {"changes": ["valid", ""]}},
        {"change_and_pattern": {"patterns": "not-a-list"}},
        {"content": "A different rewritten summary."},
    ],
)
async def test_invalid_structure_cannot_replace_accepted_prose_or_apply_partial_metadata(
    monkeypatch, invalid
):
    service = TemporalSummaryLLMService()
    response = _capture_generation_bridge(
        monkeypatch, service, structure={"key_topics": ["must not leak"], **invalid}
    )
    result = await service.generate_temporal_candidate(
        _generation_pack(), fallback_summary="rule text"
    )
    assert response.await_count == 2
    assert result.used_fallback is False
    assert result.candidate.content == "Accepted day summary."
    assert result.candidate.source_event_ids == ["evt-1", "evt-2"]
    assert result.summary_overrides == {
        "key_topics": [],
        "key_entities": [],
        "sentiment_summary": None,
        "change_and_pattern": None,
    }


def _generation_pack(category="day"):
    return TemporalEvidencePack(
        summary_category=category,
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        importance_aggregate=0.7,
        event_type_distribution={"UserMessage": 1, "AIResponse": 1},
        events=[
            TemporalEvidenceItem(
                event_id="evt-1", event_type="UserMessage", content="growth matters"
            ),
            TemporalEvidenceItem(
                event_id="evt-2", event_type="AIResponse", content="finish portfolio"
            ),
        ],
    )


def _capture_generation_bridge(
    monkeypatch, service, *, prose="Accepted day summary.", structure=None
):
    import json
    from unittest.mock import AsyncMock

    outputs = [SimpleNamespace(content=prose), SimpleNamespace(content=json.dumps(structure or {}))]
    bridge = SimpleNamespace(chat_response=AsyncMock(side_effect=outputs))
    monkeypatch.setattr(
        service,
        "_get_llm_target",
        lambda: (SimpleNamespace(provider_name="test", model_name="test-model"), bridge),
    )
    return bridge.chat_response


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "empty"])
async def test_temporal_prose_failure_preserves_fallback_and_skips_structure(monkeypatch, failure):
    from unittest.mock import AsyncMock

    service = TemporalSummaryLLMService(llm_timeout_seconds=0.01)

    async def never_finishes(*args, **kwargs):
        await asyncio.Event().wait()

    prose = (
        AsyncMock(side_effect=never_finishes)
        if failure == "timeout"
        else AsyncMock(return_value="")
    )
    structure = AsyncMock()
    monkeypatch.setattr(service, "_call_temporal_prose_model", prose)
    monkeypatch.setattr(service, "_call_temporal_structure_model", structure)
    result = await service.generate_temporal_candidate(
        _generation_pack(), fallback_summary="rule text"
    )
    assert result.used_fallback is True
    assert result.candidate.content == "rule text"
    assert result.candidate.summary_type == "temporal"
    assert result.candidate.source_event_ids == ["evt-1", "evt-2"]
    prose.assert_awaited_once()
    structure.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_temporal_candidate_keeps_prose_when_structure_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="今天主要在调 Magi 总结"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="结构化字段可以稍后补齐"),
        ],
        importance_aggregate=0.7,
        event_type_distribution={"UserMessage": 1, "AIResponse": 1},
    )

    async def _prose_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "这一天主要在调整 Magi 的总结生成，让正文先稳定可读，再补充结构化字段。"

    async def _bad_structure_call(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        _ = prose_content
        return None

    monkeypatch.setattr(service, "_call_temporal_prose_model", _prose_call)
    monkeypatch.setattr(service, "_call_temporal_structure_model", _bad_structure_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is False
    assert result.candidate.content == "这一天主要在调整 Magi 的总结生成，让正文先稳定可读，再补充结构化字段。"
    assert result.summary_overrides["key_topics"] == []
    assert result.summary_overrides["change_and_pattern"] is None


@pytest.mark.asyncio
async def test_generate_temporal_candidate_keeps_essence_from_structure_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="本周主要修复 Magi 总结页"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="详情保留完整 Markdown"),
        ],
    )

    async def _prose_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "## 要点\n本周主要修复 Magi 总结页，让首页更好读，详情继续保留完整内容。"

    async def _structure_call(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content.startswith("## 要点")
        return {
            "essence_prose": "本周主要修复 Magi 总结页，让首页更好读。",
            "key_topics": ["总结页"],
        }

    monkeypatch.setattr(service, "_call_temporal_prose_model", _prose_call)
    monkeypatch.setattr(service, "_call_temporal_structure_model", _structure_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is False
    assert result.summary_overrides["essence_prose"] == "本周主要修复 Magi 总结页，让首页更好读。"
    assert result.summary_overrides["key_topics"] == ["总结页"]


@pytest.mark.asyncio
async def test_generate_temporal_candidate_falls_back_on_language_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="hour",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Visited Gmail"),
            TemporalEvidenceItem(event_id="evt-2", event_type="TimelineEvent", content="Committed in magi"),
        ],
        event_type_distribution={"TimelineEvent": 2},
        source_distribution={"chrome_history": 1, "git_activity": 1},
    )
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="en": "zh-CN",
    )

    async def _english_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "The session began with browsing activity and then shifted to development work."

    monkeypatch.setattr(service, "_call_temporal_prose_model", _english_call)

    result = await service.generate_temporal_candidate(
        pack,
        fallback_summary="The session began with browsing activity and then shifted to development work.",
    )

    assert result.used_fallback is True
    assert result.candidate.content.startswith("这一小时的记忆主要围绕")
    assert "The session began" not in result.candidate.content


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,count", [(True, 1), (False, 2)])
async def test_temporal_generation_admission_skips_both_model_stages(monkeypatch, enabled, count):
    from unittest.mock import AsyncMock

    service = TemporalSummaryLLMService(enabled=enabled, min_event_count_for_llm=2)
    pack = _generation_pack()
    pack.source_event_count = count
    pack.events = pack.events[:count]
    pack.source_event_ids = pack.source_event_ids[:count]
    prose = AsyncMock(return_value="Unexpected model summary.")
    structure = AsyncMock(return_value={})
    monkeypatch.setattr(service, "_call_temporal_prose_model", prose)
    monkeypatch.setattr(service, "_call_temporal_structure_model", structure)
    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")
    assert result.used_fallback is True
    assert result.candidate.content == "rule text"
    prose.assert_not_awaited()
    structure.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_temporal_model_parses_json_from_llm_target(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
        ],
    )

    class _FakeBridge:
        async def chat_response(self, **_: object) -> SimpleNamespace:
            return SimpleNamespace(content='{"content":"LLM day summary","key_topics":["job_search"]}')

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _FakeBridge()))

    payload = await service._call_temporal_model(pack)

    assert payload == {"content": "LLM day summary", "key_topics": ["job_search"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,default_timeout,disable_thinking",
    [
        ("hour", 180.0, True),
        ("day", 300.0, False),
        ("week", 600.0, False),
        ("month", 600.0, False),
        ("quarter", 600.0, False),
        ("year", 600.0, False),
    ],
)
@pytest.mark.parametrize("override", [None, 1.5])
async def test_period_and_timeout_override_reach_both_model_requests(
    monkeypatch, category, default_timeout, disable_thinking, override
):
    from magi.llm import LLMRequestPriority

    service = TemporalSummaryLLMService(
        **({} if override is None else {"llm_timeout_seconds": override})
    )
    request = _capture_generation_bridge(monkeypatch, service)
    result = await service.generate_temporal_candidate(
        _generation_pack(category), fallback_summary="rule text"
    )
    assert result.used_fallback is False
    assert result.candidate.content == "Accepted day summary."
    assert request.await_count == 2
    calls = [call.kwargs for call in request.await_args_list]
    assert [call["json_mode"] for call in calls] == [False, True]
    assert [call["event_context"]["request_kind"] for call in calls] == [
        "memory:l3_temporal_summary_prose",
        "memory:l3_temporal_summary_structure",
    ]
    for call in calls:
        assert call["timeout_seconds"] == (default_timeout if override is None else override)
        assert call["disable_thinking"] is disable_thinking
        assert call["cache_system"] is True
        assert call["priority"] is LLMRequestPriority.LOW
        assert call["event_context"]["turn_id"] == "evt-1"


def test_temporal_service_uses_memory_summarizer_scenario() -> None:
    from magi.config.models import LLMScenario

    class _FakeScenarioPool:
        def __init__(self) -> None:
            self.calls: list[LLMScenario] = []

        def get(self, scenario: LLMScenario) -> object:
            self.calls.append(scenario)
            return "adapter"

    pool = _FakeScenarioPool()
    service = TemporalSummaryLLMService(scenario_llm_pool=pool)

    assert service._get_adapter() == "adapter"
    assert pool.calls == [LLMScenario.MEMORY_SUMMARIZER]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current,preferred,label",
    [
        ("zh", "en", "Simplified Chinese (zh-CN)"),
        (None, "zh-CN", "Simplified Chinese (zh-CN)"),
        ("en", "zh-CN", "English"),
        (None, "en", "English"),
    ],
)
async def test_live_temporal_requests_share_exact_evidence_and_resolve_language_precedence(
    monkeypatch, current, preferred, label
):
    import json
    from magi.i18n import language_context

    service = TemporalSummaryLLMService()
    pack = _generation_pack()
    pack.rule_hints = {
        "top_terms": ["distinct-hint"],
        "high_importance_event_ids": ["evt-1"],
        "window_change_candidates": [{"kind": "first_last_focus_shift"}],
        "recurring_constraints": [{"keyword": "remote", "event_ids": ["evt-1", "evt-2"]}],
    }
    pack.previous_period_summaries = [{"summary_id": "previous", "content": "Earlier period only."}]
    pack.child_period_summaries = [{"summary_id": "child", "content": "A distinct child summary."}]
    pack.window_event_count = 8
    pack.omitted_event_count = 6
    pack.selection_policy = {"method": "representative"}
    pack.source_distribution = {"chat": 8}
    pack.plugin_summary_features = {"custom": {"focus_domain": "example.org"}}
    prose = (
        "这一天主要在修改总结生成。" if label.startswith("Simplified") else "Accepted day summary."
    )
    request = _capture_generation_bridge(monkeypatch, service, prose=prose)
    monkeypatch.setattr("magi.i18n.get_preferred_language", lambda default="en": preferred)
    with language_context(current):
        result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")
    assert result.used_fallback is False
    assert result.candidate.content == prose
    assert request.await_count == 2
    calls = [call.kwargs for call in request.await_args_list]
    expected = {
        "summary_type": "temporal",
        "summary_category": "day",
        "period_start": 100.0,
        "period_end": 200.0,
        "window_event_count": 8,
        "source_event_count": 2,
        "omitted_event_count": 6,
        "source_event_ids": ["evt-1", "evt-2"],
        "importance_aggregate": 0.7,
        "event_type_distribution": {"UserMessage": 1, "AIResponse": 1},
        "rule_hints": {
            "top_terms": ["distinct-hint"],
            "high_importance_event_ids": ["evt-1"],
            "window_change_candidates": [{"kind": "first_last_focus_shift"}],
            "recurring_constraints": [{"keyword": "remote", "event_ids": ["evt-1", "evt-2"]}],
        },
        "plugin_summary_features": {"custom": {"focus_domain": "example.org"}},
        "source_distribution": {"chat": 8},
        "selection_policy": {"method": "representative"},
        "previous_period_summaries": [
            {"summary_id": "previous", "content": "Earlier period only."}
        ],
        "child_period_summaries": [{"summary_id": "child", "content": "A distinct child summary."}],
        "events": [
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "timestamp": None,
                "memory_domain": None,
                "importance_score": None,
                "content": "growth matters",
                "interpretation_context": None,
            },
            {
                "event_id": "evt-2",
                "event_type": "AIResponse",
                "timestamp": None,
                "memory_domain": None,
                "importance_score": None,
                "content": "finish portfolio",
                "interpretation_context": None,
            },
        ],
    }
    contexts = []
    for call in calls:
        assert f"Target language: {label}" in call["system_prompt"]
        assert len(call["messages"]) == 1 and call["messages"][0]["role"] == "user"
        prompt = call["messages"][0]["content"]
        assert f"The target language is {label}" in prompt
        offset = prompt.index("Evidence Pack:\n") + len("Evidence Pack:\n")
        payload, end = json.JSONDecoder().raw_decode(prompt[offset:])
        assert payload == expected
        contexts.append(prompt[: offset + end])
    assert contexts[0] == contexts[1]
    assert f"Accepted User-Facing Summary:\n{prose}" in calls[1]["messages"][0]["content"]


def test_zh_week_fallback_is_theme_first_and_hides_debug_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=115,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="SOURCE_EVENT", content="visited yoasobi-heaven.com"),
            TemporalEvidenceItem(event_id="evt-2", event_type="SOURCE_EVENT", content="played music"),
        ],
        event_type_distribution={"SOURCE_EVENT": 115},
        source_distribution={"chrome_history": 90, "netease_music": 25},
        plugin_summary_features={
            "chrome_history": {
                "focus_domain": "yoasobi-heaven.com",
                "visit_count": 458,
                "top_domains": [
                    {"domain": "yoasobi-heaven.com", "count": 120},
                    {"domain": "bilibili.com", "count": 60},
                    {"domain": "xiaohongshu.com", "count": 40},
                ],
            }
        },
    )
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="en": "zh-CN",
    )

    content = service._build_fallback_result(pack, "raw fallback").candidate.content

    assert content.startswith("这一周的记忆主要围绕浏览记录和网易云音乐展开")
    assert "浏览活动主要集中在 yoasobi-heaven.com" in content
    assert "高频访问还包括 bilibili.com、xiaohongshu.com" in content
    assert "SOURCE_EVENT" not in content
    assert "事件类型" not in content
    assert "本时间窗口记录" not in content
    assert "共压缩" not in content


@pytest.mark.asyncio
async def test_build_temporal_evidence_pack_extracts_recurring_constraints() -> None:
    service = TemporalSummaryLLMService()

    pack = service.build_evidence_pack(
        events=[
            {
                "event_id": "evt-1",
                "event_type": "UserMessage",
                "content": "I prefer remote work because time flexibility matters.",
                "memory_domain": "user_authored",
                "importance_score": 0.8,
                "timestamp": 100.0,
            },
            {
                "event_id": "evt-2",
                "event_type": "AIResponse",
                "content": "We should optimize for remote roles first.",
                "memory_domain": "interaction",
                "importance_score": 0.6,
                "timestamp": 120.0,
            },
        ],
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
    )

    assert pack.rule_hints["recurring_constraints"] == [
        {"keyword": "remote", "event_ids": ["evt-1", "evt-2"]}
    ]

@pytest.mark.asyncio
async def test_call_temporal_model_no_persona_uses_default_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.memory.l3.temporal_llm_service import TEMPORAL_SUMMARY_SYSTEM_PROMPT

    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
        ],
    )

    captured_kwargs: dict = {}

    class _CapturingBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            captured_kwargs.update(kwargs)
            return SimpleNamespace(content='{"content":"LLM summary","key_topics":[]}')

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _CapturingBridge()))

    await service._call_temporal_model(pack)

    system_prompt = captured_kwargs.get("system_prompt", "")
    assert system_prompt.startswith(TEMPORAL_SUMMARY_SYSTEM_PROMPT)
    assert "Language Rules:" in system_prompt
