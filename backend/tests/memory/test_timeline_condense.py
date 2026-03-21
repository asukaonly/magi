"""Tests for deterministic timeline condensation."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.timeline_condense import build_timeline_summary


def test_condenses_bundles_into_time_sorted_event_lines():
    bundles = [
        {
            "session_id": "session-b",
            "events": [
                {
                    "event_id": "evt-b1",
                    "session_id": "session-b",
                    "turn_id": "session-b:turn-3",
                    "timestamp": 20.0,
                    "author_type": "user",
                    "content": "I attended the 'Effective Time Management' workshop last Saturday.",
                }
            ],
        },
        {
            "session_id": "session-a",
            "events": [
                {
                    "event_id": "evt-a1",
                    "session_id": "session-a",
                    "turn_id": "session-a:turn-2",
                    "timestamp": 10.0,
                    "author_type": "user",
                    "content": "I participated in the 'Data Analysis using Python' webinar two months ago.",
                }
            ],
        },
    ]

    summary = build_timeline_summary(
        question="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
        evidence_bundles=bundles,
    )

    assert [item["supporting_event_ids"] for item in summary] == [["evt-a1"], ["evt-b1"]]
    assert [item["timestamp"] for item in summary] == [10.0, 20.0]


def test_skips_generic_guidance_when_fact_event_exists_in_same_bundle():
    bundles = [
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "evt-1",
                    "session_id": "session-1",
                    "turn_id": "session-1:turn-2",
                    "timestamp": 11.0,
                    "author_type": "assistant",
                    "content": "Here are some tips for comparing your workshop and webinar notes to figure out which came first.",
                },
                {
                    "event_id": "evt-2",
                    "session_id": "session-1",
                    "turn_id": "session-1:turn-3",
                    "timestamp": 12.0,
                    "author_type": "user",
                    "content": "I participated in the 'Data Analysis using Python' webinar two months ago.",
                },
            ],
        }
    ]

    summary = build_timeline_summary(
        question="Which event did I attend first, the 'Data Analysis using Python' webinar?",
        evidence_bundles=bundles,
    )

    assert [item["supporting_event_ids"] for item in summary] == [["evt-2"]]


def test_preserves_two_competing_events_for_comparison_questions():
    bundles = [
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "evt-webinar",
                    "session_id": "session-1",
                    "turn_id": "session-1:turn-3",
                    "timestamp": 15.0,
                    "author_type": "user",
                    "content": "I participated in the 'Data Analysis using Python' webinar two months ago.",
                }
            ],
        },
        {
            "session_id": "session-2",
            "events": [
                {
                    "event_id": "evt-workshop",
                    "session_id": "session-2",
                    "turn_id": "session-2:turn-11",
                    "timestamp": 21.0,
                    "author_type": "user",
                    "content": "I attended the 'Effective Time Management' workshop last Saturday.",
                }
            ],
        },
    ]

    summary = build_timeline_summary(
        question="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
        evidence_bundles=bundles,
    )

    summary_event_ids = [item["supporting_event_ids"][0] for item in summary]
    assert summary_event_ids == ["evt-webinar", "evt-workshop"]
