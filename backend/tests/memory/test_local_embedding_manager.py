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
