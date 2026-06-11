"""Tests for the local embedding router's variant-aware download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from magi.api.routers import local_embedding as router_mod
from magi.config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    LocalEmbeddingVariantMeta,
)


def _meta_with_variants() -> LocalEmbeddingModelMeta:
    return LocalEmbeddingModelMeta(
        id="qwen3-test",
        label="Qwen3 Test",
        repo="org/repo",
        onnx_repo="onnx-community/repo",
        dimension=1024,
        max_tokens=8192,
        variants={
            "fp32":      LocalEmbeddingVariantMeta(file="onnx/model.onnx",            size_mb=2400),
            "fp16":      LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx",       size_mb=1200),
            "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx",  size_mb=585),
        },
        default_variant={"darwin_arm64": "fp16", "_fallback": "quantized"},
    )


@pytest.mark.asyncio
async def test_download_only_fetches_chosen_variant_files(tmp_path: Path) -> None:
    """Resolves to fp16 on darwin_arm64; allow_patterns must include only fp16 + sidecar + tokenizer files."""
    meta = _meta_with_variants()
    captured_patterns: list[str] = []

    def fake_snapshot_download(repo_id, *, local_dir, allow_patterns, **kwargs):
        captured_patterns.extend(allow_patterns)
        target = Path(local_dir) / "onnx"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_fp16.onnx").touch()
        (Path(local_dir) / "tokenizer.json").touch()
        return str(local_dir)

    with patch.dict("sys.modules", {"huggingface_hub": MagicMock(snapshot_download=fake_snapshot_download)}), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"), \
         patch("magi.memory.onnx_variants.detect_platform_key", return_value="darwin_arm64"):
        await router_mod._download_model_task(meta, tmp_path, variant_override=None)

    # Critical: only fp16 file in patterns, plus its sidecar
    assert "onnx/model_fp16.onnx" in captured_patterns
    assert "onnx/model_fp16.onnx_data" in captured_patterns
    # The `.onnx.data` (dot) form is not a real upstream convention; we only
    # ship `.onnx_data` (underscore).
    assert "onnx/model_fp16.onnx.data" not in captured_patterns
    # Other variants MUST NOT be downloaded
    assert "onnx/model.onnx" not in captured_patterns
    assert "onnx/model_quantized.onnx" not in captured_patterns
    # Sidecars (tokenizer/config) still present
    assert "tokenizer.json" in captured_patterns
    assert "config.json" in captured_patterns
    # Legacy broad patterns must NOT be present
    assert "*.onnx" not in captured_patterns
    assert "onnx/*.onnx" not in captured_patterns


@pytest.mark.asyncio
async def test_download_respects_variant_override(tmp_path: Path) -> None:
    """variant_override='fp32' on darwin_arm64 overrides the default and downloads fp32."""
    meta = _meta_with_variants()
    captured_patterns: list[str] = []

    def fake_snapshot_download(repo_id, *, local_dir, allow_patterns, **kwargs):
        captured_patterns.extend(allow_patterns)
        target = Path(local_dir) / "onnx"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.onnx").touch()
        (target / "model.onnx_data").touch()
        (Path(local_dir) / "tokenizer.json").touch()
        return str(local_dir)

    with patch.dict("sys.modules", {"huggingface_hub": MagicMock(snapshot_download=fake_snapshot_download)}), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"), \
         patch("magi.memory.onnx_variants.detect_platform_key", return_value="darwin_arm64"):
        await router_mod._download_model_task(meta, tmp_path, variant_override="fp32")

    assert "onnx/model.onnx" in captured_patterns
    assert "onnx/model.onnx_data" in captured_patterns  # sidecar always probed
    # fp16/quantized must NOT appear
    assert "onnx/model_fp16.onnx" not in captured_patterns
    assert "onnx/model_quantized.onnx" not in captured_patterns


@pytest.mark.asyncio
async def test_download_falls_back_to_legacy_patterns_when_no_variants(tmp_path: Path) -> None:
    """Meta without a variants block (legacy YAML) keeps the old broad allow_patterns."""
    meta = LocalEmbeddingModelMeta(
        id="legacy",
        label="Legacy",
        repo="o/l",
        onnx_repo="o/l",
        dimension=384,
        max_tokens=512,
    )
    captured_patterns: list[str] = []

    def fake_snapshot_download(repo_id, *, local_dir, allow_patterns, **kwargs):
        captured_patterns.extend(allow_patterns)
        (Path(local_dir) / "model.onnx").touch()
        (Path(local_dir) / "tokenizer.json").touch()
        return str(local_dir)

    with patch.dict("sys.modules", {"huggingface_hub": MagicMock(snapshot_download=fake_snapshot_download)}), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True):
        await router_mod._download_model_task(meta, tmp_path, variant_override=None)

    assert "*.onnx" in captured_patterns
    assert "onnx/*.onnx" in captured_patterns


@pytest.mark.asyncio
async def test_download_model_endpoint_accepts_variant_query_param(tmp_path: Path) -> None:
    """The POST endpoint must accept ?variant=fp32 and thread it to _download_model_task."""
    from magi.config.local_embedding_registry import LocalEmbeddingModelRegistry

    meta = _meta_with_variants()
    registry = LocalEmbeddingModelRegistry(models=[meta])

    captured = {"variant": "<unset>"}

    async def fake_task(meta_arg, model_dir, *, variant_override=None):
        captured["variant"] = variant_override

    runtime_paths = MagicMock()
    runtime_paths.managed_embedding_model_dir.return_value = str(tmp_path / "model_dir")

    with patch.object(router_mod, "get_local_embedding_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=runtime_paths), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "_download_model_task", side_effect=fake_task):
        await router_mod.download_model("qwen3-test", variant="quantized")
        # let the task event loop tick
        import asyncio
        await asyncio.sleep(0)

    assert captured["variant"] == "quantized"


@pytest.mark.asyncio
async def test_list_models_includes_variants_with_downloaded_status(tmp_path: Path) -> None:
    """Each model in the list response must include its variants and which are downloaded."""
    from magi.config.local_embedding_registry import LocalEmbeddingModelRegistry

    meta = _meta_with_variants()
    registry = LocalEmbeddingModelRegistry(models=[meta])

    paths = MagicMock()
    model_dir = tmp_path / meta.id
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "onnx" / "model_fp16.onnx").touch()  # only fp16 downloaded
    (model_dir / "tokenizer.json").touch()
    paths.managed_embedding_model_dir = MagicMock(return_value=str(model_dir))

    with patch.object(router_mod, "get_local_embedding_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=paths), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"), \
         patch("magi.memory.onnx_variants.detect_platform_key", return_value="darwin_arm64"):
        result = await router_mod.list_models()

    assert len(result) == 1
    info = result[0]
    variant_names = {v.name for v in info.variants}
    assert variant_names == {"fp32", "fp16", "quantized"}
    by_name = {v.name: v for v in info.variants}
    assert by_name["fp16"].downloaded is True
    assert by_name["fp32"].downloaded is False
    assert by_name["quantized"].downloaded is False
    assert info.default_variant == "fp16"  # darwin_arm64 default
    assert by_name["fp32"].size_mb == 2400
    assert by_name["fp32"].file == "onnx/model.onnx"


@pytest.mark.asyncio
async def test_list_models_legacy_model_has_empty_variants_list(tmp_path: Path) -> None:
    """A model without a variants block returns an empty variants list and None default_variant."""
    from magi.config.local_embedding_registry import LocalEmbeddingModelMeta, LocalEmbeddingModelRegistry

    bare_meta = LocalEmbeddingModelMeta(
        id="legacy",
        label="Legacy",
        repo="o/l",
        onnx_repo="o/l",
        dimension=384,
        max_tokens=512,
    )
    registry = LocalEmbeddingModelRegistry(models=[bare_meta])

    paths = MagicMock()
    paths.managed_embedding_model_dir = MagicMock(return_value=str(tmp_path / "legacy"))

    with patch.object(router_mod, "get_local_embedding_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=paths):
        result = await router_mod.list_models()

    assert len(result) == 1
    info = result[0]
    assert info.variants == []
    assert info.default_variant is None
