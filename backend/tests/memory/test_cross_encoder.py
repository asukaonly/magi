"""Tests for cross-encoder reranker (mocked ONNX)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from magi.memory.hybrid_retrieval.cross_encoder import (
    CrossEncoderReranker,
    CrossEncoderScorer,
    _find_onnx_model,
)
from magi.memory.hybrid_retrieval.models import RetrievalConfig


# ---------------------------------------------------------------------------
# _find_onnx_model tests
# ---------------------------------------------------------------------------


def test_find_onnx_model_prefers_quantized(tmp_path: Path):
    (tmp_path / "model.onnx").touch()
    (tmp_path / "model_quantized.onnx").touch()
    result = _find_onnx_model(tmp_path)
    assert result is not None
    assert result.name == "model_quantized.onnx"


def test_find_onnx_model_onnx_subdir(tmp_path: Path):
    onnx_dir = tmp_path / "onnx"
    onnx_dir.mkdir()
    (onnx_dir / "model.onnx").touch()
    result = _find_onnx_model(tmp_path)
    assert result is not None
    assert result.name == "model.onnx"


def test_find_onnx_model_not_found(tmp_path: Path):
    result = _find_onnx_model(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# CrossEncoderReranker integration tests (mocked scorer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_encoder_reranker_combines_heuristic_and_ce():
    """CE scores should be combined with heuristic metadata adjustments."""
    config = RetrievalConfig(
        cross_encoder_enabled=True,
        cross_encoder_model_id="test-model",
        reranker_layers=("L1",),
        reranker_top_k=10,
    )
    reranker = CrossEncoderReranker(config)

    items = [
        {
            "event_id": "a",
            "content": "I ate sushi yesterday",
            "author_type": "user",
            "timestamp": 1000.0,
        },
        {
            "event_id": "b",
            "content": "I recommend eating more vegetables for better health. " * 5,
            "author_type": "assistant",
            "timestamp": 1001.0,
        },
    ]

    mock_scorer = AsyncMock()
    # CE says item b is more relevant, but heuristic metadata should adjust
    mock_scorer.score_pairs.return_value = [0.6, 0.8]

    mock_model_dir = Path("/fake/model/dir")

    with (
        patch(
            "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_model_dir",
            return_value=mock_model_dir,
        ),
        patch(
            "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
            return_value=mock_scorer,
        ),
    ):
        result = await reranker.rerank(
            layer="L1",
            results=items,
            query="what food did I eat",
            fused_scores={"a": 0.5, "b": 0.5},
        )

    assert len(result) == 2
    # Item a (user, sushi) should rank higher: even though CE gives 0.6 vs 0.8,
    # the heuristic role_bias (+0.35 for user, -0.1 for assistant) should tip it
    assert result[0]["event_id"] == "a"
    assert result[0]["reranker_backend"] == "cross_encoder"
    assert "ce_score" in result[0]["retrieval_trace"]


@pytest.mark.asyncio
async def test_cross_encoder_reranker_falls_back_on_missing_model():
    """When model dir is not found, should fall back to heuristic only."""
    config = RetrievalConfig(
        cross_encoder_enabled=True,
        cross_encoder_model_id="nonexistent",
        reranker_layers=("L1",),
        reranker_top_k=10,
    )
    reranker = CrossEncoderReranker(config)

    items = [
        {"event_id": "a", "content": "hello", "author_type": "user", "timestamp": 1.0},
    ]

    with patch(
        "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_model_dir",
        return_value=None,
    ):
        result = await reranker.rerank(
            layer="L1",
            results=items,
            query="test",
            fused_scores={"a": 0.5},
        )

    assert len(result) == 1
    assert result[0]["reranker_backend"] == "heuristic"


@pytest.mark.asyncio
async def test_cross_encoder_reranker_falls_back_on_scorer_error():
    """When scorer throws, should fall back to heuristic results."""
    config = RetrievalConfig(
        cross_encoder_enabled=True,
        cross_encoder_model_id="test-model",
        reranker_layers=("L1",),
        reranker_top_k=10,
    )
    reranker = CrossEncoderReranker(config)

    items = [
        {"event_id": "a", "content": "hello", "author_type": "user", "timestamp": 1.0},
    ]

    mock_scorer = AsyncMock()
    mock_scorer.score_pairs.side_effect = RuntimeError("ONNX crash")
    mock_model_dir = Path("/fake/model/dir")

    with (
        patch(
            "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_model_dir",
            return_value=mock_model_dir,
        ),
        patch(
            "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
            return_value=mock_scorer,
        ),
    ):
        result = await reranker.rerank(
            layer="L1",
            results=items,
            query="test",
            fused_scores={"a": 0.5},
        )

    assert len(result) == 1
    assert result[0]["reranker_backend"] == "heuristic"


@pytest.mark.asyncio
async def test_cross_encoder_reranker_skips_non_enabled_layer():
    """Layers not in reranker_layers use heuristic only."""
    config = RetrievalConfig(
        cross_encoder_enabled=True,
        cross_encoder_model_id="test-model",
        reranker_layers=("L1",),  # L3 not enabled
        reranker_top_k=10,
    )
    reranker = CrossEncoderReranker(config)

    items = [
        {"summary_id": "a", "content": "summary A"},
    ]

    # Should use heuristic path → noop for non-enabled layer
    result = await reranker.rerank(
        layer="L3",
        results=items,
        query="test",
        fused_scores={"a": 0.5},
    )
    assert len(result) == 1
    assert result[0]["reranker_backend"] == "noop"
