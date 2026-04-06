"""Tests for LongMemEval query-only CLI helpers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQueryResult

from benchmark.common.io import read_jsonl
from benchmark.longmemeval.query_dataset import ERROR_HYPOTHESIS, query_longmemeval_rows


@dataclass
class FakeQueryService:
    results_by_namespace: dict[str, EvalMemoryQueryResult]

    def __post_init__(self) -> None:
        self.query_namespaces: list[str] = []
        self.queries: list[object] = []

    async def query_memory(self, query):
        self.queries.append(query)
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
            [{"role": "user", "content": "I like pasta."}],
            [{"role": "user", "content": "Actually sushi is my favorite.", "has_answer": True}],
        ],
    }


def test_query_script_reads_existing_namespaces_and_writes_outputs(tmp_path) -> None:
    namespace = "benchmark/longmemeval/run-1/q-1"
    progress_events: list[dict[str, object]] = []
    service = FakeQueryService(
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
        query_longmemeval_rows(
            rows=[_build_sample_row()],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            progress_reporter=lambda progress: progress_events.append(asdict(progress)),
        )
    )

    assert service.query_namespaces == [namespace]
    assert progress_events == [
        {
            "question_index": 1,
            "total_questions": 1,
            "question_id": "q-1",
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "hit_count": 1,
            "total_hit_count": 1,
        }
    ]
    assert read_jsonl(artifacts.predictions_path) == [
        {"question_id": "q-1", "hypothesis": "Actually sushi is my favorite."}
    ]
    assert read_jsonl(artifacts.predictions_with_trace_path)[0]["retrieved_session_ids"] == ["sess-2"]

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["total_questions"] == 1
    assert summary["session_recall_at_k"] == 1.0
    assert "retrieval_compression" in summary
    rc = summary["retrieval_compression"]
    assert rc["questions_measured"] == 1
    assert 0.0 < rc["mean_ratio"] < 1.0


def test_query_script_marks_unknown_when_memory_returns_no_hits(tmp_path) -> None:
    namespace = "benchmark/longmemeval/run-1/q-2_abs"
    service = FakeQueryService(
        results_by_namespace={
            namespace: EvalMemoryQueryResult(
                hits=[],
                trace={"intent_source": "rule_fallback"},
            )
        }
    )

    artifacts = asyncio.run(
        query_longmemeval_rows(
            rows=[_build_sample_row(question_id="q-2_abs") | {"answer": "unknown", "answer_session_ids": []}],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
        )
    )

    assert read_jsonl(artifacts.predictions_path) == [
        {"question_id": "q-2_abs", "hypothesis": "unknown"}
    ]


def test_query_script_prefers_llm_answer_when_present(tmp_path) -> None:
    namespace = "benchmark/longmemeval/run-1/q-3"
    service = FakeQueryService(
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
                answer="Sushi",
                answer_trace={"answer_source": "llm"},
            )
        }
    )

    artifacts = asyncio.run(
        query_longmemeval_rows(
            rows=[_build_sample_row(question_id="q-3")],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            answer_with_llm=True,
        )
    )

    assert read_jsonl(artifacts.predictions_path) == [
        {"question_id": "q-3", "hypothesis": "Sushi"}
    ]
    assert service.queries[0].answer_with_llm is True
    traced = read_jsonl(artifacts.predictions_with_trace_path)[0]
    assert traced["hypothesis"] == "Sushi"
    assert traced["answer_trace"]["answer_source"] == "llm"


def test_query_script_propagates_explicit_mode(tmp_path) -> None:
    namespace = "benchmark/longmemeval/run-1/q-4"
    service = FakeQueryService(
        results_by_namespace={
            namespace: EvalMemoryQueryResult(
                hits=[],
                trace={"intent_source": "rule"},
            )
        }
    )

    asyncio.run(
        query_longmemeval_rows(
            rows=[_build_sample_row(question_id="q-4")],
            eval_service=service,
            run_id="run-1",
            output_root=tmp_path,
            mode="detail",
        )
    )

    assert service.queries[0].mode == "detail"


def test_query_retries_on_error_and_marks_error_hypothesis(tmp_path) -> None:
    """When query_memory always raises, skip after retries and mark __error__."""

    call_count = 0

    class FailingService:
        async def query_memory(self, query):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("content filter triggered")

    artifacts = asyncio.run(
        query_longmemeval_rows(
            rows=[_build_sample_row(question_id="q-fail")],
            eval_service=FailingService(),
            run_id="run-1",
            output_root=tmp_path,
        )
    )

    assert call_count == 3  # MAX_QUERY_RETRIES
    predictions = read_jsonl(artifacts.predictions_path)
    assert predictions[0]["hypothesis"] == ERROR_HYPOTHESIS
    traced = read_jsonl(artifacts.predictions_with_trace_path)[0]
    assert traced["trace"]["skipped"] is True
    assert "RuntimeError" in traced["trace"]["error"]
