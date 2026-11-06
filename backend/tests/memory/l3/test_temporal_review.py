"""Evidence repair must not turn known overclaims into accepted summaries."""

from unittest.mock import AsyncMock

import pytest

from magi.memory.l3.models import TemporalEvidencePack
from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService
from magi.memory.l3.temporal_review import parse_prose_issues


def _pack():
    return TemporalEvidencePack(
        summary_category="day",
        period_start=0,
        period_end=10,
        source_event_count=2,
        source_event_ids=["request", "browsing"],
    )


def _issue():
    return {
        "claim": "修复了报表。",
        "reason": "The user requested a fix; no result was observed.",
        "event_ids": ["request"],
    }


@pytest.mark.asyncio
async def test_flagged_request_completion_is_repaired_and_reviewed_again(monkeypatch):
    service = TemporalSummaryLLMService()
    monkeypatch.setattr(
        service, "_call_temporal_prose_model", AsyncMock(return_value="修复了报表。")
    )
    structure = AsyncMock(
        side_effect=[
            {"unsupported_claims": [_issue()], "essence_prose": "修好了报表。"},
            {"unsupported_claims": [], "essence_prose": "请助手修复报表。", "key_topics": ["CRM"]},
        ]
    )
    repair = AsyncMock(return_value="请助手修复报表。")
    monkeypatch.setattr(service, "_call_temporal_structure_model", structure)
    monkeypatch.setattr(service._model_client, "call_repair_model", repair)
    result = await service.generate_temporal_candidate(_pack(), fallback_summary="Fallback")
    assert not result.used_fallback
    assert result.candidate.content == "请助手修复报表。"
    assert result.summary_overrides["essence_prose"] == "请助手修复报表。"
    assert structure.await_count == 2
    repair.assert_awaited_once()
    assert repair.call_args.kwargs["issues"] == [_issue()]


@pytest.mark.asyncio
@pytest.mark.parametrize("second", [None, {}, {"unsupported_claims": [_issue()]}])
async def test_unverified_or_still_wrong_repair_is_not_published(monkeypatch, second):
    service = TemporalSummaryLLMService()
    monkeypatch.setattr(
        service, "_call_temporal_prose_model", AsyncMock(return_value="修复了报表。")
    )
    monkeypatch.setattr(
        service,
        "_call_temporal_structure_model",
        AsyncMock(side_effect=[{"unsupported_claims": [_issue()]}, second]),
    )
    repair = AsyncMock(return_value="修复了报表。")
    monkeypatch.setattr(service._model_client, "call_repair_model", repair)
    result = await service.generate_temporal_candidate(_pack(), fallback_summary="Fallback")
    assert result.used_fallback
    assert result.candidate.content != "修复了报表。"
    repair.assert_awaited_once()


@pytest.mark.parametrize(
    "issue",
    [
        {"claim": "Not in the draft", "reason": "Missing", "event_ids": []},
        {"claim": "修复了报表。", "reason": "Missing", "event_ids": ["invented"]},
    ],
)
def test_review_cannot_inject_quotes_or_evidence(issue):
    with pytest.raises(ValueError):
        parse_prose_issues(
            {"unsupported_claims": [issue]}, content="修复了报表。", event_ids=["request"]
        )


@pytest.mark.asyncio
async def test_malformed_review_does_not_silently_accept_the_draft(monkeypatch):
    service = TemporalSummaryLLMService()
    monkeypatch.setattr(
        service, "_call_temporal_prose_model", AsyncMock(return_value="修复了报表。")
    )
    monkeypatch.setattr(
        service,
        "_call_temporal_structure_model",
        AsyncMock(
            return_value={
                "unsupported_claims": [_issue(), {"claim": "Not in draft"}],
            }
        ),
    )
    result = await service.generate_temporal_candidate(_pack(), fallback_summary="Fallback")
    assert result.used_fallback


def test_english_product_names_do_not_discard_a_chinese_preview(monkeypatch):
    monkeypatch.setattr("magi.i18n.get_preferred_language", lambda default="en": "zh-CN")
    service = TemporalSummaryLLMService()
    fields = service.parse_structure_output(
        {
            "essence_prose": "查阅了 Claude Code 的工作方式。",
            "key_topics": ["Claude Code", "JDEasyFlow"],
        },
        pack=_pack(),
        content="查阅了 Claude Code 的工作方式。",
    )
    assert fields["essence_prose"] == "查阅了 Claude Code 的工作方式。"
    assert fields["key_topics"] == ["Claude Code", "JDEasyFlow"]
