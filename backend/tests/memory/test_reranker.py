"""Tests for retrieval reranker backends."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalConfig
from magi.memory.hybrid_retrieval.reranker import (
    HeuristicRetrievalReranker,
    LLMRetrievalReranker,
    LocalCLIRerankerClient,
    build_local_cli_reranker_client,
)


@pytest.mark.asyncio
async def test_llm_reranker_reorders_candidates_with_model_scores(monkeypatch: pytest.MonkeyPatch):
    config = RetrievalConfig(
        reranker_enabled=True,
        reranker_backend="llm",
        reranker_layers=("L1",),
        reranker_top_k=2,
        reranker_mode="remote",
        reranker_remote_provider_id="openai",
        reranker_remote_model="gpt-4o-mini",
    )
    bridge = SimpleNamespace(
        chat_response=AsyncMock(
            side_effect=[
                SimpleNamespace(content='{"score": 0.05}'),
                SimpleNamespace(content='{"score": 0.95}'),
            ]
        )
    )
    base_results = [
        {
            "event_id": "user-fact",
            "content": "The GPS failed after the first service.",
            "timestamp": 2000.0,
            "retrieval_score": 0.8,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.8},
        },
        {
            "event_id": "assistant-answer",
            "content": "The first issue after service was the GPS problem.",
            "timestamp": 2100.0,
            "retrieval_score": 0.4,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.4},
        },
    ]

    async def _fake_base_rerank(self, *, layer, results, query, fused_scores):  # type: ignore[no-untyped-def]
        return list(base_results)

    monkeypatch.setattr(HeuristicRetrievalReranker, "rerank", _fake_base_rerank)

    reranker = LLMRetrievalReranker(config, bridge_builder=lambda _config: bridge)

    results = await reranker.rerank(
        layer="L1",
        results=[
            {"event_id": "user-fact", "content": "The GPS failed after the first service.", "timestamp": 2000.0},
            {"event_id": "assistant-answer", "content": "The first issue after service was the GPS problem.", "timestamp": 2100.0},
        ],
        query="What was the first issue after the first service?",
        fused_scores={"user-fact": 0.8, "assistant-answer": 0.4},
    )

    assert [item["event_id"] for item in results] == ["assistant-answer", "user-fact"]
    assert results[0]["retrieval_trace"]["backend"] == "llm"
    assert results[0]["retrieval_trace"]["llm_score"] == 0.95
    assert results[0]["reranker_backend"] == "llm"


@pytest.mark.asyncio
async def test_llm_reranker_falls_back_when_bridge_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    config = RetrievalConfig(
        reranker_enabled=True,
        reranker_backend="llm",
        reranker_layers=("L1",),
        reranker_top_k=2,
        reranker_mode="remote",
        reranker_remote_provider_id="openai",
        reranker_remote_model="gpt-4o-mini",
    )
    base_results = [
        {
            "event_id": "user-fact",
            "content": "The GPS failed after the first service.",
            "timestamp": 2000.0,
            "retrieval_score": 0.8,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.8},
        },
        {
            "event_id": "assistant-answer",
            "content": "The first issue after service was the GPS problem.",
            "timestamp": 2100.0,
            "retrieval_score": 0.4,
            "retrieval_trace": {"backend": "heuristic", "base_rrf_score": 0.4},
        },
    ]

    async def _fake_base_rerank(self, *, layer, results, query, fused_scores):  # type: ignore[no-untyped-def]
        return list(base_results)

    monkeypatch.setattr(HeuristicRetrievalReranker, "rerank", _fake_base_rerank)

    reranker = LLMRetrievalReranker(config, bridge_builder=lambda _config: None)

    results = await reranker.rerank(
        layer="L1",
        results=[
            {"event_id": "user-fact", "content": "The GPS failed after the first service.", "timestamp": 2000.0},
            {"event_id": "assistant-answer", "content": "The first issue after service was the GPS problem.", "timestamp": 2100.0},
        ],
        query="What was the first issue after the first service?",
        fused_scores={"user-fact": 0.8, "assistant-answer": 0.4},
    )

    assert [item["event_id"] for item in results] == ["user-fact", "assistant-answer"]
    assert results[0]["retrieval_trace"]["backend"] == "heuristic"
    assert results[0]["retrieval_trace"]["llm_fallback_reason"] == "bridge_unavailable"


@pytest.mark.asyncio
async def test_local_cli_reranker_client_runs_llama_cli_with_external_model(tmp_path: Path):
    model_path = tmp_path / "reranker.gguf"
    model_path.write_text("fake")
    recorded: dict[str, object] = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b'{"score": 0.61}', b"")

    async def _runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        return _Proc()

    client = LocalCLIRerankerClient(
        cli_path="/usr/local/bin/llama-cli",
        model_path=model_path,
        max_context_tokens=2048,
        process_runner=_runner,
    )

    response = await client.chat_response(
        system_prompt="Return JSON",
        messages=[{"role": "user", "content": "score this candidate"}],
        max_tokens=32,
        temperature=0.0,
        json_mode=True,
        timeout_seconds=0.5,
    )

    assert response.content == '{"score": 0.61}'
    assert recorded["args"][0] == "/usr/local/bin/llama-cli"
    assert "--model" in recorded["args"]
    assert str(model_path) in recorded["args"]


def test_build_local_cli_reranker_client_resolves_managed_model_dir(tmp_path: Path):
    managed_dir = tmp_path / "managed-reranker"
    managed_dir.mkdir()
    model_path = managed_dir / "model.gguf"
    model_path.write_text("fake")

    config = RetrievalConfig(
        reranker_backend="llm",
        reranker_mode="local",
        reranker_local_model_source="managed",
        reranker_local_managed_model_id="demo-model",
    )
    runtime_paths = SimpleNamespace(
        managed_reranker_model_dir=lambda model_id: managed_dir if model_id == "demo-model" else tmp_path / model_id
    )

    client = build_local_cli_reranker_client(
        config,
        runtime_paths=runtime_paths,
        cli_path_finder=lambda _binary: "/usr/local/bin/llama-cli",
    )

    assert isinstance(client, LocalCLIRerankerClient)
    assert client.model_path == model_path
