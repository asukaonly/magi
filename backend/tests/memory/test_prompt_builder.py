from __future__ import annotations

from magi.memory.answering.prompt_builder import build_answer_prompt_payload, is_preference_question


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
    assert "t=11.0" in payload.timeline_text
    assert "t=15.0" in payload.timeline_text
    assert "1970-01-01" in payload.timeline_text  # human-readable date present
    assert "sess-webinar" in payload.bundle_text
    assert "t=14.0" in payload.bundle_text
    assert "1970-01-01" in payload.bundle_text  # human-readable date present


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


class TestIsPreferenceQuestion:
    """Tests for preference / recommendation question detection."""

    def test_recommend_keyword(self):
        assert is_preference_question("Can you recommend a show or movie for me to watch tonight?")

    def test_suggest_keyword(self):
        assert is_preference_question("Can you suggest a hotel for my upcoming trip to Miami?")

    def test_any_tips(self):
        assert is_preference_question("My kitchen's becoming a bit of a mess again. Any tips for keeping it clean?")

    def test_any_suggestions(self):
        assert is_preference_question("I am planning another theme park weekend; do you have any suggestions?")

    def test_what_do_you_think(self):
        assert is_preference_question("I'm trying to decide whether to buy a NAS device now or wait. What do you think?")

    def test_do_you_think_it_might(self):
        assert is_preference_question("I've been sneezing quite a bit lately. Do you think it might be my living room?")

    def test_documentary_recommendations(self):
        assert is_preference_question("I've got some free time tonight, any documentary recommendations?")

    def test_factual_question_not_detected(self):
        assert not is_preference_question("What breed is my dog?")

    def test_temporal_question_not_detected(self):
        assert not is_preference_question("How many days ago did I attend the Maundy Thursday service?")

    def test_counting_question_not_detected(self):
        assert not is_preference_question("How many fish do I have in total?")


def test_build_answer_prompt_payload_includes_preference_instruction():
    payload = build_answer_prompt_payload(
        question="Can you recommend a show or movie for me to watch tonight?",
        hits=[
            {
                "event_id": "evt-comedy",
                "session_id": "sess-comedy",
                "content": "I really enjoy stand-up comedy specials, especially the storytelling style.",
                "score": 0.9,
                "turn_id": "sess-comedy:turn-2",
            }
        ],
        evidence_bundles=[],
        timeline_summary=[],
    )

    assert "The user would prefer" in payload.preference_instruction
    assert "unknown" in payload.preference_instruction.lower()


def test_build_answer_prompt_payload_no_preference_instruction_for_factual():
    payload = build_answer_prompt_payload(
        question="What is the name of my cat?",
        hits=[],
        evidence_bundles=[],
        timeline_summary=[],
    )

    assert payload.preference_instruction == ""
