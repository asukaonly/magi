"""Tests for temporal L3 evidence-pack and LLM service contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.l3.models import TemporalEvidenceItem, TemporalEvidencePack
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService


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
            "change_and_pattern": {"changes": ["moved from exploration to planning"], "patterns": []},
            "importance_aggregate": 0.8,
        },
        pack=pack,
    )

    assert candidate.summary_type == "temporal"
    assert candidate.summary_category == "day"
    assert candidate.content == "The day centered on clarifying job-switch priorities."
    assert candidate.source_event_ids == ["evt-1", "evt-2"]
    assert summary_overrides["key_topics"] == ["job_search"]
    assert summary_overrides["importance_aggregate"] == 0.8


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
        return {"content": "should never arrive"}

    monkeypatch.setattr(service, "_call_temporal_model", _slow_call)

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
        return {"content": ""}

    monkeypatch.setattr(service, "_call_temporal_model", _bad_call)

    result = await service.generate_temporal_candidate(pack, fallback_summary="rule text")

    assert result.used_fallback is True
    assert result.candidate.content == "rule text"


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

    monkeypatch.setattr(service, "_call_temporal_model", _unexpected_call)

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
        events=[
            TemporalEvidenceItem(event_id="evt-1", event_type="UserMessage", content="growth matters"),
            TemporalEvidenceItem(event_id="evt-2", event_type="UserMessage", content="finish portfolio"),
        ],
    )

    prompt = service._render_temporal_summary_prompt(pack)

    assert "Task:" in prompt
    assert "Output JSON Schema:" in prompt
    assert "Evidence Pack:" in prompt
    assert '"rule_hints"' in prompt
    assert '"top_terms"' in prompt
    assert '"growth"' in prompt
    assert '"window_change_candidates"' in prompt
    assert '"recurring_constraints"' in prompt
    assert '"content"' in prompt
    assert '"change_and_pattern"' in prompt


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
async def test_call_temporal_model_appends_persona_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
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

    persona_context = {
        "name": "Melchior",
        "tone": "wise and warm",
        "background": "A scholar of MAGI",
        "keywords": "insight, growth",
    }

    await service._call_temporal_model(pack, persona_context=persona_context)

    system_prompt = captured_kwargs.get("system_prompt", "")
    assert "Melchior" in system_prompt
    assert "wise and warm" in system_prompt


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

    await service._call_temporal_model(pack, persona_context=None)

    system_prompt = captured_kwargs.get("system_prompt", "")
    assert system_prompt == TEMPORAL_SUMMARY_SYSTEM_PROMPT
