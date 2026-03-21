from __future__ import annotations

from datetime import datetime

from magi.memory.answering.reducers import resolve_temporal_distance_answer


def test_resolve_temporal_distance_answer_computes_explicit_day_delta():
    timeline_summary = [
        {
            "timestamp": 1.0,
            "session_id": "sess-workshop",
            "turn_id": "sess-workshop:turn-1",
            "author_type": "user",
            "summary": 'I attended the "Effective Communication in the Workplace" workshop on January 10th.',
            "supporting_event_ids": ["evt-workshop"],
            "reason_codes": ["quoted_span_match", "temporal_anchor"],
        },
        {
            "timestamp": 2.0,
            "session_id": "sess-meeting",
            "turn_id": "sess-meeting:turn-1",
            "author_type": "user",
            "summary": "I was preparing for a team meeting on January 17th.",
            "supporting_event_ids": ["evt-meeting"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
    ]

    answer = resolve_temporal_distance_answer(
        question="How many days before the team meeting I was preparing for did I attend the workshop on 'Effective Communication in the Workplace'?",
        timeline_summary=timeline_summary,
    )

    assert answer == "7 days"


def test_resolve_temporal_distance_answer_computes_relative_week_delta():
    timeline_summary = [
        {
            "timestamp": 1.0,
            "session_id": "sess-meetup",
            "turn_id": "sess-meetup:turn-1",
            "author_type": "user",
            "summary": "I attended a meetup organized by Book Lovers Unite last week where we discussed the book.",
            "supporting_event_ids": ["evt-meetup"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
        {
            "timestamp": 2.0,
            "session_id": "sess-joined",
            "turn_id": "sess-joined:turn-1",
            "author_type": "user",
            "summary": 'I recently joined a Facebook group called "Book Lovers Unite" three weeks ago and have been loving the discussions.',
            "supporting_event_ids": ["evt-joined"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
    ]

    answer = resolve_temporal_distance_answer(
        question="How long had I been a member of 'Book Lovers Unite' when I attended the meetup?",
        timeline_summary=timeline_summary,
        query_timestamp=datetime(2023, 5, 24, 21, 38).timestamp(),
    )

    assert answer == "2 weeks"
