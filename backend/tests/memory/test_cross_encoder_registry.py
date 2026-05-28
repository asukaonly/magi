"""Tests for the cross-encoder model registry."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from magi.config.cross_encoder_registry import (
    CrossEncoderModelRegistry,
    CrossEncoderVariantMeta,
    load_cross_encoder_registry,
)


@pytest.fixture()
def registry_yaml(tmp_path: Path) -> Path:
    content = dedent("""\
        models:
          - id: ce-small
            label: "CE Small"
            repo: "org/ce-small"
            onnx_repo: "org/ce-small-onnx"
            max_tokens: 512
            size_mb: 30
            languages: [en]
            recommended: true
            description: "Test CE"
            variants:
              fp32:      { file: "onnx/model.onnx",            size_mb: 90 }
              fp16:      { file: "onnx/model_fp16.onnx",       size_mb: 45 }
              quantized: { file: "onnx/model_quantized.onnx",  size_mb: 23 }
            default_variant:
              darwin_arm64:  fp16
              win32_amd64:   quantized
              _fallback:     quantized
          - id: ce-legacy
            label: "CE Legacy (no variants)"
            repo: "org/ce-legacy"
            max_tokens: 512
    """)
    path = tmp_path / "cross_encoder_models.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestCrossEncoderRegistry:
    def test_load_with_variants(self, registry_yaml: Path) -> None:
        reg = load_cross_encoder_registry(registry_yaml)
        assert len(reg.models) == 2

    def test_variants_parsed(self, registry_yaml: Path) -> None:
        reg = load_cross_encoder_registry(registry_yaml)
        m = reg.get("ce-small")
        assert m is not None
        assert set(m.variants.keys()) == {"fp32", "fp16", "quantized"}
        assert m.variants["fp16"].file == "onnx/model_fp16.onnx"
        assert m.variants["fp16"].size_mb == 45
        assert m.default_variant["darwin_arm64"] == "fp16"
        assert m.default_variant["_fallback"] == "quantized"

    def test_legacy_entry_has_empty_variants(self, registry_yaml: Path) -> None:
        reg = load_cross_encoder_registry(registry_yaml)
        m = reg.get("ce-legacy")
        assert m is not None
        assert m.variants == {}
        assert m.default_variant == {}

    def test_malformed_variant_entry_skipped(self, tmp_path: Path) -> None:
        content = dedent("""\
            models:
              - id: m1
                label: "M1"
                repo: "o/m1"
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
        reg = load_cross_encoder_registry(path)
        m = reg.get("m1")
        assert m is not None
        assert set(m.variants.keys()) == {"ok"}
        assert isinstance(m.variants["ok"], CrossEncoderVariantMeta)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        reg = load_cross_encoder_registry(tmp_path / "nope.yaml")
        assert isinstance(reg, CrossEncoderModelRegistry)
        assert len(reg.models) == 0
