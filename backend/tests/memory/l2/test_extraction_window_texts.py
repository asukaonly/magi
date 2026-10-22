"""Frozen extraction bodies are shared by prompts, guards, and evidence locators."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from magi.events.events import Event
from magi.memory.event_contracts import MemoryEvent, normalize_runtime_event
from magi.memory.l2.models import L2EventWindow, L2Phase1Result
from magi.memory.l2.pipeline.claim_grounding import ground_phase1_fact_claims
from magi.memory.l2.pipeline.claim_persistence import _evidence_locator
from magi.memory.l2.pipeline.entity_grounding import evidence_script_names
from magi.memory.l2.pipeline.extraction import (
    L2PipelineExtractionMixin,
    resolve_extraction_events,
)
from magi.memory.l2.pipeline.prompts import render_phase1_extract_prompt
from magi.memory.l2.pipeline.utils import L2PipelineUtilityMixin


def _event(event_id: str, content: str) -> MemoryEvent:
    return normalize_runtime_event(
        Event(
            event_id=event_id,
            type="UserMessage",
            source="chat",
            timestamp=1.0,
            data={"content": content, "user_id": "local_user"},
        )
    )


def _result(quote: str) -> L2Phase1Result:
    return L2Phase1Result.from_dict(
        {
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "predicate": "REAL_NAME",
                    "object_ref": "小明",
                    "object_type": "person",
                    "evidence_text": quote,
                }
            ],
        }
    )


def test_body_is_bound_by_event_id_and_shared_without_rewriting_raw_events() -> None:
    raw = [_event("empty", ""), _event("note", "Summary"), _event("other", "Other summary")]
    body = "  # 近况\n\n我叫小明。\n"
    window = L2EventWindow(events=resolve_extraction_events(raw, {"note": body, "other": ""}))

    assert window.texts == ["", body, "Other summary"]
    assert [event.content_source for event in window.events] == [
        "event_content",
        "pinned_payload",
        "event_content",
    ]
    assert [event.content for event in raw] == ["", "Summary", "Other summary"]
    assert L2EventWindow(**window.to_dict()).texts == window.texts
    prompt = render_phase1_extract_prompt(
        event_window=window,
        focal_subject={"entity_ref": "user:local_user"},
    )
    assert "我叫小明。" in prompt
    assert "### [USER] [#note]" in prompt
    assert evidence_script_names(window) == ("Han", "Latin")
    result = _result("我叫小明。")
    assert (
        L2PipelineUtilityMixin()._filter_ungrounded_profile_signal_claims(
            result,
            window.events,
        )
        == 0
    )
    assert ground_phase1_fact_claims(result, window)["kept"] == 1
    assert result.fact_claims[0].supporting_event_ids == ["note"]
    locator = _evidence_locator(window.events[1].content, result.fact_claims[0].evidence_text)
    assert body[locator["start"] : locator["end"]] == "我叫小明。"


def test_history_document_owns_its_normalized_body() -> None:
    raw = replace(_event("doc", "我叫小明。"), event_type="history_import.document")
    resolved = resolve_extraction_events([raw], {"doc": "Unrelated snapshot"})
    assert resolved[0].content == raw.content
    assert resolved[0].content_source == "event_content"


@pytest.mark.parametrize("author", ["assistant", "external"])
def test_full_text_does_not_grant_user_authorship(author: str) -> None:
    raw = replace(_event("other", "Summary"), author_type=author)
    result = _result("我叫小明。")
    events = resolve_extraction_events([raw], {"other": "我叫小明。"})
    assert L2PipelineUtilityMixin()._filter_ungrounded_profile_signal_claims(result, events) == 1
    assert result.fact_claims == []


@pytest.mark.asyncio
async def test_payload_read_failure_is_not_silently_extracted_as_a_summary() -> None:
    host = L2PipelineExtractionMixin()
    host._l1_store = AsyncMock()
    host._l1_store.get_pinned_payloads.side_effect = RuntimeError("payload read failed")
    with pytest.raises(RuntimeError, match="payload read failed"):
        await host._fetch_pinned_payloads(["note"])
    host._l1_store.get_pinned_payloads.assert_awaited_once_with(["note"])


@pytest.mark.parametrize("event_type", ["UserMessage", "history_import.document"])
@pytest.mark.parametrize("prefix", ["> 我叫小明。\n\n", "```text\n我叫小明。\n```\n\n"])
def test_locator_uses_authored_occurrence_after_identical_quoted_text(
    event_type: str,
    prefix: str,
) -> None:
    quote = "我叫小明。"
    body = prefix + quote
    raw = replace(_event("note", body), event_type=event_type)
    events = resolve_extraction_events([raw], {})
    result = _result(quote)
    assert ground_phase1_fact_claims(result, L2EventWindow(events=events))["kept"] == 1
    locator = _evidence_locator(body, quote, event_type=event_type)
    assert (locator["start"], locator["end"]) == (len(prefix), len(body))


@pytest.mark.parametrize("event_type", ["UserMessage", "history_import.document"])
@pytest.mark.parametrize(
    ("body", "quote", "source_quote"),
    [
        ("🎵\r\nI use   OBSIDIAN.\r\n", "i use obsidian.", "I use   OBSIDIAN."),
        (
            "正文：我用Ｏｂｓｉｄｉａｎ整理笔记。",
            "我用Obsidian整理笔记。",
            "我用Ｏｂｓｉｄｉａｎ整理笔记。",
        ),
        ("Notes: I visited Cafe\u0301.", "I visited Café.", "I visited Cafe\u0301."),
    ],
)
def test_normalized_grounding_and_locator_share_original_character_offsets(
    event_type: str,
    body: str,
    quote: str,
    source_quote: str,
) -> None:
    raw = replace(_event("note", body), event_type=event_type)
    result = L2Phase1Result.from_dict(
        {
            "fact_claims": [
                {
                    "assertion_mode": "asserted",
                    "subject_ref": "user:self",
                    "predicate": "USES",
                    "object_ref": "software:obsidian",
                    "object_type": "software",
                    "evidence_text": quote,
                }
            ]
        }
    )
    window = L2EventWindow(events=resolve_extraction_events([raw], {}))
    assert ground_phase1_fact_claims(result, window)["kept"] == 1
    locator = _evidence_locator(body, quote, event_type=event_type)
    assert (locator["start"], locator["end"]) == (
        body.index(source_quote),
        body.index(source_quote) + len(source_quote),
    )
    assert body[locator["start"] : locator["end"]] == source_quote
