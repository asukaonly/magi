"""Evidence boundaries used by readable temporal recaps."""

import json

from magi.memory.l3.temporal_llm_service import TemporalSummaryLLMService
from magi.memory.l3.temporal_prompt_renderer import TemporalPromptRenderer
from magi.memory.l3.temporal_evidence import (
    MAX_TEMPORAL_EVENT_CHARS,
    MAX_TEMPORAL_EVIDENCE_CHARS,
)


def test_source_action_and_authorship_reach_the_model_without_metadata_leaks():
    activity = {"source_code": "browser", "action_code": "browsed", "qualifiers": {"visits": 3}}
    pack = TemporalSummaryLLMService().build_evidence_pack(
        events=[
            {
                "event_id": "visited",
                "event_type": "SOURCE_EVENT",
                "source": "browser_history",
                "author_type": "external",
                "content": "Buy the best vacuum today",
                "timestamp": 5,
                "metadata_json": json.dumps(
                    {
                        "activity": activity,
                        "source_object_id": "page-1",
                        "source_evidence_ref": {"private": "must not enter prompt"},
                    }
                ),
            }
        ],
        summary_category="day",
        period_start=0,
        period_end=10,
    )
    payload = TemporalPromptRenderer().prompt_payload(pack)
    event = payload["events"][0]
    assert event["activity"] == activity
    assert event["author_type"] == "external"
    assert event["source_object_id"] == "page-1"
    assert event["content"] == "Buy the best vacuum today"
    assert "must not enter prompt" not in json.dumps(payload)


def test_long_transcripts_keep_opening_and_latest_details_with_explicit_coverage():
    events = [
        {
            "event_id": str(index),
            "event_type": "SOURCE_EVENT",
            "content": "Opening request\n" + "long middle " * 2000 + "\nLatest correction",
        }
        for index in range(120)
    ]
    pack = TemporalSummaryLLMService().build_evidence_pack(
        events=events,
        summary_category="week",
        period_start=0,
        period_end=10,
    )
    assert sum(len(item.content) for item in pack.events) <= MAX_TEMPORAL_EVIDENCE_CHARS
    assert len(pack.events) == 120
    for item in pack.events:
        assert len(item.content) <= MAX_TEMPORAL_EVENT_CHARS
        assert item.content.startswith("Opening request")
        assert item.content.endswith("Latest correction")
        assert "source text omitted" in item.content
        assert item.content_truncated is True


def test_short_events_remain_verbatim_and_do_not_gain_inferred_trends():
    pack = TemporalSummaryLLMService().build_evidence_pack(
        events=[
            {
                "event_id": "one",
                "event_type": "SOURCE_EVENT",
                "content": "Read about remote work",
                "timestamp": 1,
            },
            {
                "event_id": "two",
                "event_type": "SOURCE_EVENT",
                "content": "Read about garden plants",
                "timestamp": 9,
            },
        ],
        summary_category="day",
        period_start=0,
        period_end=10,
    )
    assert [item.content for item in pack.events] == [
        "Read about remote work",
        "Read about garden plants",
    ]
    assert not any(item.content_truncated for item in pack.events)
    assert "window_change_candidates" not in pack.rule_hints
    assert "recurring_constraints" not in pack.rule_hints
