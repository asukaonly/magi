"""Tests for the LocalEmbeddingManager without requiring ONNX Runtime."""

from __future__ import annotations

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




class TestModelResolution:
    """Test _resolve_model_dir logic."""

    @pytest.mark.parametrize(
        "source,model_id,external_path,expected",
        [
            ("managed", "test-model", None, "managed"),
            ("managed", "", None, None),
            ("external", "ignored", "/tmp/my-model", "external"),
            ("external", "ignored", "", None),
        ],
    )
    def test_model_directory_resolution_uses_only_configured_source(
        self, tmp_path, source, model_id, external_path, expected
    ):
        runtime_paths = MagicMock()
        managed = tmp_path / "models" / "test-model"
        runtime_paths.managed_embedding_model_dir.return_value = managed
        mgr = LocalEmbeddingManager(
            _make_config(model_source=source, managed_model_id=model_id, model_dir_path=external_path),
            runtime_paths=runtime_paths,
        )
        assert mgr._resolve_model_dir() == (
            {"managed": managed, "external": Path("/tmp/my-model"), None: None}[expected]
        )
        if expected == "managed":
            runtime_paths.managed_embedding_model_dir.assert_called_once_with("test-model")
        else:
            runtime_paths.managed_embedding_model_dir.assert_not_called()


class TestEmbed:
    """Test embed/embed_batch dispatching without real ONNX."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method,value,expected",
        [
            ("embed", "", None),
            ("embed", "   ", None),
            ("embed_batch", [], []),
            ("embed_batch", ["", "  ", ""], [None, None, None]),
        ],
    )
    async def test_empty_embedding_input_skips_loading_and_inference(self, method, value, expected):
        mgr = LocalEmbeddingManager(_make_config())
        mgr._ensure_loaded = AsyncMock(side_effect=AssertionError("Empty input loaded a model"))
        mgr._encode_sync = MagicMock(side_effect=AssertionError("Empty input reached inference"))
        assert await getattr(mgr, method)(value) == expected
        mgr._ensure_loaded.assert_not_called()
        mgr._encode_sync.assert_not_called()


    @pytest.mark.asyncio
    async def test_embed_calls_ensure_loaded(self) -> None:
        """Non-empty text should trigger _ensure_loaded and _encode_sync."""
        mgr = LocalEmbeddingManager(_make_config())
        mgr._ensure_loaded = AsyncMock()
        mgr._encode_sync = MagicMock(return_value=[[0.1, 0.2, 0.3]])

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

    @pytest.mark.parametrize(
        "pooling,padding,expected",
        [
            ("cls", "right", [[3, 4, 0, 0], [5, 12, 0, 0]]),
            ("mean", "right", [[6, 8, 0, 0], [14.5, 11, 0, 0]]),
            ("last_token", "right", [[9, 12, 0, 0], [24, 10, 0, 0]]),
            ("last_token", "left", [[9, 12, 0, 0], [24, 10, 0, 0]]),
        ],
    )
    @pytest.mark.parametrize("normalize", [False, True])
    def test_pooling_excludes_padding_and_normalizes_without_changing_direction(
        self, pooling, padding, expected, normalize
    ):
        import numpy as np
        from types import SimpleNamespace

        mgr = self._make_mgr_with_session(pooling, normalize=normalize)
        short = [[5, 12, 0, 0], [24, 10, 0, 0]]
        canary = [99, 99, 99, 99]
        if padding == "left":
            mgr._tokenizer.encode_batch.return_value[1] = SimpleNamespace(
                ids=[0, 40, 50], attention_mask=[0, 1, 1]
            )
            short = [canary, *short]
        else:
            short = [*short, canary]
        mgr._session.run.return_value = [
            np.array([[[3, 4, 0, 0], [6, 8, 0, 0], [9, 12, 0, 0]], short], dtype=np.float32)
        ]
        result = mgr._encode_sync(["hello", "hi"])
        if normalize:
            expected = [[0.6, 0.8, 0, 0], {"cls": [5 / 13, 12 / 13, 0, 0], "mean": [29 / (1325 ** .5), 22 / (1325 ** .5), 0, 0], "last_token": [12 / 13, 5 / 13, 0, 0]}[pooling]]
        np.testing.assert_allclose(result, expected, atol=1e-6)
        mgr._tokenizer.enable_padding.assert_called_once_with(
            direction="left" if pooling == "last_token" else "right"
        )


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

        mgr._encode_sync(["hello", "hi"])

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




class TestDetectPlatformKey:
    """Verify platform key format matches what default_variant keys use."""

    @pytest.mark.parametrize(
        "platform_name,expected_key,machine_name",
        [
            pytest.param("darwin", "darwin_arm64", "arm64", id="darwin_arm64"),
            pytest.param("win32", "win32_amd64", "AMD64", id="win32_amd64_uppercase"),
            pytest.param("linux", "linux_x86_64", "x86_64", id="linux_x86_64"),
        ],
    )
    def test_platform_key_normalizes_supported_hosts(
        self, platform_name, expected_key, machine_name
    ) -> None:
        from unittest.mock import patch
        from magi.memory import onnx_variants as res

        with patch.object(res.sys, "platform", platform_name), patch.object(
            res.platform, "machine", return_value=machine_name
        ):
            assert res.detect_platform_key() == expected_key


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

    @pytest.mark.parametrize(
        "metadata,platform,expected",
        [
            ("variants", "darwin_arm64", "fp16"),
            ("variants", "win32_amd64", "quantized"),
            ("variants", None, "quantized"),
            ("variants", "bsd_riscv64", "quantized"),
            ("empty", "darwin_arm64", None),
            ("absent", None, None),
        ],
    )
    def test_variant_selection_uses_explicit_platform_before_detection(
        self, monkeypatch, metadata, platform, expected
    ):
        from magi.config.local_embedding_registry import LocalEmbeddingModelMeta
        from magi.memory import onnx_variants

        detect = MagicMock(return_value="win32_amd64")
        monkeypatch.setattr(onnx_variants, "detect_platform_key", detect)
        meta = (
            self._meta()
            if metadata == "variants"
            else (
                LocalEmbeddingModelMeta(
                    id="m", label="M", repo="o/m", onnx_repo="o/m", dimension=512, max_tokens=512
                )
                if metadata == "empty"
                else None
            )
        )
        assert (
            onnx_variants.resolve_variant_name(meta, override=None, platform_key=platform) == expected
        )
        if metadata == "variants" and platform is None:
            detect.assert_called_once_with()
        else:
            detect.assert_not_called()


    def test_emergency_chain_when_default_missing_from_variants(self) -> None:
        from magi.memory.onnx_variants import resolve_variant_name
        # default points to a variant the YAML doesn't actually define.
        # Emergency chain picks first of (quantized, int8, fp16, fp32) present.
        meta = self._meta(variant_names=["fp32", "int8"], default={"_fallback": "quantized"})
        assert resolve_variant_name(meta, override=None, platform_key="anything") == "int8"


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


class TestLifecycleVariantWiring:
    """Verify _ensure_loaded picks the configured variant."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "override,filename", [(None, "model_fp16.onnx"), ("quantized", "model_quantized.onnx")]
    )
    async def test_load_variant_then_shutdown_is_idempotent(
        self, tmp_path: Path, monkeypatch, override, filename
    ) -> None:
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
                "fp16": LocalEmbeddingVariantMeta(file="onnx/model_fp16.onnx", size_mb=50),
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
            variant=override,
        )
        mgr = LocalEmbeddingManager(cfg, runtime_paths=runtime_paths)

        assert (mgr.is_loaded, mgr.model_name, mgr.dimension) == (False, "", None)
        await mgr.shutdown()

        # Force platform_key to darwin_arm64 deterministically
        monkeypatch.setattr(res, "detect_platform_key", lambda: "darwin_arm64")

        # Patch ort and tokenizers imports inside _ensure_loaded
        ort_mod = MagicMock()
        ort_mod.SessionOptions = MagicMock(
            return_value=MagicMock(
                inter_op_num_threads=0,
                intra_op_num_threads=0,
                graph_optimization_level=0,
            )
        )
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
            await mgr._ensure_loaded()

        try:
            assert captured_sessions == [str(tmp_path / "onnx" / filename)]
            assert (mgr.is_loaded, mgr.model_name, mgr.dimension) == (True, "test-model", 768)
            timer = mgr._unload_task
            assert timer is not None
        finally:
            await mgr.shutdown()
        assert timer.done()
        assert mgr.is_loaded is False
        assert mgr._tokenizer is None
        await mgr.shutdown()
        assert mgr.is_loaded is False


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

    def test_external_fingerprint_hashes_exact_assets_without_registry_lookup(
        self, tmp_path, monkeypatch
    ):
        from magi.memory.embedding import local_embedding_identity

        (tmp_path / "model.onnx").write_bytes(b"external-model-bytes")
        (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
        (tmp_path / "config.json").write_text('{"hidden_size": 384}', encoding="utf-8")
        registry = MagicMock(side_effect=AssertionError("External assets consulted managed registry"))
        monkeypatch.setattr(local_embedding_identity, "get_local_embedding_registry", registry)
        config = _make_config(
            model_source="external",
            model_dir_path=str(tmp_path),
            managed_model_id="unrelated-managed-model",
        )
        fingerprint = local_embedding_identity.compute_local_embedding_model_fingerprint(config)
        assert fingerprint.model_dir == tmp_path
        assert fingerprint.model_name == tmp_path.name
        assert fingerprint.dimension == 384
        assert (
            fingerprint.model_file_hash
            == "3cee8a5c32af5630145e9f5e43be3ec81c0451befe4ef40104e0efb8a29cfc5c"
        )
        assert (
            fingerprint.identity_key
            == "local:onnxruntime:3cee8a5c32af5630145e9f5e43be3ec81c0451befe4ef40104e0efb8a29cfc5c"
        )
        registry.assert_not_called()
