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
            MagicMock(name="input_ids"),
            MagicMock(name="attention_mask"),
        ]
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
