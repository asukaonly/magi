"""Tests for LongMemEval replay runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQueryResult

from benchmark.common.io import read_jsonl
from benchmark.longmemeval.runner import (
    run_longmemeval_rows,
    synthesize_hypothesis_from_hits,
)


@dataclass
class FakeEvalService:
    results_by_namespace: dict[str, EvalMemoryQueryResult]

    def __post_init__(self) -> None:
        self.write_calls: list[tuple[str, int]] = []
        self.query_namespaces: list[str] = []

    async def write_records(self, *, namespace: str, records):
        self.write_calls.append((namespace, len(records)))
        return [{"namespace": namespace, "count": len(records)}]

    async def query_memory(self, query):
        self.query_namespaces.append(query.namespace)
        return self.results_by_namespace[query.namespace]


def _build_sample_row(question_id: str = "q-1") -> dict[str, object]:
    return {
        "question_id": question_id,
        "question_type": "multi-session",
        "question": "What food do I prefer?",
        "answer": "Sushi",
        "question_date": "2024-01-10",
        "answer_session_ids": ["sess-2"],
        "haystack_session_ids": ["sess-1", "sess-2"],
        "haystack_dates": ["2024-01-01", "2024-01-05"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I like pasta."},
            ],
            [
                {"role": "user", "content": "Actually sushi is my favorite.", "has_answer": True},
            ],
        ],
    }


def test_runner_replays_one_sample_and_writes_prediction_files(tmp_path) -> None:
    namespace = "benchmark/longmemeval/run-1/q-1"
    service = FakeEvalService(
        results_by_namespace={
            namespace: EvalMemoryQueryResult(
                hits=[
                    EvalMemoryHit(
                        event_id="evt-1",
                        session_id="sess-2",
                        turn_id="sess-2:turn-1",
                        score=0.99,
                        content="Actually sushi is my favorite.",
                    )
                ],
                trace={"intent_source": "rule"},
            )
        }
    )

    artifacts = asyncio.run(
        run_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
        )
    )

    assert service.write_calls == [(namespace, 2)]
    assert service.query_namespaces == [namespace]

    predictions = read_jsonl(artifacts.predictions_path)
    assert predictions == [
        {
            "question_id": "q-1",
            "hypothesis": "Actually sushi is my favorite.",
        }
    ]

    traced = read_jsonl(artifacts.predictions_with_trace_path)
    assert traced[0]["question_id"] == "q-1"
    assert traced[0]["retrieved_session_ids"] == ["sess-2"]
    assert traced[0]["trace"]["intent_source"] == "rule"


def test_runner_uses_run_specific_namespaces_to_avoid_stale_memory(tmp_path) -> None:
    first_namespace = "benchmark/longmemeval/run-1/q-1"
    second_namespace = "benchmark/longmemeval/run-2/q-1"
    service = FakeEvalService(
        results_by_namespace={
            first_namespace: EvalMemoryQueryResult(
                hits=[
                    EvalMemoryHit(
                        event_id="evt-1",
                        session_id="sess-1",
                        turn_id="sess-1:turn-1",
                        score=0.7,
                        content="Old favorite: pasta.",
                    )
                ]
            ),
            second_namespace: EvalMemoryQueryResult(
                hits=[
                    EvalMemoryHit(
                        event_id="evt-2",
                        session_id="sess-2",
                        turn_id="sess-2:turn-1",
                        score=0.9,
                        content="Actually sushi is my favorite.",
                    )
                ]
            ),
        }
    )

    first_artifacts = asyncio.run(
        run_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
        )
    )
    second_artifacts = asyncio.run(
        run_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-2",
            output_root=tmp_path,
        )
    )

    assert service.query_namespaces == [first_namespace, second_namespace]
    assert read_jsonl(first_artifacts.predictions_path)[0]["hypothesis"] == "Old favorite: pasta."
    assert read_jsonl(second_artifacts.predictions_path)[0]["hypothesis"] == "Actually sushi is my favorite."


def test_synthesizer_falls_back_to_unknown_when_no_hits_exist() -> None:
    assert synthesize_hypothesis_from_hits(hits=[]) == "unknown"
