"""Tests for temporal L3 evidence-pack and LLM service contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack
from magi.memory.l3.summary_store import _temporal_fallback_summary
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService
from magi.i18n import set_current_language


@pytest.fixture(autouse=True)
def _use_english_temporal_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="zh-CN": "en",
    )


def test_temporal_evidence_pack_keeps_window_and_event_ids() -> None:
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

    assert pack.summary_category == "day"
    assert pack.source_event_ids == ["evt-1", "evt-2"]


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


def test_parse_temporal_llm_output_rejects_out_of_range_importance() -> None:
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

    with pytest.raises(ValueError, match="importance_aggregate"):
        service.parse_llm_output(
            {
                "content": "The day centered on clarifying job-switch priorities.",
                "importance_aggregate": 1.5,
            },
            pack=pack,
        )


def test_parse_temporal_llm_output_rejects_malformed_change_and_pattern() -> None:
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

    with pytest.raises(ValueError, match="change_and_pattern"):
        service.parse_llm_output(
            {
                "content": "The day centered on clarifying job-switch priorities.",
                "change_and_pattern": {"changes": ["valid", 2], "patterns": "not-a-list"},
            },
            pack=pack,
        )


@pytest.mark.asyncio
async def test_generate_temporal_candidate_falls_back_to_rule_summary_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService(llm_timeout_seconds=0.01)
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
        importance_aggregate=0.7,
        event_type_distribution={"UserMessage": 1, "AIResponse": 1},
    )

    async def _slow_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.1)
        return "should never arrive"

    monkeypatch.setattr(service, "_call_temporal_prose_model", _slow_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule text"
    assert result.candidate.summary_type == "temporal"


@pytest.mark.asyncio
async def test_generate_temporal_candidate_falls_back_on_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
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
        importance_aggregate=0.7,
        event_type_distribution={"UserMessage": 1, "AIResponse": 1},
    )

    async def _bad_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return ""

    monkeypatch.setattr(service, "_call_temporal_prose_model", _bad_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule text"


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
async def test_generate_temporal_candidate_ignores_structure_rewrite(
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
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="今天主要在整理总结页"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="结构字段不能改写正文"),
        ],
    )

    async def _prose_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        return "这一天主要在整理总结页，让正文稳定后再提取结构字段。"

    async def _rewriting_structure_call(_pack, *, prose_content, **_kwargs):  # type: ignore[no-untyped-def]
        assert prose_content == "这一天主要在整理总结页，让正文稳定后再提取结构字段。"
        return {
            "content": "这是另一个被结构化调用改写过的总结。",
            "key_topics": ["should_not_apply"],
        }

    monkeypatch.setattr(service, "_call_temporal_prose_model", _prose_call)
    monkeypatch.setattr(service, "_call_temporal_structure_model", _rewriting_structure_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is False
    assert result.candidate.content == "这一天主要在整理总结页，让正文稳定后再提取结构字段。"
    assert result.summary_overrides["key_topics"] == []


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
async def test_generate_temporal_candidate_skips_llm_below_minimum_event_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TemporalSummaryLLMService(min_event_count_for_llm=2)
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

    async def _unexpected_call(_pack, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("LLM path should be skipped for low-evidence packs")

    monkeypatch.setattr(service, "_call_temporal_prose_model", _unexpected_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule text"


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


def test_temporal_period_profiles_use_requested_defaults() -> None:
    service = TemporalSummaryLLMService()

    hour_pack = TemporalEvidencePack(
        summary_category="hour",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
    )
    day_pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
    )
    week_pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
    )

    assert service._timeout_seconds_for_pack(hour_pack) == 180.0
    assert service._timeout_seconds_for_pack(day_pack) == 300.0
    assert service._timeout_seconds_for_pack(week_pack) == 600.0
    assert service._disable_thinking_for_pack(hour_pack) is True
    assert service._disable_thinking_for_pack(day_pack) is False
    assert service._disable_thinking_for_pack(week_pack) is False


def test_temporal_timeout_override_still_applies_to_all_periods() -> None:
    service = TemporalSummaryLLMService(llm_timeout_seconds=1.5)
    pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
    )

    assert service._timeout_seconds_for_pack(pack) == 1.5


@pytest.mark.asyncio
async def test_call_temporal_model_uses_week_timeout_and_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Visited yoasobi-heaven.com"),
            TemporalEvidenceItem(event_id="evt-2", event_type="TimelineEvent", content="Played music"),
        ],
    )
    seen: dict[str, object] = {}

    class _FakeBridge:
        async def chat_response(self, **kwargs: object) -> SimpleNamespace:
            seen.update(kwargs)
            return SimpleNamespace(content='{"content":"LLM week summary"}')

    fake_adapter = SimpleNamespace(provider_name="fake", model_name="fake-model")
    monkeypatch.setattr(service, "_get_llm_target", lambda: (fake_adapter, _FakeBridge()))

    payload = await service._call_temporal_model(pack)

    assert payload == {"content": "LLM week summary"}
    assert seen["timeout_seconds"] == 600.0
    assert seen["disable_thinking"] is False


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


def test_render_temporal_summary_prompt_includes_rule_hints() -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        importance_aggregate=0.7,
        event_type_distribution={"UserMessage": 2},
        rule_hints={
            "top_terms": ["growth", "portfolio"],
            "high_importance_event_ids": ["evt-1"],
            "repeated_event_types": ["UserMessage"],
            "window_change_candidates": [{"kind": "first_last_focus_shift"}],
            "recurring_constraints": [{"keyword": "remote", "event_ids": ["evt-1", "evt-2"]}],
        },
        previous_period_summaries=[
            {
                "summary_id": "summary-prev-day",
                "summary_category": "day",
                "period_start": 0.0,
                "period_end": 100.0,
                "content": "The previous day was mostly exploratory.",
            }
        ],
        child_period_summaries=[
            {
                "summary_id": "summary-child-hour",
                "summary_category": "hour",
                "period_start": 120.0,
                "period_end": 130.0,
                "content": "A focused portfolio hour.",
            }
        ],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
            TemporalEvidenceItem(event_id="evt-2", event_type="UserMessage", content="finish portfolio"),
        ],
    )

    prompt = service._render_temporal_summary_prompt(pack)

    assert "Task:" in prompt
    assert "Output JSON Schema:" in prompt
    assert "Evidence Pack:" in prompt
    assert "Structure Contract:" in prompt
    assert '"rule_hints"' in prompt
    assert '"top_terms"' in prompt
    assert '"growth"' in prompt
    assert '"window_change_candidates"' in prompt
    assert '"recurring_constraints"' in prompt
    assert '"content"' in prompt
    assert '"change_and_pattern"' in prompt
    assert '"timeline"' in prompt
    assert '"source_signals"' in prompt
    assert '"decisions_and_actions"' in prompt
    assert '"open_threads"' in prompt
    assert '"previous_period_summaries"' in prompt
    assert '"child_period_summaries"' in prompt
    assert "only for comparison and timeline continuity" not in prompt
    assert "ordered comparison series" in prompt
    assert "primary skeleton" in prompt
    assert "Markdown" in prompt
    assert '"headline"' in prompt
    assert "The previous day was mostly exploratory" in prompt


def test_temporal_prose_and_structure_prompts_share_context_prefix() -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=2,
        source_event_ids=["evt-1", "evt-2"],
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="今天在调整总结"),
            TemporalEvidenceItem(event_id="evt-2", event_type="AIResponse", content="结构化字段稍后提取"),
        ],
    )

    context = service._render_temporal_context_prompt(pack)
    prose_prompt = service._render_temporal_prose_prompt(pack)
    structure_prompt = service._render_temporal_structure_prompt(
        pack,
        prose_content="这一天主要在调整总结生成。",
    )

    assert prose_prompt.startswith(context)
    assert structure_prompt.startswith(context)
    assert "Evidence Pack:" in context
    assert "生成用户可读正文" in prose_prompt
    assert "提取结构化字段" in structure_prompt


def test_render_temporal_summary_prompt_includes_period_focus() -> None:
    service = TemporalSummaryLLMService()
    hour_pack = TemporalEvidencePack(
        summary_category="hour",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Visited Gmail")],
    )
    day_pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="I need remote work")],
    )
    week_pack = TemporalEvidencePack(
        summary_category="week",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Played music")],
    )
    month_pack = TemporalEvidencePack(
        summary_category="month",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Worked on Magi memory")],
    )

    assert "Hour focus" in service._render_temporal_summary_prompt(hour_pack)
    assert "Day focus" in service._render_temporal_summary_prompt(day_pack)
    assert "Week focus" in service._render_temporal_summary_prompt(week_pack)
    assert "Month focus" in service._render_temporal_summary_prompt(month_pack)
    assert "timeline-oriented month recap" in service._render_temporal_summary_prompt(month_pack)
    assert "do not compress the week into a single generic theme" in service._render_temporal_summary_prompt(week_pack)
    assert "Do not lead with raw event counts" in service._render_temporal_summary_prompt(week_pack)


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


def test_render_temporal_summary_prompt_uses_current_language() -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="day",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="今天很忙")],
    )

    try:
        set_current_language("zh")
        prompt = service._render_temporal_summary_prompt(pack)
    finally:
        set_current_language(None)

    assert "Simplified Chinese (zh-CN)" in prompt
    assert "Preserve event ids" in prompt


def test_render_temporal_summary_prompt_prefers_user_language(monkeypatch: pytest.MonkeyPatch) -> None:
    service = TemporalSummaryLLMService()
    pack = TemporalEvidencePack(
        summary_category="hour",
        period_start=100.0,
        period_end=200.0,
        source_event_count=1,
        source_event_ids=["evt-1"],
        events=[TemporalEvidenceItem(event_id="evt-1", event_type="TimelineEvent", content="Visited Gmail")],
    )
    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="en": "zh-CN",
    )

    try:
        set_current_language(None)
        prompt = service._render_temporal_summary_prompt(pack)
    finally:
        set_current_language(None)

    assert "The target language is Simplified Chinese (zh-CN)" in prompt
    assert "mandatory even when evidence" in prompt


def test_temporal_summary_system_prompt_includes_target_language(monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.memory.l3.temporal_llm_service import _render_temporal_summary_system_prompt

    monkeypatch.setattr(
        "magi.i18n.get_preferred_language",
        lambda default="en": "zh-CN",
    )

    system_prompt = _render_temporal_summary_system_prompt()

    assert "Target language: Simplified Chinese (zh-CN)" in system_prompt
    assert "MUST use the target language" in system_prompt


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
