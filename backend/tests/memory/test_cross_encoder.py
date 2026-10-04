"""Tests for cross-encoder reranker (mocked ONNX)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from magi.memory.hybrid_retrieval.cross_encoder import (
    CrossEncoderReranker,
    _find_onnx_model,
)
from magi.memory.hybrid_retrieval.models import RetrievalConfig


# ---------------------------------------------------------------------------
# _find_onnx_model tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "files,expected",
    [
        (["model.onnx", "model_quantized.onnx"], "model_quantized.onnx"),
        (["onnx/model.onnx", "onnx/model_int8.onnx"], "onnx/model_int8.onnx"),
        (["model.onnx", "onnx/model_quantized.onnx"], "model.onnx"),
        (["onnx/model.onnx"], "onnx/model.onnx"),
        ([], None),
    ],
)
def test_model_discovery_respects_directory_and_precision_priority(tmp_path, files, expected):
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    assert _find_onnx_model(tmp_path) == (tmp_path / expected if expected else None)


# ---------------------------------------------------------------------------
# CrossEncoderReranker integration tests (mocked scorer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_author,expected_order,expected_scores",
    [("user", ["b", "a"], [1.15, 0.95]), ("assistant", ["a", "b"], [0.95, 0.7])],
)
async def test_cross_encoder_scores_and_author_metadata_both_affect_order(
    second_author, expected_order, expected_scores, tmp_path
):
    config = RetrievalConfig(cross_encoder_enabled=True, cross_encoder_model_id="test-model")
    items = [
        {"event_id": "a", "content": "orchard", "author_type": "user"},
        {"event_id": "b", "content": "orchard", "author_type": second_author},
    ]
    scorer = AsyncMock()
    scorer.score_pairs.return_value = [0.6, 0.8]
    with patch(
        "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_paths",
        return_value=(tmp_path, tmp_path / "model.onnx"),
    ), patch(
        "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
        new_callable=AsyncMock,
        return_value=scorer,
    ) as load:
        result = await CrossEncoderReranker(config).rerank(
            layer="L1", results=items, query="orchard", fused_scores={"a": 0.5, "b": 0.5}
        )
    load.assert_awaited_once_with(tmp_path, model_file_path=tmp_path / "model.onnx")
    scorer.score_pairs.assert_awaited_once_with(
        [
            ("orchard", "author_type: user\nsource: \ntimestamp: \norchard"),
            ("orchard", f"author_type: {second_author}\nsource: \ntimestamp: \norchard"),
        ]
    )
    assert [item["event_id"] for item in result] == expected_order
    assert [item["retrieval_score"] for item in result] == pytest.approx(expected_scores)
    assert {item["event_id"]: item["retrieval_trace"]["ce_score"] for item in result} == {
        "a": 0.6,
        "b": 0.8,
    }
    assert {item["reranker_backend"] for item in result} == {"cross_encoder"}


@pytest.mark.asyncio
async def test_scorer_failure_returns_independently_expected_heuristic_ranking(tmp_path):
    config = RetrievalConfig(cross_encoder_enabled=True, cross_encoder_model_id="test-model")
    items = [
        {"event_id": "assistant", "content": "orchard", "author_type": "assistant"},
        {"event_id": "user", "content": "orchard", "author_type": "user"},
    ]
    scorer = AsyncMock()
    scorer.score_pairs.side_effect = RuntimeError("ONNX crash")
    with patch(
        "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_paths",
        return_value=(tmp_path, tmp_path / "model.onnx"),
    ), patch(
        "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
        new_callable=AsyncMock,
        return_value=scorer,
    ):
        result = await CrossEncoderReranker(config).rerank(
            layer="L1", results=items, query="orchard", fused_scores={"assistant": 0.6, "user": 0.5}
        )
    scorer.score_pairs.assert_awaited_once_with(
        [
            ("orchard", f"author_type: {author}\nsource: \ntimestamp: \norchard")
            for author in ["user", "assistant"]
        ]
    )
    assert [item["event_id"] for item in result] == ["user", "assistant"]
    assert [item["retrieval_score"] for item in result] == pytest.approx([1.85, 1.5])
    assert [item["reranker_backend"] for item in result] == ["heuristic", "heuristic"]


@pytest.mark.asyncio
async def test_disabled_layer_preserves_order_without_loading_available_model(tmp_path):
    config = RetrievalConfig(
        cross_encoder_enabled=True, cross_encoder_model_id="test-model", reranker_layers=("L1",)
    )
    items = [
        {"summary_id": "a", "content": "summary A"},
        {"summary_id": "b", "content": "summary B"},
    ]
    scorer = AsyncMock()
    with patch(
        "magi.memory.hybrid_retrieval.cross_encoder._resolve_cross_encoder_paths",
        return_value=(tmp_path, tmp_path / "model.onnx"),
    ) as resolve, patch(
        "magi.memory.hybrid_retrieval.cross_encoder._get_or_create_scorer",
        new_callable=AsyncMock,
        return_value=scorer,
    ) as load:
        result = await CrossEncoderReranker(config).rerank(
            layer="L3", results=items, query="summary", fused_scores={"a": 0.2, "b": 0.9}
        )
    resolve.assert_not_called()
    load.assert_not_awaited()
    scorer.score_pairs.assert_not_awaited()
    assert [item["summary_id"] for item in result] == ["a", "b"]
    assert [item["retrieval_score"] for item in result] == [0.2, 0.9]
    assert [item["reranker_backend"] for item in result] == ["noop", "noop"]


# ---------------------------------------------------------------------------
# Variant override field — Pydantic round-trip + threading
# ---------------------------------------------------------------------------


class TestRetrievalConfigVariant:
    """Variant threads from CrossEncoderSettings into RetrievalConfig."""


    def test_threads_from_app_config(self) -> None:
        """build_retrieval_config_from_app_config copies the variant from CrossEncoderSettings."""
        from magi.config.models import AppConfig
        from magi.memory.hybrid_retrieval.service import (
            build_retrieval_config_from_app_config,
        )

        app_config = AppConfig()
        app_config.agent.memory.reranker.cross_encoder.enabled = True
        app_config.agent.memory.reranker.cross_encoder.managed_model_id = (
            "bge-reranker-v2-m3"
        )
        app_config.agent.memory.reranker.cross_encoder.variant = "fp16"
        rc = build_retrieval_config_from_app_config(app_config)
        assert rc.cross_encoder_enabled is True
        assert rc.cross_encoder_model_id == "bge-reranker-v2-m3"
        assert rc.cross_encoder_variant == "fp16"


class TestVariantAwareModelDirResolution:
    """The caller must resolve variant -> file path before instantiating the scorer."""

    @pytest.mark.parametrize(
        "model_id,override,has_quantized,expected",
        [
            ("m", None, True, "onnx/model_qint8_arm64.onnx"),
            ("m", "fp32", True, "onnx/model.onnx"),
            ("m", None, False, None),
            (None, None, True, None),
        ],
    )
    def test_configured_variant_resolves_only_its_available_file(
        self, tmp_path, monkeypatch, model_id, override, has_quantized, expected
    ):
        from unittest.mock import MagicMock
        from magi.config.cross_encoder_registry import (
            CrossEncoderModelMeta,
            CrossEncoderModelRegistry,
            CrossEncoderVariantMeta,
        )
        from magi.memory.hybrid_retrieval import cross_encoder as ce

        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx/model.onnx").touch()
        if has_quantized:
            (tmp_path / "onnx/model_qint8_arm64.onnx").touch()
        meta = CrossEncoderModelMeta(
            id="m",
            label="M",
            repo="o/m",
            onnx_repo="o/m",
            variants={
                "fp32": CrossEncoderVariantMeta(file="onnx/model.onnx", size_mb=91),
                "arm64_int8": CrossEncoderVariantMeta(file="onnx/model_qint8_arm64.onnx", size_mb=23),
            },
            default_variant={"darwin_arm64": "arm64_int8", "_fallback": "fp32"},
        )
        monkeypatch.setattr(
            ce, "get_cross_encoder_registry", lambda: CrossEncoderModelRegistry(models=[meta])
        )
        monkeypatch.setattr("magi.memory.onnx_variants.detect_platform_key", lambda: "darwin_arm64")
        runtime_paths = MagicMock()
        runtime_paths.managed_reranker_model_dir.return_value = str(tmp_path)
        monkeypatch.setattr(ce, "RuntimePaths", lambda: runtime_paths)
        config = RetrievalConfig(
            cross_encoder_enabled=True, cross_encoder_model_id=model_id, cross_encoder_variant=override
        )
        assert ce._resolve_cross_encoder_paths(config) == (
            (tmp_path, tmp_path / expected) if expected else None
        )
        if model_id:
            runtime_paths.managed_reranker_model_dir.assert_called_once_with(model_id)
        else:
            runtime_paths.managed_reranker_model_dir.assert_not_called()
