"""Tests for LoCoMo dataset adaptation."""

from __future__ import annotations

from datetime import datetime, timezone

from benchmark.locomo.adapter import adapt_locomo_sample


def _build_sample() -> dict[str, object]:
    return {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Caroline",
            "speaker_b": "Melanie",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {
                    "speaker": "Caroline",
                    "dia_id": "D1:1",
                    "text": "I joined a support group.",
                },
                {
                    "speaker": "Melanie",
                    "dia_id": "D1:2",
                    "text": "I painted a sunrise.",
                    "query": "sunrise lake painting reference",
                    "blip_caption": "a lake sunrise painting",
                },
            ],
            "session_2_date_time": "2:14 pm on 25 May, 2023",
            "session_2": [
                {
                    "speaker": "Caroline",
                    "dia_id": "D2:1",
                    "text": "I researched adoption agencies.",
                },
            ],
        },
        "qa": [
            {
                "question": "What did Caroline join?",
                "answer": "support group",
                "evidence": ["D1:1"],
                "category": 4,
            },
            {
                "question": "What did Caroline research?",
                "answer": "adoption agencies",
                "evidence": ["D2:1"],
                "category": 1,
            },
        ],
    }


def test_adapter_converts_sample_into_shared_replay_records_and_queries() -> None:
    adapted = adapt_locomo_sample(_build_sample(), namespace="benchmark/locomo/run-1/conv-test")

    assert adapted.sample_id == "conv-test"
    assert adapted.speaker_a == "Caroline"
    assert adapted.speaker_b == "Melanie"
    assert [record.session_id for record in adapted.replay_records] == [
        "session_1",
        "session_1",
        "session_2",
    ]
    assert [record.turn_id for record in adapted.replay_records] == ["D1:1", "D1:2", "D2:1"]
    assert adapted.replay_records[0].role == "user"
    assert adapted.replay_records[1].role == "user"
    assert 'Caroline said, "I joined a support group."' in adapted.replay_records[0].content
    assert "Nearby conversation context:" not in adapted.replay_records[0].content
    assert "shared an image: a lake sunrise painting" in adapted.replay_records[1].content
    assert "image search query: sunrise lake painting reference" in adapted.replay_records[1].content
    assert "Previous turn D1:1 (Caroline): I joined a support group." in adapted.replay_records[1].content
    assert adapted.replay_records[2].metadata["dia_id"] == "D2:1"
    assert adapted.replay_records[0].metadata["neighbor_context_window"] == 0
    assert adapted.replay_records[1].metadata["image_query"] == "sunrise lake painting reference"
    assert adapted.replay_records[1].metadata["neighbor_context_window"] == 2

    assert [qa.question_id for qa in adapted.qa_entries] == [
        "conv-test:qa-1",
        "conv-test:qa-2",
    ]
    assert adapted.qa_entries[0].category_label == "single-hop"
    assert adapted.qa_entries[0].answer_session_ids == ["session_1"]
    assert adapted.qa_entries[1].answer_session_ids == ["session_2"]
    assert adapted.qa_entries[0].query.namespace == "benchmark/locomo/run-1/conv-test"


def test_adapter_parses_locomo_session_dates() -> None:
    adapted = adapt_locomo_sample(_build_sample(), namespace="benchmark/locomo/run-1/conv-test")

    expected = datetime.strptime(
        "1:56 PM ON 8 May, 2023",
        "%I:%M %p ON %d %B, %Y",
    ).replace(tzinfo=timezone.utc).timestamp()
    assert adapted.replay_records[0].timestamp == expected
    assert adapted.replay_records[1].timestamp > adapted.replay_records[0].timestamp
    assert adapted.qa_entries[0].query.query_timestamp > adapted.replay_records[-1].timestamp


def test_adapter_uses_numeric_session_order() -> None:
    sample = _build_sample()
    conversation = sample["conversation"]
    assert isinstance(conversation, dict)
    conversation["session_10_date_time"] = "3:00 pm on 1 June, 2023"
    conversation["session_10"] = [
        {"speaker": "Caroline", "dia_id": "D10:1", "text": "This happened later."}
    ]

    adapted = adapt_locomo_sample(sample, namespace="benchmark/locomo/run-1/conv-test")

    assert [record.turn_id for record in adapted.replay_records][-1] == "D10:1"
