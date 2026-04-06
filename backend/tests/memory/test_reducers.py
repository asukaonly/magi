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


def test_resolve_temporal_distance_answer_computes_month_delta():
    timeline_summary = [
        {
            "timestamp": 1.0,
            "session_id": "sess-filmfest",
            "turn_id": "sess-filmfest:turn-1",
            "author_type": "user",
            "summary": "I attended the Seattle International Film Festival on January 15, 2023.",
            "supporting_event_ids": ["evt-filmfest"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
    ]

    answer = resolve_temporal_distance_answer(
        question="How many months ago did I attend the Seattle International Film Festival?",
        timeline_summary=timeline_summary,
        query_timestamp=datetime(2023, 5, 20, 12, 0).timestamp(),
    )

    assert answer == "4 months"


def test_resolve_temporal_distance_answer_computes_month_delta_from_relative():
    timeline_summary = [
        {
            "timestamp": 1.0,
            "session_id": "sess-workshop",
            "turn_id": "sess-workshop:turn-1",
            "author_type": "user",
            "summary": "I attended the photography workshop three months ago.",
            "supporting_event_ids": ["evt-workshop"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
        {
            "timestamp": 2.0,
            "session_id": "sess-bought",
            "turn_id": "sess-bought:turn-1",
            "author_type": "user",
            "summary": "I bought a new camera lens two months ago.",
            "supporting_event_ids": ["evt-bought"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
    ]

    answer = resolve_temporal_distance_answer(
        question="How many months passed between the photography workshop and buying a new camera lens?",
        timeline_summary=timeline_summary,
        query_timestamp=datetime(2023, 6, 15, 12, 0).timestamp(),
    )

    assert answer == "1 month"


def test_resolve_temporal_distance_answer_survives_invalid_numeric_date():
    """Numeric patterns like 14/5 (from text like 'session 14/5') must not crash."""
    timeline_summary = [
        {
            "timestamp": 1.0,
            "session_id": "sess-aunt",
            "turn_id": "sess-aunt:turn-1",
            "author_type": "user",
            "summary": "I met up with my aunt on 14/5 and received a crystal chandelier.",
            "supporting_event_ids": ["evt-aunt"],
            "reason_codes": ["phrase_match", "temporal_anchor"],
        },
    ]

    # Should not raise "month must be in 1..12"
    answer = resolve_temporal_distance_answer(
        question="How many weeks ago did I meet up with my aunt and receive the crystal chandelier?",
        timeline_summary=timeline_summary,
        query_timestamp=datetime(2023, 6, 1, 12, 0).timestamp(),
    )
    # The function may or may not produce an answer, but it must not crash
    assert answer is None or isinstance(answer, str)
