"""Tests for LoCoMo query-only helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQueryResult

from benchmark.common.io import read_jsonl
from benchmark.locomo.query_dataset import query_locomo_samples


@dataclass
class FakeQueryService:
    results: list[EvalMemoryQueryResult]

    def __post_init__(self) -> None:
        self.queries: list[object] = []

    async def query_memory(self, query):
        self.queries.append(query)
        return self.results[len(self.queries) - 1]


def _build_sample() -> dict[str, object]:
    return {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Caroline",
            "speaker_b": "Melanie",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {"speaker": "Caroline", "dia_id": "D1:1", "text": "I joined a support group."},
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
                "question": "What city did Caroline move to?",
                "answer": "Paris",
                "evidence": [],
                "category": 5,
            },
        ],
    }


def test_query_script_reuses_sample_namespace_and_writes_locomo_outputs(tmp_path) -> None:
    service = FakeQueryService(
        results=[
            EvalMemoryQueryResult(
                hits=[
                    EvalMemoryHit(
                        event_id="evt-1",
                        session_id="session_1",
                        turn_id="D1:1",
                        score=0.99,
                        content='Caroline said, "I joined a support group."',
                    )
                ],
                trace={"intent_source": "rule"},
                answer="support group",
            ),
            EvalMemoryQueryResult(hits=[], trace={"intent_source": "rule"}),
        ]
    )
    progress_events: list[dict[str, object]] = []

    artifacts = asyncio.run(
        query_locomo_samples(
            samples=[_build_sample()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            progress_reporter=lambda progress: progress_events.append(asdict(progress)),
            answer_with_llm=True,
        )
    )

    assert [query.namespace for query in service.queries] == [
        "benchmark/locomo/run-1/conv-test",
        "benchmark/locomo/run-1/conv-test",
    ]
    assert all(query.answer_with_llm is True for query in service.queries)
    assert progress_events[0]["question_id"] == "conv-test:qa-1"
    assert progress_events[1]["question_id"] == "conv-test:qa-2"

    predictions = read_jsonl(artifacts.predictions_path)
    assert predictions == [
        {
            "question_id": "conv-test:qa-1",
            "sample_id": "conv-test",
            "qa_index": 0,
            "category": 4,
            "category_label": "single-hop",
            "hypothesis": "support group",
        },
        {
            "question_id": "conv-test:qa-2",
            "sample_id": "conv-test",
            "qa_index": 1,
            "category": 5,
            "category_label": "adversarial",
            "hypothesis": "No information available",
        },
    ]
    locomo_payload = json.loads(artifacts.locomo_predictions_path.read_text(encoding="utf-8"))
    assert locomo_payload[0]["qa"][0]["magi_prediction"] == "support group"
    assert locomo_payload[0]["qa"][1]["magi_prediction"] == "No information available"
    assert locomo_payload[0]["qa"][0]["magi_context"] == ["D1:1"]

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["overall_f1"] == 1.0
    assert summary["category_metrics"]["4"]["count"] == 1
    assert summary["category_metrics"]["5"]["f1"] == 1.0
