"""Tests for the LongMemEval backend HTTP client."""

from __future__ import annotations

import asyncio

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord

from benchmark.longmemeval.backend_client import BackendEvalService


def test_backend_client_posts_replay_records_to_eval_endpoint() -> None:
    service = BackendEvalService("http://localhost:8000")
    calls: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"written": 1, "results": [{"event_id": "evt-1"}]}

    service._post_json_sync = fake_post  # type: ignore[method-assign]

    asyncio.run(
        service.write_records(
            namespace="benchmark/longmemeval/run-1/q-1",
            records=[
                EvalMemoryWriteRecord(
                    namespace="benchmark/longmemeval/run-1/q-1",
                    session_id="sess-1",
                    timestamp=1.0,
                    role="user",
                    content="I like pasta.",
                    turn_id="sess-1:turn-1",
                    metadata={"source_dataset": "longmemeval"},
                )
            ],
        )
    )

    assert calls == [
        (
            "/api/memory/eval/replay",
            {
                "namespace": "benchmark/longmemeval/run-1/q-1",
                "records": [
                    {
                        "namespace": "benchmark/longmemeval/run-1/q-1",
                        "session_id": "sess-1",
                        "timestamp": 1.0,
                        "role": "user",
                        "content": "I like pasta.",
                        "turn_id": "sess-1:turn-1",
                        "metadata": {"source_dataset": "longmemeval"},
                    }
                ],
            },
        )
    ]


def test_backend_client_restores_query_results_from_eval_endpoint() -> None:
    service = BackendEvalService("http://localhost:8000")

    def fake_post(path: str, payload: dict):
        assert path == "/api/memory/eval/query"
        assert payload["namespace"] == "benchmark/longmemeval/run-1/q-1"
        return {
            "hits": [
                {
                    "event_id": "evt-1",
                    "session_id": "sess-2",
                    "turn_id": "sess-2:turn-1",
                    "score": 0.99,
                    "content": "Actually sushi is my favorite.",
                    "metadata": {"source_dataset": "longmemeval"},
                }
            ],
            "trace": {"intent_source": "rule"},
            "retrieved_session_ids": ["sess-2"],
            "retrieved_turn_ids": ["sess-2:turn-1"],
            "retrieved_event_ids": ["evt-1"],
        }

    service._post_json_sync = fake_post  # type: ignore[method-assign]

    result = asyncio.run(
        service.query_memory(
            EvalMemoryQuery(
                namespace="benchmark/longmemeval/run-1/q-1",
                query="What food do I prefer?",
            )
        )
    )

    assert result.retrieved_session_ids == ["sess-2"]
    assert result.retrieved_turn_ids == ["sess-2:turn-1"]
    assert result.trace["intent_source"] == "rule"


def test_backend_client_posts_finalize_replay_request() -> None:
    service = BackendEvalService("http://localhost:8000")
    calls: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict):
        calls.append((path, payload))
        return {
            "summaries": {"hour": {"summary_id": "sum-hour-1"}},
            "l2_pipeline_stats": {"extract_completed": 9},
        }

    service._post_json_sync = fake_post  # type: ignore[method-assign]

    result = asyncio.run(service.finalize_replay())

    assert calls == [
        (
            "/api/memory/eval/finalize-replay",
            {"period_types": ["hour", "day", "week", "month"]},
        )
    ]
    assert result["summaries"]["hour"]["summary_id"] == "sum-hour-1"
