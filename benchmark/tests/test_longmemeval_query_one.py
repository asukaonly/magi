"""Tests for single-question LongMemEval query debugging helpers."""

from __future__ import annotations

import asyncio

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQueryResult

from benchmark.longmemeval.query_one import build_single_query_payload, select_question_row


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


class _FakeQueryService:
    def __init__(self, result: EvalMemoryQueryResult) -> None:
        self.result = result
        self.queries: list[object] = []

    async def query_memory(self, query):
        self.queries.append(query)
        return self.result


def test_select_question_row_returns_matching_question() -> None:
    rows = [_build_sample_row("q-1"), _build_sample_row("q-2")]

    row = select_question_row(rows, "q-2")

    assert row["question_id"] == "q-2"


def test_build_single_query_payload_returns_debug_shape() -> None:
    service = _FakeQueryService(
        EvalMemoryQueryResult(
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
    )

    payload = asyncio.run(
        build_single_query_payload(
            row=_build_sample_row(),
            eval_service=service,
            run_id="run-1",
            answer_with_llm=True,
        )
    )

    assert service.queries[0].answer_with_llm is True
    assert payload["question_id"] == "q-1"
    assert payload["expected_answer"] == "Sushi"
    assert payload["hypothesis"] == "Sushi"
    assert payload["retrieved_session_ids"] == ["sess-2"]
    assert payload["answer_trace"]["answer_source"] == "llm"
