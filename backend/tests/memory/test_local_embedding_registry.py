"""Tests for the local embedding model registry."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from magi.config.local_embedding_registry import (
    LocalEmbeddingModelRegistry,
    load_local_embedding_registry,
)


@pytest.fixture()
def registry_yaml(tmp_path: Path) -> Path:
    """Write a sample registry YAML and return its path."""
    content = dedent("""\
        models:
          - id: test-model-small
            label: "Test Small"
            repo: "org/test-model-small"
            onnx_repo: "org/test-model-small-onnx"
            dimension: 384
            max_tokens: 512
            pooling: cls
            normalize: true
            size_mb: 30
            quantized: true
            languages: ["en"]
            recommended: true
            description: "A test model"
          - id: test-model-large
            label: "Test Large"
            repo: "org/test-model-large"
            dimension: 1024
            max_tokens: 8192
            pooling: mean
    """)
    path = tmp_path / "local_embedding_models.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLocalEmbeddingRegistry:
    """Tests for registry loading and lookup."""

    def test_load_valid_yaml(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        assert len(registry.models) == 2

    def test_get_by_id(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        meta = registry.get("test-model-small")
        assert meta is not None
        assert meta.label == "Test Small"
        assert meta.dimension == 384
        assert meta.pooling == "cls"
        assert meta.recommended is True
        assert "en" in meta.languages

    def test_get_missing_returns_none(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        assert registry.get("nonexistent") is None

    def test_list_ids(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        ids = registry.list_ids()
        assert ids == ["test-model-small", "test-model-large"]

    def test_defaults_applied(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        large = registry.get("test-model-large")
        assert large is not None
        assert large.pooling == "mean"
        assert large.normalize is True  # default
        assert large.quantized is True  # default
        assert large.onnx_repo == "org/test-model-large"  # fallback to repo

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        registry = load_local_embedding_registry(tmp_path / "missing.yaml")
        assert len(registry.models) == 0

    def test_malformed_entry_skipped(self, tmp_path: Path) -> None:
        content = dedent("""\
            models:
              - id: good-model
                label: "Good"
                repo: "org/good"
                dimension: 384
                max_tokens: 512
              - not_a_dict
              - id: ""
        """)
        path = tmp_path / "registry.yaml"
        path.write_text(content, encoding="utf-8")
        registry = load_local_embedding_registry(path)
        assert len(registry.models) == 1
        assert registry.models[0].id == "good-model"

    def test_variants_loaded(self, tmp_path: Path) -> None:
        content = dedent("""\
            models:
              - id: m1
                label: "M1"
                repo: "org/m1"
                dimension: 512
                max_tokens: 512
                variants:
                  fp32:      { file: "onnx/model.onnx",           size_mb: 96 }
                  quantized: { file: "onnx/model_quantized.onnx", size_mb: 24 }
                  fp16:      { file: "onnx/model_fp16.onnx",      size_mb: 48 }
                default_variant:
                  darwin_arm64:  fp16
                  win32_amd64:   quantized
                  _fallback:     quantized
        """)
        path = tmp_path / "registry.yaml"
        path.write_text(content, encoding="utf-8")
        registry = load_local_embedding_registry(path)
        m = registry.get("m1")
        assert m is not None
        assert set(m.variants.keys()) == {"fp32", "quantized", "fp16"}
        assert m.variants["fp32"].file == "onnx/model.onnx"
        assert m.variants["fp32"].size_mb == 96
        assert m.default_variant["darwin_arm64"] == "fp16"
        assert m.default_variant["_fallback"] == "quantized"

    def test_missing_variants_block_yields_empty_dicts(self, registry_yaml: Path) -> None:
        registry = load_local_embedding_registry(registry_yaml)
        small = registry.get("test-model-small")
        assert small is not None
        assert small.variants == {}
        assert small.default_variant == {}

    def test_malformed_variant_entry_skipped(self, tmp_path: Path) -> None:
        content = dedent("""\
            models:
              - id: m1
                label: "M1"
                repo: "org/m1"
                dimension: 512
                max_tokens: 512
                variants:
                  ok:      { file: "onnx/model.onnx", size_mb: 10 }
                  bad:     "not-a-dict"
                  no_file: { size_mb: 5 }
                default_variant:
                  _fallback: ok
        """)
        path = tmp_path / "registry.yaml"
        path.write_text(content, encoding="utf-8")
        registry = load_local_embedding_registry(path)
        m = registry.get("m1")
        assert m is not None
        assert set(m.variants.keys()) == {"ok"}

    def test_empty_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.yaml"
        path.write_text("", encoding="utf-8")
        registry = load_local_embedding_registry(path)
        assert isinstance(registry, LocalEmbeddingModelRegistry)
        assert len(registry.models) == 0
