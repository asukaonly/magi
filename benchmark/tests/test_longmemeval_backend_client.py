"""Tests for the LongMemEval backend HTTP client."""

from __future__ import annotations

import asyncio
import socket

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
            "evidence_bundles": [
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
            "answer": "Sushi",
            "answer_trace": {"answer_source": "llm"},
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
    assert result.answer == "Sushi"
    assert result.answer_trace["answer_source"] == "llm"
    assert result.trace["intent_source"] == "rule"
    assert result.evidence_bundles[0]["session_id"] == "sess-2"


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


def test_backend_client_reads_l2_statistics_endpoint() -> None:
    service = BackendEvalService("http://localhost:8000")
    calls: list[str] = []

    def fake_get(path: str):
        calls.append(path)
        return {
            "extract_enqueued": 10,
            "extract_completed": 8,
            "extract_failed": 0,
            "extract_skipped": 1,
            "reconcile_enqueued": 2,
            "reconcile_completed": 2,
            "reconcile_failed": 0,
            "snapshot_enqueued": 1,
            "snapshot_completed": 1,
            "snapshot_failed": 0,
        }

    service._get_json_sync = fake_get  # type: ignore[method-assign]

    result = asyncio.run(service.get_l2_pipeline_stats())

    assert calls == ["/api/memory/l2/statistics"]
    assert result["extract_completed"] == 8


def test_backend_client_reads_background_pending_endpoint() -> None:
    service = BackendEvalService("http://localhost:8000")
    calls: list[str] = []

    def fake_get(path: str):
        calls.append(path)
        return {
            "l2": {"extract_pending": 0, "reconcile_pending": 0, "snapshot_pending": 0},
            "l1_embeddings": {"pending": 7, "worker_running": True},
            "l3_embeddings": {"pending": 3, "worker_running": True},
            "l4_embeddings": {"pending": 0, "worker_running": False},
            "all_idle": False,
        }

    service._get_json_sync = fake_get  # type: ignore[method-assign]

    result = asyncio.run(service.get_background_pending())

    assert calls == ["/api/memory/background/pending"]
    assert result["l1_embeddings"]["pending"] == 7
    assert result["all_idle"] is False


def test_backend_client_uses_configured_timeout_for_post_requests() -> None:
    service = BackendEvalService("http://localhost:8000", timeout_seconds=12.5)

    captured: list[float] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"hits":[],"trace":{}}'

    def fake_urlopen(req, timeout=None):
        _ = req
        captured.append(timeout)
        return _FakeResponse()

    import urllib.request as urllib_request

    original = urllib_request.urlopen
    urllib_request.urlopen = fake_urlopen  # type: ignore[assignment]
    try:
        asyncio.run(
            service.query_memory(
                EvalMemoryQuery(
                    namespace="benchmark/longmemeval/run-1/q-1",
                    query="What food do I prefer?",
                )
            )
        )
    finally:
        urllib_request.urlopen = original  # type: ignore[assignment]

    assert captured == [12.5]


def test_backend_client_wraps_post_timeouts_with_actionable_error() -> None:
    service = BackendEvalService("http://localhost:8000", timeout_seconds=3.0)

    def fake_urlopen(req, timeout=None):
        _ = (req, timeout)
        raise socket.timeout("timed out")

    import urllib.request as urllib_request

    original = urllib_request.urlopen
    urllib_request.urlopen = fake_urlopen  # type: ignore[assignment]
    try:
        try:
            asyncio.run(
                service.query_memory(
                    EvalMemoryQuery(
                        namespace="benchmark/longmemeval/run-1/q-1",
                        query="What food do I prefer?",
                    )
                )
            )
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected RuntimeError")
    finally:
        urllib_request.urlopen = original  # type: ignore[assignment]

    assert "/api/memory/eval/query" in message
    assert "timed out after 3.0s" in message
