from __future__ import annotations

from magi.memory.answering.prompt_builder import build_answer_prompt_payload


def test_build_answer_prompt_payload_prioritizes_timeline_for_temporal_questions():
    noisy_assistant_text = (
        "Here are some top-notch resources to help you learn data visualization in Python: "
        "Matplotlib, Seaborn, Plotly, and many more options for dashboarding and storytelling."
    )

    payload = build_answer_prompt_payload(
        question="Which event did I attend first, the 'Effective Time Management' workshop or the 'Data Analysis using Python' webinar?",
        hits=[
            {
                "event_id": "evt-webinar",
                "session_id": "sess-webinar",
                "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                "score": 0.8,
                "turn_id": "sess-webinar:turn-3",
            },
            {
                "event_id": "evt-workshop",
                "session_id": "sess-workshop",
                "content": 'I attended the "Effective Time Management" workshop last Saturday.',
                "score": 0.8,
                "turn_id": "sess-workshop:turn-11",
            },
        ],
        evidence_bundles=[
            {
                "session_id": "sess-webinar",
                "events": [
                    {
                        "event_id": "evt-helper",
                        "turn_id": "sess-webinar:turn-2",
                        "timestamp": 14.0,
                        "author_type": "assistant",
                        "content": noisy_assistant_text,
                    },
                    {
                        "event_id": "evt-webinar",
                        "turn_id": "sess-webinar:turn-3",
                        "timestamp": 15.0,
                        "author_type": "user",
                        "content": 'I participated in the "Data Analysis using Python" webinar two months ago.',
                    },
                ],
            }
        ],
        timeline_summary=[
            {
                "timestamp": 11.0,
                "session_id": "sess-workshop",
                "turn_id": "sess-workshop:turn-11",
                "author_type": "user",
                "summary": 'I attended the "Effective Time Management" workshop last Saturday.',
            },
            {
                "timestamp": 15.0,
                "session_id": "sess-webinar",
                "turn_id": "sess-webinar:turn-3",
                "author_type": "user",
                "summary": 'I participated in the "Data Analysis using Python" webinar two months ago.',
            },
        ],
    )

    assert payload.prioritize_timeline is True
    # Bundles are now included (with timestamps) even for temporal questions
    assert "bundle 1" in payload.bundle_text
    assert "sess-webinar" in payload.bundle_text
    assert noisy_assistant_text in payload.bundle_text  # 171 chars, under truncation limit
    # Timeline always includes timestamps
    assert "t=11.0" in payload.timeline_text
    assert "t=15.0" in payload.timeline_text


def test_build_answer_prompt_payload_requests_short_issue_answer():
    payload = build_answer_prompt_payload(
        question="What was the first issue I had with my new car after its first service?",
        hits=[
            {
                "event_id": "evt-gps",
                "session_id": "sess-car",
                "content": "I had an issue with my car's GPS system on 3/22.",
                "score": 0.9,
                "turn_id": "sess-car:turn-3",
            }
        ],
        evidence_bundles=[],
        timeline_summary=[
            {
                "timestamp": 1.0,
                "session_id": "sess-service",
                "turn_id": "sess-service:turn-1",
                "author_type": "user",
                "summary": "I got my car serviced for the first time on March 15th.",
            },
            {
                "timestamp": 3.0,
                "session_id": "sess-car",
                "turn_id": "sess-car:turn-3",
                "author_type": "user",
                "summary": "I had an issue with my car's GPS system on 3/22.",
            },
        ],
    )

    assert payload.short_answer_instruction.startswith(
        "For issue or event questions, answer with the short issue name"
    )


def test_build_answer_prompt_payload_truncates_assistant_evidence():
    long_assistant_content = "A" * 500
    short_user_content = "I visited Paris last summer."

    payload = build_answer_prompt_payload(
        question="Where did I travel?",
        hits=[
            {
                "event_id": "evt-1",
                "session_id": "sess-1",
                "content": long_assistant_content,
                "score": 0.9,
                "turn_id": "turn-1",
                "metadata": {"author_type": "assistant"},
            },
            {
                "event_id": "evt-2",
                "session_id": "sess-1",
                "content": short_user_content,
                "score": 0.8,
                "turn_id": "turn-2",
                "metadata": {"author_type": "user"},
            },
        ],
        evidence_bundles=[
            {
                "session_id": "sess-1",
                "events": [
                    {
                        "turn_id": "turn-1",
                        "timestamp": 1.0,
                        "author_type": "assistant",
                        "content": long_assistant_content,
                    },
                    {
                        "turn_id": "turn-2",
                        "timestamp": 2.0,
                        "author_type": "user",
                        "content": short_user_content,
                    },
                ],
            }
        ],
    )

    # Assistant evidence in hits is truncated
    assert long_assistant_content not in payload.evidence_text
    assert "A" * 300 + "..." in payload.evidence_text
    # User evidence is kept intact
    assert short_user_content in payload.evidence_text
    # Assistant content in bundles is also truncated
    assert long_assistant_content not in payload.bundle_text
    assert "A" * 300 + "..." in payload.bundle_text
    # User content in bundles is kept intact
    assert short_user_content in payload.bundle_text
