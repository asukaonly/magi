"""Tests for the LocalEmbeddingManager without requiring ONNX Runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from magi.config.models import LocalEmbeddingModelSource, LocalEmbeddingSettings
from magi.memory.embedding.local_embedding_manager import LocalEmbeddingManager


def _make_config(
    *,
    model_source: str = "managed",
    managed_model_id: str | None = "test-model",
    model_dir_path: str | None = None,
    idle_timeout_seconds: int = 1800,
) -> LocalEmbeddingSettings:
    return LocalEmbeddingSettings(
        model_source=LocalEmbeddingModelSource(model_source),
        managed_model_id=managed_model_id,
        model_dir_path=model_dir_path,
        idle_timeout_seconds=idle_timeout_seconds,
    )


class TestLocalEmbeddingManagerInit:
    """Test construction and basic properties."""

    def test_not_loaded_initially(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        assert mgr.is_loaded is False
        assert mgr.model_name == ""
        assert mgr.dimension is None


class TestModelResolution:
    """Test _resolve_model_dir logic."""

    def test_managed_source_resolves_to_cache_dir(self, tmp_path: Path) -> None:
        """Managed source should look up runtime_paths.managed_embedding_model_dir."""
        runtime_paths = MagicMock()
        runtime_paths.managed_embedding_model_dir.return_value = str(tmp_path / "models" / "test-model")

        mgr = LocalEmbeddingManager(_make_config(), runtime_paths=runtime_paths)
        result = mgr._resolve_model_dir()

        assert result is not None
        assert "test-model" in str(result)
        runtime_paths.managed_embedding_model_dir.assert_called_once_with("test-model")

    def test_external_source_uses_path(self) -> None:
        mgr = LocalEmbeddingManager(
            _make_config(model_source="external", model_dir_path="/tmp/my-model")
        )
        result = mgr._resolve_model_dir()
        assert result == Path("/tmp/my-model")

    def test_external_source_empty_path_returns_none(self) -> None:
        mgr = LocalEmbeddingManager(
            _make_config(model_source="external", model_dir_path="")
        )
        assert mgr._resolve_model_dir() is None

    def test_managed_source_empty_id_returns_none(self) -> None:
        mgr = LocalEmbeddingManager(_make_config(managed_model_id=""))
        assert mgr._resolve_model_dir() is None


class TestEmbed:
    """Test embed/embed_batch dispatching without real ONNX."""

    @pytest.mark.asyncio
    async def test_embed_empty_text_returns_none(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        result = await mgr.embed("")
        assert result is None

    @pytest.mark.asyncio
    async def test_embed_whitespace_returns_none(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        result = await mgr.embed("   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list_returns_empty(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        result = await mgr.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_batch_all_empty_returns_nones(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        result = await mgr.embed_batch(["", "  ", ""])
        assert result == [None, None, None]

    @pytest.mark.asyncio
    async def test_embed_calls_ensure_loaded(self) -> None:
        """Non-empty text should trigger _ensure_loaded and _encode_sync."""
        mgr = LocalEmbeddingManager(_make_config())
        mgr._ensure_loaded = AsyncMock()
        mgr._encode_sync = MagicMock(return_value=[[0.1, 0.2, 0.3]])

        with patch("asyncio.to_thread", new_callable=lambda: lambda fn, *a: asyncio.coroutine(lambda: fn(*a))()):
            pass

        # Patch to_thread to just call sync
        async def fake_to_thread(fn, *args):
            return fn(*args)

        with patch("magi.memory.embedding.local_embedding_manager.asyncio.to_thread", fake_to_thread):
            result = await mgr.embed("hello")

        mgr._ensure_loaded.assert_awaited_once()
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_batch_maps_results(self) -> None:
        """embed_batch should map non-empty texts to their vectors."""
        mgr = LocalEmbeddingManager(_make_config())
        mgr._ensure_loaded = AsyncMock()
        mgr._encode_sync = MagicMock(return_value=[[1.0, 0.0], [0.0, 1.0]])

        async def fake_to_thread(fn, *args):
            return fn(*args)

        with patch("magi.memory.embedding.local_embedding_manager.asyncio.to_thread", fake_to_thread):
            result = await mgr.embed_batch(["", "hello", "world", ""])

        assert len(result) == 4
        assert result[0] is None
        assert result[1] == [1.0, 0.0]
        assert result[2] == [0.0, 1.0]
        assert result[3] is None


class TestEncodeSyncPooling:
    """Test _encode_sync pooling strategies with mocked session/tokenizer."""

    def _make_mgr_with_session(self, pooling: str, normalize: bool = True):
        import numpy as np

        mgr = LocalEmbeddingManager(_make_config())
        mgr._pooling = pooling
        mgr._normalize = normalize

        # Fake tokenizer
        class FakeEncoding:
            def __init__(self, ids, mask):
                self.ids = ids
                self.attention_mask = mask

        class FakeInput:
            """Mimics onnxruntime NodeArg with a .name attribute."""
            def __init__(self, name: str):
                self.name = name

        tokenizer = MagicMock()
        # Two texts: "hello" (3 real tokens) and "hi" (2 real tokens), padded to len 3
        tokenizer.encode_batch.return_value = [
            FakeEncoding([10, 20, 30], [1, 1, 1]),
            FakeEncoding([40, 50, 0], [1, 1, 0]),
        ]
        mgr._tokenizer = tokenizer

        # Fake session producing hidden_states (batch=2, seq_len=3, dim=4)
        hidden = np.array([
            [[1.0, 0.0, 0.0, 0.0],
             [0.0, 2.0, 0.0, 0.0],
             [0.0, 0.0, 3.0, 0.0]],
            [[4.0, 0.0, 0.0, 0.0],
             [0.0, 5.0, 0.0, 0.0],
             [0.0, 0.0, 6.0, 0.0]],
        ], dtype=np.float32)
        session = MagicMock()
        session.run.return_value = [hidden]
        session.get_inputs.return_value = [
            FakeInput("input_ids"),
            FakeInput("attention_mask"),
        ]

        class FakeOutput:
            def __init__(self, name: str):
                self.name = name

        session.get_outputs.return_value = [FakeOutput("last_hidden_state")]
        mgr._session = session
        mgr._model_config = {"max_position_embeddings": 512}
        return mgr

    def test_cls_pooling(self):
        import numpy as np

        mgr = self._make_mgr_with_session("cls", normalize=False)
        result = mgr._encode_sync(["hello", "hi"])
        arr = np.array(result)
        # CLS = first token
        assert arr.shape == (2, 4)
        np.testing.assert_allclose(arr[0], [1.0, 0.0, 0.0, 0.0])
        np.testing.assert_allclose(arr[1], [4.0, 0.0, 0.0, 0.0])

    def test_mean_pooling(self):
        import numpy as np

        mgr = self._make_mgr_with_session("mean", normalize=False)
        result = mgr._encode_sync(["hello", "hi"])
        arr = np.array(result)
        # "hello": mask=[1,1,1], mean of 3 rows
        np.testing.assert_allclose(arr[0], [1 / 3, 2 / 3, 3 / 3, 0.0], atol=1e-6)
        # "hi": mask=[1,1,0], mean of first 2 rows only
        np.testing.assert_allclose(arr[1], [4 / 2, 5 / 2, 0.0, 0.0], atol=1e-6)

    def test_last_token_pooling(self):
        import numpy as np

        mgr = self._make_mgr_with_session("last_token", normalize=False)
        result = mgr._encode_sync(["hello", "hi"])
        arr = np.array(result)
        # "hello": mask=[1,1,1], last valid index = 2
        np.testing.assert_allclose(arr[0], [0.0, 0.0, 3.0, 0.0])
        # "hi": mask=[1,1,0], last valid index = 1
        np.testing.assert_allclose(arr[1], [0.0, 5.0, 0.0, 0.0])

    def test_last_token_sets_left_padding(self):
        mgr = self._make_mgr_with_session("last_token", normalize=False)
        mgr._encode_sync(["hello", "hi"])
        mgr._tokenizer.enable_padding.assert_called_with(direction="left")

    def test_cls_sets_right_padding(self):
        mgr = self._make_mgr_with_session("cls", normalize=False)
        mgr._encode_sync(["hello", "hi"])
        mgr._tokenizer.enable_padding.assert_called_with(direction="right")

    def test_normalize_produces_unit_vectors(self):
        import numpy as np

        mgr = self._make_mgr_with_session("cls", normalize=True)
        result = mgr._encode_sync(["hello", "hi"])
        arr = np.array(result)
        norms = np.linalg.norm(arr, axis=1)
        np.testing.assert_allclose(norms, [1.0, 1.0], atol=1e-6)

    def test_decoder_model_provides_position_ids_and_kv_cache(self):
        """Decoder-only models (e.g. Qwen3) need position_ids + empty KV-cache."""
        import numpy as np

        mgr = self._make_mgr_with_session("last_token", normalize=False)

        class FakeInput:
            def __init__(self, name: str):
                self.name = name

        class FakeOutput:
            def __init__(self, name: str):
                self.name = name

        # Simulate decoder-only model inputs
        mgr._session.get_inputs.return_value = [
            FakeInput("input_ids"),
            FakeInput("attention_mask"),
            FakeInput("position_ids"),
            FakeInput("past_key_values.0.key"),
            FakeInput("past_key_values.0.value"),
            FakeInput("past_key_values.1.key"),
            FakeInput("past_key_values.1.value"),
        ]
        mgr._session.get_outputs.return_value = [FakeOutput("last_hidden_state")]
        mgr._model_config = {
            "max_position_embeddings": 512,
            "num_key_value_heads": 4,
            "head_dim": 64,
        }

        result = mgr._encode_sync(["hello", "hi"])

        # Verify run was called with all required feeds
        call_args = mgr._session.run.call_args
        feeds = call_args[0][1]
        assert "position_ids" in feeds
        assert "past_key_values.0.key" in feeds
        assert "past_key_values.1.value" in feeds
        # position_ids should be [0, 1, 2] for seq_len=3
        np.testing.assert_array_equal(feeds["position_ids"][0], [0, 1, 2])
        # KV-cache should be empty (past_sequence_length=0)
        assert feeds["past_key_values.0.key"].shape == (2, 4, 0, 64)

    def test_only_first_output_requested(self):
        """session.run should request only hidden states, not KV-cache outputs."""
        mgr = self._make_mgr_with_session("cls", normalize=False)
        mgr._encode_sync(["hello", "hi"])
        call_args = mgr._session.run.call_args
        output_names = call_args[0][0]
        assert output_names == ["last_hidden_state"]


class TestShutdown:
    """Test clean shutdown."""

    @pytest.mark.asyncio
    async def test_shutdown_when_not_loaded(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())
        await mgr.shutdown()
        assert mgr.is_loaded is False

    @pytest.mark.asyncio
    async def test_shutdown_cancels_unload_task(self) -> None:
        mgr = LocalEmbeddingManager(_make_config())

        cancelled = False

        async def fake_loop():
            nonlocal cancelled
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled = True

        mgr._unload_task = asyncio.create_task(fake_loop())
        await asyncio.sleep(0)  # let the task start
        await mgr.shutdown()
        assert cancelled


class TestDetectPlatformKey:
    """Verify platform key format matches what default_variant keys use."""

    def test_darwin_arm64(self) -> None:
        from unittest.mock import patch
        from magi.memory import onnx_variants as res
        with patch.object(res.sys, "platform", "darwin"), \
             patch.object(res.platform, "machine", return_value="arm64"):
            assert res.detect_platform_key() == "darwin_arm64"

    def test_win32_amd64_uppercase(self) -> None:
        from unittest.mock import patch
        from magi.memory import onnx_variants as res
        with patch.object(res.sys, "platform", "win32"), \
             patch.object(res.platform, "machine", return_value="AMD64"):
            # platform.machine() returns "AMD64" on Windows — must be lowercased.
            assert res.detect_platform_key() == "win32_amd64"

    def test_linux_x86_64(self) -> None:
        from unittest.mock import patch
        from magi.memory import onnx_variants as res
        with patch.object(res.sys, "platform", "linux"), \
             patch.object(res.platform, "machine", return_value="x86_64"):
            assert res.detect_platform_key() == "linux_x86_64"


class TestResolveVariantName:
    """Verify variant selection: override > platform default > _fallback > emergency chain."""

    def _meta(
        self,
        variant_names: list[str] | None = None,
        default: dict[str, str] | None = None,
    ):
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
        )
        names = variant_names or ["fp32", "fp16", "quantized", "int8"]
        v = {
            name: LocalEmbeddingVariantMeta(file=f"onnx/model_{name}.onnx", size_mb=100)
            for name in names
        }
        return LocalEmbeddingModelMeta(
            id="m",
            label="M",
            repo="o/m",
            onnx_repo="o/m",
            dimension=512,
            max_tokens=512,
            variants=v,
            default_variant=default or {
                "darwin_arm64": "fp16",
                "win32_amd64": "quantized",
                "_fallback": "quantized",
            },
        )

    def test_override_wins(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        assert resolve_variant_name(meta, override="fp32", platform_key="darwin_arm64") == "fp32"

    def test_override_invalid_falls_back_to_platform_default(self, caplog) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        with caplog.at_level("WARNING"):
            result = resolve_variant_name(meta, override="nonexistent", platform_key="darwin_arm64")
        assert result == "fp16"
        assert any("nonexistent" in r.message for r in caplog.records)

    def test_platform_default_darwin(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        assert resolve_variant_name(meta, override=None, platform_key="darwin_arm64") == "fp16"

    def test_platform_default_windows(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        assert resolve_variant_name(meta, override=None, platform_key="win32_amd64") == "quantized"

    def test_fallback_when_platform_unknown(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        assert resolve_variant_name(meta, override=None, platform_key="bsd_riscv64") == "quantized"

    def test_emergency_chain_when_default_missing_from_variants(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        # default points to a variant the YAML doesn't actually define.
        # Emergency chain picks first of (quantized, int8, fp16, fp32) present.
        meta = self._meta(variant_names=["fp32", "int8"], default={"_fallback": "quantized"})
        assert resolve_variant_name(meta, override=None, platform_key="anything") == "int8"

    def test_no_variants_returns_none(self) -> None:
        from magi.config.local_embedding_registry import LocalEmbeddingModelMeta
        from magi.memory.onnx_variants import resolve_variant_name
        meta = LocalEmbeddingModelMeta(
            id="m", label="M", repo="o/m", onnx_repo="o/m",
            dimension=512, max_tokens=512,
        )
        assert resolve_variant_name(meta, override=None, platform_key="darwin_arm64") is None

    def test_none_meta_returns_none(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        assert resolve_variant_name(None) is None

    def test_default_platform_key_used_when_omitted(self) -> None:
        """If platform_key is not passed, function calls detect_platform_key()."""
        from unittest.mock import patch
        from magi.memory.onnx_variants import resolve_variant_name
        meta = self._meta()
        with patch("magi.memory.onnx_variants.detect_platform_key", return_value="win32_amd64"):
            assert resolve_variant_name(meta, override=None) == "quantized"


class TestResolveVariantPath:
    """resolve_variant_path: from (model_dir, meta) to concrete .onnx path."""

    def _make_meta(self):
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
        )
        return LocalEmbeddingModelMeta(
            id="m",
            label="M",
            repo="o/m",
            onnx_repo="o/m",
            dimension=512,
            max_tokens=512,
            variants={
                "fp32":      LocalEmbeddingVariantMeta(file="onnx/model.onnx",            size_mb=100),
                "fp16":      LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx",       size_mb=50),
                "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx",  size_mb=25),
            },
            default_variant={"darwin_arm64": "fp16", "_fallback": "quantized"},
        )

    def test_picks_resolved_variant_when_present(self, tmp_path: Path) -> None:
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx" / "model_fp16.onnx").touch()
        (tmp_path / "onnx" / "model_quantized.onnx").touch()

        result = resolve_variant_path(
            tmp_path, self._make_meta(), override=None, platform_key="darwin_arm64"
        )
        assert result == tmp_path / "onnx" / "model_fp16.onnx"

    def test_override_picks_specific_variant(self, tmp_path: Path) -> None:
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx" / "model.onnx").touch()
        (tmp_path / "onnx" / "model_quantized.onnx").touch()

        result = resolve_variant_path(
            tmp_path, self._make_meta(), override="fp32", platform_key="darwin_arm64"
        )
        assert result == tmp_path / "onnx" / "model.onnx"

    def test_chosen_variant_missing_on_disk_returns_none(self, tmp_path: Path) -> None:
        """If resolver picks fp16 but only fp32 is downloaded, return None — do NOT silently load fp32."""
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx" / "model.onnx").touch()  # only fp32 present

        result = resolve_variant_path(
            tmp_path, self._make_meta(), override=None, platform_key="darwin_arm64"
        )
        assert result is None

    def test_flat_layout_fallback(self, tmp_path: Path) -> None:
        """Variant file is 'onnx/model_fp16.onnx' but user flattened it to model_fp16.onnx at root."""
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "model_fp16.onnx").touch()

        result = resolve_variant_path(
            tmp_path, self._make_meta(), override=None, platform_key="darwin_arm64"
        )
        assert result == tmp_path / "model_fp16.onnx"

    def test_no_variants_block_falls_back_to_legacy_scan(self, tmp_path: Path) -> None:
        from magi.config.local_embedding_registry import LocalEmbeddingModelMeta
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "model_quantized.onnx").touch()
        bare_meta = LocalEmbeddingModelMeta(
            id="m", label="M", repo="o/m", onnx_repo="o/m",
            dimension=512, max_tokens=512,
        )
        result = resolve_variant_path(tmp_path, bare_meta)
        assert result == tmp_path / "model_quantized.onnx"

    def test_meta_is_none_falls_back_to_legacy_scan(self, tmp_path: Path) -> None:
        from magi.memory.onnx_variants import resolve_variant_path
        (tmp_path / "model.onnx").touch()
        result = resolve_variant_path(tmp_path, None)
        assert result == tmp_path / "model.onnx"


class TestLocalEmbeddingSettingsVariant:
    """Pydantic round-trip for the new variant override field."""

    def test_default_is_none(self) -> None:
        from magi.config.models import LocalEmbeddingSettings
        s = LocalEmbeddingSettings()
        assert s.variant is None

    def test_explicit_variant(self) -> None:
        from magi.config.models import LocalEmbeddingSettings
        s = LocalEmbeddingSettings(variant="fp16")
        assert s.variant == "fp16"

    def test_serializes_to_dict(self) -> None:
        from magi.config.models import LocalEmbeddingSettings
        s = LocalEmbeddingSettings(variant="quantized")
        assert s.model_dump()["variant"] == "quantized"

    def test_round_trip_through_dict(self) -> None:
        from magi.config.models import LocalEmbeddingSettings
        s = LocalEmbeddingSettings.model_validate({"variant": "int8", "managed_model_id": "x"})
        assert s.variant == "int8"
        assert s.managed_model_id == "x"


class TestLifecycleVariantWiring:
    """Verify _ensure_loaded picks the configured variant."""

    @pytest.mark.asyncio
    async def test_picks_fp16_when_settings_variant_is_fp16(self, tmp_path: Path, monkeypatch) -> None:
        from magi.config.models import LocalEmbeddingSettings, LocalEmbeddingModelSource
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
            LocalEmbeddingModelRegistry,
        )
        from magi.memory.embedding.local_embedding_manager import LocalEmbeddingManager
        from magi.memory import onnx_variants as res

        # Build a fake managed dir with fp16 + quantized files
        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx" / "model_fp16.onnx").touch()
        (tmp_path / "onnx" / "model_quantized.onnx").touch()
        (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "config.json").write_text('{"hidden_size": 768}', encoding="utf-8")

        # Stub registry to return a known meta
        meta = LocalEmbeddingModelMeta(
            id="test-model",
            label="Test",
            repo="o/t",
            onnx_repo="o/t",
            dimension=768,
            max_tokens=512,
            variants={
                "fp16":      LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx", size_mb=50),
                "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx", size_mb=25),
            },
            default_variant={"darwin_arm64": "fp16", "_fallback": "quantized"},
        )
        registry = LocalEmbeddingModelRegistry(models=[meta])
        monkeypatch.setattr(
            "magi.memory.embedding.local_embedding_resolution.get_local_embedding_registry",
            lambda: registry,
        )

        runtime_paths = MagicMock()
        runtime_paths.managed_embedding_model_dir.return_value = str(tmp_path)

        cfg = LocalEmbeddingSettings(
            model_source=LocalEmbeddingModelSource.MANAGED,
            managed_model_id="test-model",
            variant=None,  # let platform default pick
        )
        mgr = LocalEmbeddingManager(cfg, runtime_paths=runtime_paths)

        # Force platform_key to darwin_arm64 deterministically
        monkeypatch.setattr(res, "detect_platform_key", lambda: "darwin_arm64")

        # Patch ort and tokenizers imports inside _ensure_loaded
        ort_mod = MagicMock()
        ort_mod.SessionOptions = MagicMock(return_value=MagicMock(
            inter_op_num_threads=0, intra_op_num_threads=0,
            graph_optimization_level=0,
        ))
        ort_mod.GraphOptimizationLevel.ORT_ENABLE_ALL = 0
        captured_sessions: list[str] = []

        def fake_session(path, opts, providers):
            captured_sessions.append(path)
            return MagicMock()

        ort_mod.InferenceSession = fake_session
        tokenizers_mod = MagicMock()
        tokenizers_mod.Tokenizer.from_file = MagicMock(return_value=MagicMock())

        with patch.dict("sys.modules", {"onnxruntime": ort_mod, "tokenizers": tokenizers_mod}):
            await mgr._ensure_loaded()

        assert len(captured_sessions) == 1
        assert captured_sessions[0].endswith("model_fp16.onnx"), (
            f"expected fp16 to be loaded, got {captured_sessions[0]}"
        )

        # Cancel idle task so test doesn't leak
        if mgr._unload_task and not mgr._unload_task.done():
            mgr._unload_task.cancel()

    @pytest.mark.asyncio
    async def test_picks_overridden_variant(self, tmp_path: Path, monkeypatch) -> None:
        """When settings.variant='quantized', loads quantized even on darwin_arm64."""
        from magi.config.models import LocalEmbeddingSettings, LocalEmbeddingModelSource
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
            LocalEmbeddingModelRegistry,
        )
        from magi.memory.embedding.local_embedding_manager import LocalEmbeddingManager
        from magi.memory import onnx_variants as res

        (tmp_path / "onnx").mkdir()
        (tmp_path / "onnx" / "model_fp16.onnx").touch()
        (tmp_path / "onnx" / "model_quantized.onnx").touch()
        (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "config.json").write_text('{"hidden_size": 768}', encoding="utf-8")

        meta = LocalEmbeddingModelMeta(
            id="test-model",
            label="Test",
            repo="o/t",
            onnx_repo="o/t",
            dimension=768,
            max_tokens=512,
            variants={
                "fp16":      LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx", size_mb=50),
                "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx", size_mb=25),
            },
            default_variant={"darwin_arm64": "fp16", "_fallback": "quantized"},
        )
        registry = LocalEmbeddingModelRegistry(models=[meta])
        monkeypatch.setattr(
            "magi.memory.embedding.local_embedding_resolution.get_local_embedding_registry",
            lambda: registry,
        )
        monkeypatch.setattr(res, "detect_platform_key", lambda: "darwin_arm64")

        runtime_paths = MagicMock()
        runtime_paths.managed_embedding_model_dir.return_value = str(tmp_path)

        cfg = LocalEmbeddingSettings(
            model_source=LocalEmbeddingModelSource.MANAGED,
            managed_model_id="test-model",
            variant="quantized",
        )
        mgr = LocalEmbeddingManager(cfg, runtime_paths=runtime_paths)

        ort_mod = MagicMock()
        ort_mod.SessionOptions = MagicMock(return_value=MagicMock(
            inter_op_num_threads=0, intra_op_num_threads=0,
            graph_optimization_level=0,
        ))
        ort_mod.GraphOptimizationLevel.ORT_ENABLE_ALL = 0
        captured: list[str] = []
        ort_mod.InferenceSession = lambda path, opts, providers: (captured.append(path) or MagicMock())
        tokenizers_mod = MagicMock()
        tokenizers_mod.Tokenizer.from_file = MagicMock(return_value=MagicMock())

        with patch.dict("sys.modules", {"onnxruntime": ort_mod, "tokenizers": tokenizers_mod}):
            await mgr._ensure_loaded()

        assert captured[0].endswith("model_quantized.onnx"), (
            f"expected quantized override to win over darwin_arm64 default, got {captured[0]}"
        )

        if mgr._unload_task and not mgr._unload_task.done():
            mgr._unload_task.cancel()


class TestComputeFingerprintVariantAware:
    """compute_local_embedding_model_fingerprint must respect variant and model_source."""

    def _setup_model_dir(self, tmp_path, variants_present: list[str]) -> None:
        """Create a managed model dir with the named variant files + tokenizer/config."""
        (tmp_path / "onnx").mkdir(exist_ok=True)
        filename_map = {
            "fp32":      "model.onnx",
            "fp16":      "model_fp16.onnx",
            "quantized": "model_quantized.onnx",
            "int8":      "model_int8.onnx",
        }
        for v in variants_present:
            (tmp_path / "onnx" / filename_map[v]).write_bytes(b"fake-onnx-bytes-" + v.encode())
        (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "config.json").write_text('{"hidden_size": 768}', encoding="utf-8")

    def test_identity_changes_when_variant_changes(self, tmp_path, monkeypatch) -> None:
        from magi.config.models import LocalEmbeddingSettings, LocalEmbeddingModelSource
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
            LocalEmbeddingModelRegistry,
        )
        from magi.memory.embedding.local_embedding_identity import (
            compute_local_embedding_model_fingerprint,
        )
        from unittest.mock import MagicMock

        self._setup_model_dir(tmp_path, ["fp16", "quantized"])

        meta = LocalEmbeddingModelMeta(
            id="test-model", label="Test", repo="o/t", onnx_repo="o/t",
            dimension=768, max_tokens=512,
            variants={
                "fp16":      LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx", size_mb=50),
                "quantized": LocalEmbeddingVariantMeta(file="onnx/model_quantized.onnx", size_mb=25),
            },
            default_variant={"darwin_arm64": "fp16", "_fallback": "quantized"},
        )
        registry = LocalEmbeddingModelRegistry(models=[meta])
        monkeypatch.setattr(
            "magi.memory.embedding.local_embedding_identity.get_local_embedding_registry",
            lambda: registry,
        )

        runtime_paths = MagicMock()
        runtime_paths.managed_embedding_model_dir.return_value = str(tmp_path)

        cfg_fp16 = LocalEmbeddingSettings(
            model_source=LocalEmbeddingModelSource.MANAGED,
            managed_model_id="test-model",
            variant="fp16",
        )
        cfg_quantized = LocalEmbeddingSettings(
            model_source=LocalEmbeddingModelSource.MANAGED,
            managed_model_id="test-model",
            variant="quantized",
        )

        fp_a = compute_local_embedding_model_fingerprint(cfg_fp16, runtime_paths=runtime_paths)
        fp_b = compute_local_embedding_model_fingerprint(cfg_quantized, runtime_paths=runtime_paths)

        assert fp_a is not None and fp_b is not None
        assert fp_a.identity_key != fp_b.identity_key, (
            "switching variant must produce a different identity_key"
        )

    def test_identity_for_external_source_ignores_residual_managed_id(self, tmp_path, monkeypatch) -> None:
        """Bug C3 regression: external source must not consult the registry."""
        from magi.config.models import LocalEmbeddingSettings, LocalEmbeddingModelSource
        from magi.config.local_embedding_registry import (
            LocalEmbeddingModelMeta,
            LocalEmbeddingVariantMeta,
            LocalEmbeddingModelRegistry,
        )
        from magi.memory.embedding.local_embedding_identity import (
            compute_local_embedding_model_fingerprint,
        )

        # External dir has just a plain model.onnx (no onnx/ subdir).
        (tmp_path / "model.onnx").write_bytes(b"external-model-bytes")
        (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "config.json").write_text('{"hidden_size": 384}', encoding="utf-8")

        # Registry has a managed entry whose variant files DON'T exist in tmp_path.
        registry_meta = LocalEmbeddingModelMeta(
            id="some-other-managed",
            label="Other",
            repo="o/o",
            onnx_repo="o/o",
            dimension=1024,
            max_tokens=512,
            variants={
                "fp16": LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx", size_mb=100),
            },
            default_variant={"_fallback": "fp16"},
        )
        registry = LocalEmbeddingModelRegistry(models=[registry_meta])
        monkeypatch.setattr(
            "magi.memory.embedding.local_embedding_identity.get_local_embedding_registry",
            lambda: registry,
        )

        cfg = LocalEmbeddingSettings(
            model_source=LocalEmbeddingModelSource.EXTERNAL,
            model_dir_path=str(tmp_path),
            # Residual id from when source was managed — must be ignored.
            managed_model_id="some-other-managed",
            variant=None,
        )
        fp = compute_local_embedding_model_fingerprint(cfg)
        assert fp is not None, "external-source fingerprint must succeed via legacy scan"
        assert fp.model_dir == tmp_path
        assert fp.model_file_hash, "model_file_hash must be a non-empty digest"
