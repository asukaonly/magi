"""Tests for the local reranker router's variant-aware download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from magi.api.routers import local_reranker as router_mod
from magi.config.cross_encoder_registry import (
    CrossEncoderModelMeta,
    CrossEncoderModelRegistry,
    CrossEncoderVariantMeta,
)


def _meta_with_variants() -> CrossEncoderModelMeta:
    return CrossEncoderModelMeta(
        id="ms-marco-test",
        label="MS MARCO Test",
        repo="cross-encoder/test",
        onnx_repo="cross-encoder/test",
        variants={
            "fp32":          CrossEncoderVariantMeta(file="onnx/model.onnx",             size_mb=91),
            "arm64_int8":    CrossEncoderVariantMeta(file="onnx/model_qint8_arm64.onnx", size_mb=23),
            "x86_avx2_int8": CrossEncoderVariantMeta(file="onnx/model_quint8_avx2.onnx", size_mb=23),
        },
        default_variant={"darwin_arm64": "arm64_int8", "_fallback": "x86_avx2_int8"},
    )


@pytest.mark.asyncio
async def test_download_only_fetches_chosen_variant(tmp_path: Path) -> None:
    """darwin_arm64 default resolves to arm64_int8; allow_patterns contains only it + sidecars."""
    meta = _meta_with_variants()
    captured_patterns: list[str] = []

    def fake_snapshot_download(repo_id, *, local_dir, allow_patterns, **kwargs):
        captured_patterns.extend(allow_patterns)
        target = Path(local_dir) / "onnx"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model_qint8_arm64.onnx").touch()
        (Path(local_dir) / "tokenizer.json").touch()
        return str(local_dir)

    with patch.dict("sys.modules", {"huggingface_hub": MagicMock(snapshot_download=fake_snapshot_download)}), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"):
        await router_mod._download_model_task(meta, tmp_path, variant_override=None)

    assert "onnx/model_qint8_arm64.onnx" in captured_patterns
    assert "onnx/model_qint8_arm64.onnx_data" in captured_patterns  # sidecar always probed
    assert "onnx/model.onnx" not in captured_patterns
    assert "onnx/model_quint8_avx2.onnx" not in captured_patterns
    # Legacy broad patterns must NOT be present
    assert "*.onnx" not in captured_patterns
    assert "onnx/*.onnx" not in captured_patterns
    # Tokenizer + config sidecars present
    assert "tokenizer.json" in captured_patterns
    assert "config.json" in captured_patterns


@pytest.mark.asyncio
async def test_download_respects_variant_override(tmp_path: Path) -> None:
    """variant_override='fp32' wins over the platform default."""
    meta = _meta_with_variants()
    captured_patterns: list[str] = []

    def fake_snapshot_download(repo_id, *, local_dir, allow_patterns, **kwargs):
        captured_patterns.extend(allow_patterns)
        target = Path(local_dir) / "onnx"
        target.mkdir(parents=True, exist_ok=True)
        (target / "model.onnx").touch()
        (Path(local_dir) / "tokenizer.json").touch()
        return str(local_dir)

    with patch.dict("sys.modules", {"huggingface_hub": MagicMock(snapshot_download=fake_snapshot_download)}), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True):
        await router_mod._download_model_task(meta, tmp_path, variant_override="fp32")

    assert "onnx/model.onnx" in captured_patterns
    assert "onnx/model.onnx_data" in captured_patterns
    # Other variants not in patterns
    assert "onnx/model_qint8_arm64.onnx" not in captured_patterns


@pytest.mark.asyncio
async def test_legacy_meta_uses_broad_patterns(tmp_path: Path) -> None:
    """Meta without a variants block (legacy YAML) keeps the broad allow_patterns."""
    meta = CrossEncoderModelMeta(
        id="legacy",
        label="Legacy",
        repo="o/l",
        onnx_repo="o/l",
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
async def test_download_endpoint_accepts_variant_query_param(tmp_path: Path) -> None:
    """POST /local-reranker/.../download accepts ?variant=... and threads it to the task."""
    meta = _meta_with_variants()
    registry = CrossEncoderModelRegistry(models=[meta])

    captured = {"variant": "<unset>"}

    async def fake_task(meta_arg, model_dir, *, variant_override=None):
        captured["variant"] = variant_override

    runtime_paths = MagicMock()
    runtime_paths.managed_reranker_model_dir.return_value = str(tmp_path / "model_dir")

    with patch.object(router_mod, "get_cross_encoder_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=runtime_paths), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "_download_model_task", side_effect=fake_task):
        await router_mod.download_model("ms-marco-test", variant="x86_avx2_int8")
        import asyncio
        await asyncio.sleep(0)

    assert captured["variant"] == "x86_avx2_int8"


@pytest.mark.asyncio
async def test_endpoint_short_circuits_when_chosen_variant_on_disk(tmp_path: Path) -> None:
    """If the resolved variant's specific file is already on disk, return status=completed."""
    meta = _meta_with_variants()
    registry = CrossEncoderModelRegistry(models=[meta])

    model_dir = tmp_path / meta.id
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "onnx" / "model_qint8_arm64.onnx").touch()
    (model_dir / "tokenizer.json").touch()

    runtime_paths = MagicMock()
    runtime_paths.managed_reranker_model_dir.return_value = str(model_dir)

    with patch.object(router_mod, "get_cross_encoder_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=runtime_paths), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"):
        response = await router_mod.download_model("ms-marco-test", variant=None)

    assert response.status == "completed"


@pytest.mark.asyncio
async def test_endpoint_triggers_download_when_chosen_variant_missing(tmp_path: Path) -> None:
    """C1 invariant: even if some .onnx exists, switching to a missing variant must trigger a real download."""
    meta = _meta_with_variants()
    registry = CrossEncoderModelRegistry(models=[meta])

    model_dir = tmp_path / meta.id
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "onnx" / "model.onnx").touch()  # only fp32 present
    (model_dir / "tokenizer.json").touch()

    runtime_paths = MagicMock()
    runtime_paths.managed_reranker_model_dir.return_value = str(model_dir)

    captured = {"called": False}

    async def fake_task(meta_arg, model_dir_arg, *, variant_override=None):
        captured["called"] = True

    with patch.object(router_mod, "get_cross_encoder_registry", return_value=registry), \
         patch.object(router_mod, "RuntimePaths", return_value=runtime_paths), \
         patch.object(router_mod, "_download_progress", {}, create=True), \
         patch.object(router_mod, "_download_tasks", {}, create=True), \
         patch.object(router_mod, "_download_model_task", side_effect=fake_task), \
         patch.object(router_mod, "detect_platform_key", return_value="darwin_arm64"):
        response = await router_mod.download_model("ms-marco-test", variant="arm64_int8")
        import asyncio
        await asyncio.sleep(0)

    assert captured["called"] is True
    assert response.status == "downloading"
