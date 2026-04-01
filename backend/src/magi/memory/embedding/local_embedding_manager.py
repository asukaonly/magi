"""Local ONNX Runtime embedding manager with lazy loading and idle unloading."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
)
from ...config.models import LocalEmbeddingModelSource, LocalEmbeddingSettings
from ...utils.runtime import RuntimePaths

logger = logging.getLogger(__name__)


class LocalEmbeddingManager:
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
        self._runtime_paths = runtime_paths or RuntimePaths()
        self._session: Any = None  # onnxruntime.InferenceSession
        self._tokenizer: Any = None  # tokenizers.Tokenizer
        self._model_config: dict[str, Any] = {}
        self._pooling: str = "cls"
        self._normalize: bool = True
        self._dimension: int | None = None
        self._model_name: str = ""
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()
        self._unload_task: asyncio.Task[None] | None = None

    # ── Public API ──────────────────────────────────────────────────────

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
        """Clean shutdown — cancel idle timer and unload model."""
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
            try:
                await self._unload_task
            except asyncio.CancelledError:
                pass
        await self._unload()

    # ── Model lifecycle ─────────────────────────────────────────────────

    async def _ensure_loaded(self) -> None:
        """Load the ONNX model if not already loaded."""
        if self._session is not None:
            return

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Local embedding requires optional dependencies: "
                "pip install onnxruntime tokenizers"
            ) from exc

        model_dir = self._resolve_model_dir()
        if model_dir is None or not model_dir.exists():
            raise FileNotFoundError(
                f"Embedding model directory not found. "
                f"Please download the model first."
            )

        # Resolve model file — prefer quantized
        quantized_path = model_dir / "model_quantized.onnx"
        fp32_path = model_dir / "model.onnx"
        model_path = quantized_path if quantized_path.exists() else fp32_path
        if not model_path.exists():
            # Try finding any .onnx file
            onnx_files = sorted(model_dir.glob("*.onnx"))
            if not onnx_files:
                raise FileNotFoundError(f"No ONNX model found in {model_dir}")
            model_path = onnx_files[0]

        tokenizer_path = model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"tokenizer.json not found in {model_dir}")

        # Load model config for dimension and pooling hints
        config_path = model_dir / "config.json"
        if config_path.exists():
            self._model_config = json.loads(config_path.read_text(encoding="utf-8"))

        # Resolve pooling and normalization from preset registry or config.json
        meta = self._get_preset_meta()
        if meta:
            self._pooling = meta.pooling
            self._normalize = meta.normalize
            self._dimension = meta.dimension
            self._model_name = meta.id
        else:
            self._pooling = "mean"
            self._normalize = True
            self._dimension = self._model_config.get("hidden_size")
            self._model_name = model_dir.name

        # Configure ONNX session
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        logger.info(
            "Loading local embedding model: %s (%s)",
            self._model_name,
            model_path.name,
        )
        self._session = await asyncio.to_thread(
            ort.InferenceSession,
            str(model_path),
            opts,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = await asyncio.to_thread(
            Tokenizer.from_file, str(tokenizer_path)
        )
        self._last_used = time.monotonic()
        self._schedule_idle_check()
        logger.info(
            "Local embedding model loaded: %s (dim=%s, pooling=%s)",
            self._model_name,
            self._dimension,
            self._pooling,
        )

    async def _unload(self) -> None:
        """Unload model and free memory."""
        async with self._lock:
            if self._session is not None:
                model_name = self._model_name
                del self._session
                del self._tokenizer
                self._session = None
                self._tokenizer = None
                gc.collect()
                logger.info("Local embedding model unloaded: %s", model_name)

    def _schedule_idle_check(self) -> None:
        """Start the idle unload background loop."""
        if self._unload_task is not None and not self._unload_task.done():
            return
        self._unload_task = asyncio.create_task(self._idle_unload_loop())

    async def _idle_unload_loop(self) -> None:
        """Periodically check if the model should be unloaded due to inactivity."""
        check_interval = 60.0
        try:
            while self._session is not None:
                await asyncio.sleep(check_interval)
                idle = time.monotonic() - self._last_used
                if idle >= self._config.idle_timeout_seconds:
                    logger.info(
                        "Local embedding idle for %.0fs (threshold %ds), unloading",
                        idle,
                        self._config.idle_timeout_seconds,
                    )
                    await self._unload()
                    break
        except asyncio.CancelledError:
            pass

    # ── Internal helpers ────────────────────────────────────────────────

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous batch encode — expected to run in a thread pool."""
        import numpy as np

        session = self._session
        tokenizer = self._tokenizer
        if session is None or tokenizer is None:
            return []

        # Tokenize with padding
        tokenizer.enable_padding()
        tokenizer.enable_truncation(
            max_length=self._model_config.get("max_position_embeddings", 512)
        )
        encodings = tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encodings], dtype=np.int64
        )

        # Build feeds based on model input names
        input_names = {inp.name for inp in session.get_inputs()}
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)

        # Run inference
        outputs = session.run(None, feeds)
        hidden_states = outputs[0]  # (batch, seq_len, hidden_dim)

        # Pooling
        if self._pooling == "cls":
            embeddings = hidden_states[:, 0, :]
        else:
            # Mean pooling
            mask = attention_mask[:, :, np.newaxis].astype(np.float32)
            sum_hidden = (hidden_states * mask).sum(axis=1)
            sum_mask = mask.sum(axis=1)
            sum_mask = np.maximum(sum_mask, 1e-9)
            embeddings = sum_hidden / sum_mask

        # L2 normalize
        if self._normalize:
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-12)
            embeddings = embeddings / norms

        return embeddings.tolist()

    def _resolve_model_dir(self) -> Optional[Path]:
        """Resolve the model directory based on config."""
        if self._config.model_source == LocalEmbeddingModelSource.EXTERNAL:
            path_str = (self._config.model_dir_path or "").strip()
            if not path_str:
                return None
            return Path(path_str).expanduser()

        # MANAGED source
        model_id = (self._config.managed_model_id or "").strip()
        if not model_id:
            return None
        return Path(self._runtime_paths.managed_embedding_model_dir(model_id))

    def _get_preset_meta(self) -> Optional[LocalEmbeddingModelMeta]:
        """Look up preset metadata for the current model."""
        if self._config.model_source != LocalEmbeddingModelSource.MANAGED:
            return None
        model_id = (self._config.managed_model_id or "").strip()
        if not model_id:
            return None
        return get_local_embedding_registry().get(model_id)
