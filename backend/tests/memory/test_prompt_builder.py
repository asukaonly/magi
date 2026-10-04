from __future__ import annotations

import pytest

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

    @pytest.mark.parametrize(
        "content,limit,expected",
        [
            ("A" * 600, 500, "A" * 500 + " ..."),
            ("alpha beta gamma delta epsilon", 20, "alpha beta gamma ..."),
            ("alpha beta gamma", 16, "alpha beta gamma"),
        ],
    )
    def test_hard_cap_retains_the_prefix_and_truncation_marker(self, content, limit, expected):
        assert _truncate_assistant_content(content, max_sentences=3, hard_max=limit) == expected


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

    @pytest.mark.parametrize("with_evidence", [False, True])
    def test_prompt_assembly_keeps_unique_hits_and_deduplicates_bundled_turns(self, with_evidence):
        payload = build_answer_prompt_payload(
            question="What do I like?",
            hits=(
                [
                    {"session_id": "s1", "turn_id": "s1:turn-3", "content": "I like cats."},
                    {"session_id": "s2", "turn_id": "s2:turn-1", "content": "I also like dogs."},
                ]
                if with_evidence
                else []
            ),
            evidence_bundles=(
                [
                    {
                        "session_id": "s1",
                        "events": [
                            {
                                "turn_id": "s1:turn-3",
                                "timestamp": 1.0,
                                "author_type": "user",
                                "content": "I like cats.",
                            }
                        ],
                    }
                ]
                if with_evidence
                else []
            ),
        )
        assert payload.evidence_text == (
            "[2] session=s2 turn=s2:turn-1\nI also like dogs."
            if with_evidence
            else "(no additional evidence)"
        )
        assert payload.bundle_text == (
            "[bundle 1] session=s1\n- role=user turn=s1:turn-3: I like cats."
            if with_evidence
            else "(no grouped evidence bundles)"
        )
        assert payload.timeline_text == "(no timeline summary available)"
        assert payload.prioritize_timeline is False
        assert payload.timeline_instruction == ""
