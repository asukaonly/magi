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


def test_keeps_quoted_title_and_relative_time_in_long_event_summary():
    bundles = [
        {
            "session_id": "session-1",
            "events": [
                {
                    "event_id": "evt-workshop",
                    "session_id": "session-1",
                    "turn_id": "session-1:turn-11",
                    "timestamp": 21.0,
                    "author_type": "user",
                    "content": (
                        "I've been thinking about my goals and priorities lately, and I realized that I want to focus "
                        "more on learning new skills and expanding my knowledge in different areas. I've been attending "
                        "various workshops and lectures, like the workshop on \"Effective Time Management\" at the local "
                        "community center last Saturday, and I'm finding them really helpful. Do you have any suggestions "
                        "for online resources or courses that could help me learn new skills or expand my knowledge?"
                    ),
                }
            ],
        }
    ]

    summary = build_timeline_summary(
        question="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
        evidence_bundles=bundles,
    )

    assert len(summary) == 1
    assert '"Effective Time Management"' in summary[0]["summary"]
    assert "last Saturday" in summary[0]["summary"]


def test_prefers_first_service_anchor_over_generic_new_car_activity():
    bundles = [
        {
            "session_id": "session-service",
            "events": [
                {
                    "event_id": "evt-service",
                    "session_id": "session-service",
                    "turn_id": "session-service:turn-1",
                    "timestamp": 1.0,
                    "author_type": "user",
                    "content": (
                        "I'm thinking of getting my car detailed soon. Do you know any good detailers in the area or have any "
                        "recommendations? By the way, I just got my car serviced for the first time on March 15th, and it was a great experience."
                    ),
                },
                {
                    "event_id": "evt-accessories",
                    "session_id": "session-service",
                    "turn_id": "session-service:turn-9",
                    "timestamp": 9.0,
                    "author_type": "user",
                    "content": (
                        "I've also been redeeming points from my credit card to get rewards. "
                        "I recently redeemed 50,000 points to get a $500 gift card to a car accessories store. "
                        "I used it to purchase a new car cover, floor mats, and a steering wheel cover, which I'm really happy with."
                    ),
                },
                {
                    "event_id": "evt-detailer",
                    "session_id": "session-service",
                    "turn_id": "session-service:turn-11",
                    "timestamp": 11.0,
                    "author_type": "user",
                    "content": (
                        "I'm really happy with my new car accessories, and they've added a nice touch to my car. "
                        "I've been thinking about getting a car wax and detailing done soon, and I was wondering if you could help me find a good detailer in my area."
                    ),
                },
            ],
        },
        {
            "session_id": "session-issue",
            "events": [
                {
                    "event_id": "evt-issue",
                    "session_id": "session-issue",
                    "turn_id": "session-issue:turn-3",
                    "timestamp": 15.0,
                    "author_type": "user",
                    "content": "After the first service, the GPS system stopped working correctly on 3/22.",
                }
            ],
        },
    ]

    summary = build_timeline_summary(
        question="What was the first issue I had with my new car after its first service?",
        evidence_bundles=bundles,
    )

    assert [item["supporting_event_ids"] for item in summary] == [["evt-service"], ["evt-issue"]]


def test_prefers_sentence_with_month_date_in_service_summary():
    bundles = [
        {
            "session_id": "session-service",
            "events": [
                {
                    "event_id": "evt-service",
                    "session_id": "session-service",
                    "turn_id": "session-service:turn-1",
                    "timestamp": 1.0,
                    "author_type": "user",
                    "content": (
                        "I'm thinking of getting my car detailed soon. "
                        "Do you know any good detailers in the area or have any recommendations? "
                        "By the way, I just got my car serviced for the first time on March 15th, and it was a great experience."
                    ),
                }
            ],
        }
    ]

    summary = build_timeline_summary(
        question="What was the first issue I had with my new car after its first service?",
        evidence_bundles=bundles,
    )

    assert len(summary) == 1
    assert "March 15th" in summary[0]["summary"]
    assert "serviced for the first time" in summary[0]["summary"]


