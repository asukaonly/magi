from __future__ import annotations

from magi.memory.answering.prompt_builder import (
    _truncate_assistant_content,
    build_answer_prompt_payload,
)


class TestTruncateAssistantContent:
    """Sentence-based truncation for assistant replies."""

    def test_short_content_unchanged(self):
        text = "Great idea! I'll help you with that."
        assert _truncate_assistant_content(text) == text

    def test_long_content_keeps_first_sentences(self):
        sentences = [
            "Arctic Monkeys and The Neighbourhood are both fantastic live acts, and their music is perfect for fans of indie and alternative rock.",
            "If you're enjoying their music on Spotify, you'll love them even more live.",
            "Here are a few more recommendations that might fit your musical taste and concert-going preferences.",
            "The Black Keys offer a bluesy, guitar-driven sound that appeals to a wide audience of rock enthusiasts.",
            "Tame Impala blends psychedelic and electronic elements into mesmerizing soundscapes that transport listeners.",
        ]
        content = " ".join(sentences)
        result = _truncate_assistant_content(content, max_sentences=3, hard_max=400)
        # First 3 sentences should be kept
        assert "Spotify" in result
        assert "recommendations" in result
        # 4th+ sentences should be dropped
        assert "Black Keys" not in result

    def test_hard_max_respected(self):
        result = _truncate_assistant_content("A" * 600, max_sentences=3, hard_max=500)
        assert len(result) <= 505  # small tolerance for " ..."

    def test_preserves_single_long_sentence(self):
        long_sent = "This is a very long sentence " * 30 + "with an important fact."
        result = _truncate_assistant_content(long_sent, max_sentences=3, hard_max=500)
        assert len(result) <= 505
        assert result.endswith("...")


class TestDedupFocusHints:
    """When all hits are deduped, evidence_text shows bundle focus hints."""

    def test_all_deduped_shows_focus_hint(self):
        payload = build_answer_prompt_payload(
            question="What streaming service do I use?",
            hits=[
                {"session_id": "s1", "turn_id": "s1:turn-3", "content": "I use Spotify."},
                {"session_id": "s1", "turn_id": "s1:turn-5", "content": "My Spotify playlist."},
            ],
            evidence_bundles=[
                {
                    "session_id": "s1",
                    "events": [
                        {"turn_id": "s1:turn-3", "timestamp": 1.0, "author_type": "user", "content": "I use Spotify."},
                        {"turn_id": "s1:turn-5", "timestamp": 2.0, "author_type": "user", "content": "My Spotify playlist."},
                    ],
                }
            ],
        )
        assert "bundle 1" in payload.evidence_text
        assert "2 hits" in payload.evidence_text
        assert "focus" in payload.evidence_text

    def test_partial_dedup_keeps_unique_hits(self):
        payload = build_answer_prompt_payload(
            question="What do I like?",
            hits=[
                {"session_id": "s1", "turn_id": "s1:turn-3", "content": "I like cats."},
                {"session_id": "s2", "turn_id": "s2:turn-1", "content": "I also like dogs."},
            ],
            evidence_bundles=[
                {
                    "session_id": "s1",
                    "events": [
                        {"turn_id": "s1:turn-3", "timestamp": 1.0, "author_type": "user", "content": "I like cats."},
                    ],
                }
            ],
        )
        # s2:turn-1 is not in any bundle, should appear in evidence
        assert "s2:turn-1" in payload.evidence_text
        assert "I also like dogs" in payload.evidence_text

    def test_no_hits_no_bundles(self):
        payload = build_answer_prompt_payload(
            question="Hello?",
            hits=[],
            evidence_bundles=[],
        )
        assert payload.evidence_text == "(no additional evidence)"


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
    assert "sess-workshop" in payload.timeline_text
    assert "sess-webinar" in payload.timeline_text
    assert "sess-webinar" in payload.bundle_text



