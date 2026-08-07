"""Tests for the LongMemEval backend HTTP client."""

from __future__ import annotations

import asyncio
import socket

import pytest

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord

from benchmark.longmemeval.backend_client import BackendEvalService, SESSION_TOKEN_ENV


@pytest.fixture(autouse=True)
def _benchmark_session_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SESSION_TOKEN_ENV, "benchmark-session-token")


def test_backend_client_requires_non_empty_session_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SESSION_TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=SESSION_TOKEN_ENV):
        BackendEvalService("http://localhost:8000")

    monkeypatch.setenv(SESSION_TOKEN_ENV, "   ")
    with pytest.raises(RuntimeError, match="non-empty temporary credential"):
        BackendEvalService("http://localhost:8000")


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
            "timeline_summary": [
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
    assert result.timeline_summary[0]["summary"] == "Actually sushi is my favorite."


def test_backend_client_posts_eval_judge_requests_to_backend() -> None:
    service = BackendEvalService("http://localhost:8000")
    calls: list[tuple[str, dict]] = []

    def fake_post(path: str, payload: dict):
        calls.append((path, payload))
        return {
            "content": '{"label":"CORRECT","reasoning":"same"}',
            "model": "core-test-model",
            "llm_scenario": "core",
        }

    service._post_json_sync = fake_post  # type: ignore[method-assign]

    result = asyncio.run(
        service.judge_answer(
            system_prompt="Return JSON only.",
            prompt="Question: Q\nGold answer: A\nGenerated answer: A",
            max_tokens=256,
            temperature=0.0,
        )
    )

    assert calls == [
        (
            "/api/memory/eval/judge-answer",
            {
                "system_prompt": "Return JSON only.",
                "prompt": "Question: Q\nGold answer: A\nGenerated answer: A",
                "max_tokens": 256,
                "temperature": 0.0,
            },
        )
    ]
    assert result["content"] == '{"label":"CORRECT","reasoning":"same"}'


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

    result = asyncio.run(
        service.finalize_replay(
            generate_summaries=False,
            flush_l2_projection_jobs=True,
            drain_l2_edge_embeddings=False,
        )
    )

    assert calls == [
        (
            "/api/memory/eval/finalize-replay",
            {
                "period_types": ["hour", "day", "week", "month"],
                "generate_summaries": False,
                "flush_l2_projection_jobs": True,
                "drain_l2_edge_embeddings": False,
            },
        )
    ]
    assert result["summaries"]["hour"]["summary_id"] == "sum-hour-1"


def test_backend_client_reads_l2_stats_from_eval_finalize_status() -> None:
    service = BackendEvalService("http://localhost:8000")
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_post(path: str, payload: dict[str, object]):
        posts.append((path, payload))
        return {
            "l2_pipeline_stats": {
                "extract_enqueued": 10,
                "extract_completed": 8,
                "extract_failed": 0,
                "extract_skipped": 1,
                "extract_active": 1,
                "reconcile_enqueued": 2,
                "reconcile_completed": 2,
                "reconcile_failed": 0,
                "snapshot_enqueued": 1,
                "snapshot_completed": 1,
                "snapshot_failed": 0,
                "projection_backlog": {"pending": 0, "claimed": 2, "completed": 8, "failed": 0},
            },
        }

    service._post_json_sync = fake_post  # type: ignore[method-assign]

    result = asyncio.run(service.get_l2_pipeline_stats())

    assert posts == [
        (
            "/api/memory/eval/finalize-replay",
            {
                "period_types": [],
                "generate_summaries": False,
                "flush_l2_projection_jobs": False,
                "drain_l2_edge_embeddings": False,
            },
        )
    ]
    assert result["extract_completed"] == 8
    assert result["extract_active"] == 1
    assert result["projection_backlog"]["claimed"] == 2


def test_backend_client_overlays_eval_l2_stats_on_background_pending() -> None:
    service = BackendEvalService("http://localhost:8000")
    gets: list[str] = []
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_get(path: str):
        gets.append(path)
        return {
            "l2": {"extract_pending": 0, "reconcile_pending": 0, "snapshot_pending": 0},
            "l1_embeddings": {"pending": 7, "worker_running": True},
            "l2_edge_embeddings": {"pending": 0},
            "l3_embeddings": {"pending": 3, "worker_running": True},
            "l4_embeddings": {"pending": 0, "worker_running": False},
            "all_idle": False,
        }

    def fake_post(path: str, payload: dict[str, object]):
        posts.append((path, payload))
        return {
            "l2_pipeline_stats": {
                "extract_enqueued": 4,
                "extract_completed": 4,
                "extract_failed": 0,
                "extract_skipped": 0,
                "extract_active": 1,
                "reconcile_enqueued": 0,
                "reconcile_completed": 0,
                "reconcile_failed": 0,
                "reconcile_active": 0,
                "snapshot_enqueued": 0,
                "snapshot_completed": 0,
                "snapshot_failed": 0,
                "snapshot_active": 0,
                "projection_backlog": {"pending": 0, "claimed": 0, "completed": 4, "failed": 0},
            },
        }

    service._get_json_sync = fake_get  # type: ignore[method-assign]
    service._post_json_sync = fake_post  # type: ignore[method-assign]

    result = asyncio.run(service.get_background_pending())

    assert gets == ["/api/memory/background/pending"]
    assert posts == [
        (
            "/api/memory/eval/finalize-replay",
            {
                "period_types": [],
                "generate_summaries": False,
                "flush_l2_projection_jobs": False,
                "drain_l2_edge_embeddings": False,
            },
        )
    ]
    assert result["l2"]["extract_active"] == 1
    assert result["l2"]["extract_pending"] == 1
    assert result["l1_embeddings"]["pending"] == 7
    assert result["all_idle"] is False


def test_backend_client_uses_session_token_and_configured_timeout_for_post_requests() -> None:
    service = BackendEvalService("http://localhost:8000", timeout_seconds=12.5)

    captured: list[float] = []
    captured_headers: list[dict[str, str]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"hits":[],"trace":{}}'

    def fake_urlopen(req, timeout=None):
        captured.append(timeout)
        captured_headers.append({key.lower(): value for key, value in req.header_items()})
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
    assert captured_headers == [
        {
            "content-type": "application/json",
            "x-magi-session-token": "benchmark-session-token",
        }
    ]


def test_backend_client_uses_session_token_for_get_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BackendEvalService("http://localhost:8000")
    captured_headers: list[dict[str, str]] = []

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"all_idle":true}'

    def fake_urlopen(req, timeout=None):
        _ = timeout
        captured_headers.append({key.lower(): value for key, value in req.header_items()})
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = service._get_json_sync("/api/memory/background/pending")

    assert result == {"all_idle": True}
    assert captured_headers == [
        {
            "accept": "application/json",
            "x-magi-session-token": "benchmark-session-token",
        }
    ]


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
