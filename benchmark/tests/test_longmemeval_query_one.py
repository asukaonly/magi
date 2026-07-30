"""Tests for single-question LongMemEval query debugging helpers."""

from __future__ import annotations

import asyncio
import io
from contextlib import redirect_stdout

from magi.memory.eval_support.contracts import EvalMemoryHit, EvalMemoryQueryResult

from benchmark.longmemeval.backend_client import SESSION_TOKEN_ENV
from benchmark.longmemeval.query_one import build_single_query_payload, main, select_question_row


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
            evidence_bundles=[
                {
                    "session_id": "sess-2",
                    "hit_event_ids": ["evt-1"],
                    "events": [
                        {
                            "event_id": "evt-1",
                            "turn_id": "sess-2:turn-1",
                            "content": "Actually sushi is my favorite.",
                        }
                    ],
                    "neighbor_expansion_applied": False,
                }
            ],
            timeline_summary=[
                {
                    "timestamp": 1.0,
                    "session_id": "sess-2",
                    "turn_id": "sess-2:turn-1",
                    "author_type": "user",
                    "summary": "Actually sushi is my favorite.",
                    "supporting_event_ids": ["evt-1"],
                    "reason_codes": ["event_statement"],
                }
            ],
            trace={"intent_source": "rule"},
            answer="Sushi",
            answer_trace={"answer_source": "llm", "prompt": "Question: What food do I prefer?"},
        )
    )

    payload = asyncio.run(
        build_single_query_payload(
            row=_build_sample_row(),
            eval_service=service,
            run_id="run-1",
            answer_with_llm=True,
            show_prompt=True,
        )
    )

    assert service.queries[0].answer_with_llm is True
    assert service.queries[0].show_prompt is True
    assert payload["question_id"] == "q-1"
    assert payload["expected_answer"] == "Sushi"
    assert payload["hypothesis"] == "Sushi"
    assert payload["retrieved_session_ids"] == ["sess-2"]
    assert payload["evidence_bundles"][0]["session_id"] == "sess-2"
    assert payload["timeline_summary"][0]["summary"] == "Actually sushi is my favorite."
    assert payload["answer_trace"]["answer_source"] == "llm"
    assert "Question: What food do I prefer?" in payload["answer_trace"]["prompt"]


def test_build_single_query_payload_propagates_explicit_mode() -> None:
    service = _FakeQueryService(
        EvalMemoryQueryResult(
            hits=[],
            trace={"intent_source": "rule"},
        )
    )

    payload = asyncio.run(
        build_single_query_payload(
            row=_build_sample_row(),
            eval_service=service,
            run_id="run-1",
            mode="detail",
        )
    )

    assert service.queries[0].mode == "detail"
    assert payload["question_id"] == "q-1"


def test_query_one_main_prints_progress_before_result(monkeypatch, tmp_path) -> None:
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(SESSION_TOKEN_ENV, "benchmark-session-token")

    monkeypatch.setattr(
        "benchmark.longmemeval.query_one.load_longmemeval_rows",
        lambda path: [_build_sample_row()],
    )
    monkeypatch.setattr(
        "benchmark.longmemeval.query_one.build_single_query_payload",
        lambda **kwargs: {
            "question_id": "q-1",
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "hypothesis": "Sushi",
        },
    )

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "--dataset",
                str(dataset_path),
                "--run-id",
                "run-1",
                "--question-id",
                "q-1",
                "--answer-with-llm",
                "--show-prompt",
            ]
        )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "Querying LongMemEval question_id=q-1" in output
    assert "answer_with_llm=True" in output
    assert '"hypothesis": "Sushi"' in output


def test_query_one_main_prints_selected_mode(monkeypatch, tmp_path) -> None:
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(SESSION_TOKEN_ENV, "benchmark-session-token")

    monkeypatch.setattr(
        "benchmark.longmemeval.query_one.load_longmemeval_rows",
        lambda path: [_build_sample_row()],
    )
    monkeypatch.setattr(
        "benchmark.longmemeval.query_one.build_single_query_payload",
        lambda **kwargs: {
            "question_id": "q-1",
            "namespace": "benchmark/longmemeval/run-1/q-1",
            "hypothesis": "Sushi",
        },
    )

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = main(
            [
                "--dataset",
                str(dataset_path),
                "--run-id",
                "run-1",
                "--question-id",
                "q-1",
                "--mode",
                "detail",
            ]
        )

    output = stdout.getvalue()
    assert exit_code == 0
    assert "mode=detail" in output
