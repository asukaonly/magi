"""Local ONNX Runtime embedding manager with lazy loading and idle unloading."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from ...config.models import LocalEmbeddingSettings
from ...utils.runtime import RuntimePaths, get_runtime_paths
from .local_embedding_encoding import LocalEmbeddingEncodingMixin
from .local_embedding_lifecycle import LocalEmbeddingLifecycleMixin
from .local_embedding_resolution import LocalEmbeddingModelResolutionMixin
from ..onnx_variants import _find_onnx_model


class LocalEmbeddingManager(
    LocalEmbeddingLifecycleMixin,
    LocalEmbeddingEncodingMixin,
    LocalEmbeddingModelResolutionMixin,
):
    """Manages local ONNX embedding model lifecycle with lazy loading and idle unloading.

    The model is loaded on the first embed call and automatically unloaded
    after ``idle_timeout_seconds`` of inactivity to free memory.
    """

    def __init__(
        self,
        config: LocalEmbeddingSettings,
        runtime_paths: RuntimePaths | None = None,
    ) -> None:
        self._config = config
        self._runtime_paths = runtime_paths or get_runtime_paths()
        self._session: Any = None
        self._tokenizer: Any = None
        self._model_config: dict[str, Any] = {}
        self._pooling: str = "cls"
        self._normalize: bool = True
        self._dimension: int | None = None
        self._model_name: str = ""
        self._model_identity: str | None = None
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()
        self._unload_task: asyncio.Task[None] | None = None

    @property
    def is_loaded(self) -> bool:
        """Whether the model is currently loaded in memory."""
        return self._session is not None

    @property
    def model_name(self) -> str:
        """Return the active model name."""
        return self._model_name

    @property
    def dimension(self) -> int | None:
        """Return the embedding dimension, if known."""
        return self._dimension

    @property
    def model_identity(self) -> str | None:
        """Return the content-derived identity key for the loaded model."""
        return self._model_identity

    async def embed(self, text: str) -> Optional[list[float]]:
        """Generate an embedding vector for a single text."""
        if not text or not text.strip():
            return None
        async with self._lock:
            await self._ensure_loaded()
        self._last_used = time.monotonic()
        vectors = await asyncio.to_thread(self._encode_sync, [text.strip()])
        return vectors[0] if vectors else None

    async def embed_batch(self, texts: list[str]) -> list[Optional[list[float]]]:
        """Generate embedding vectors for a batch of texts."""
        if not texts:
            return []

        stripped = [t.strip() for t in texts]
        non_empty_indices = [i for i, t in enumerate(stripped) if t]
        if not non_empty_indices:
            return [None] * len(texts)

        async with self._lock:
            await self._ensure_loaded()
        self._last_used = time.monotonic()

        non_empty_texts = [stripped[i] for i in non_empty_indices]
        raw_vectors = await asyncio.to_thread(self._encode_sync, non_empty_texts)

        results: list[Optional[list[float]]] = [None] * len(texts)
        for idx, vec in zip(non_empty_indices, raw_vectors):
            results[idx] = vec
        return results

    async def shutdown(self) -> None:
        """Clean shutdown: cancel idle timer and unload model."""
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
            try:
                await self._unload_task
            except asyncio.CancelledError:
                pass
        await self._unload()


__all__ = ["LocalEmbeddingManager", "_find_onnx_model"]
