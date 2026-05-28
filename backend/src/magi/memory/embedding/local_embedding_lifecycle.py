"""Local embedding ONNX model lifecycle helpers."""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import time

logger = logging.getLogger(__name__)


class LocalEmbeddingLifecycleMixin:
    """Load, unload, and idle-expire a local embedding model."""

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
                "Embedding model directory not found. Please download the model first."
            )

        from .local_embedding_resolution import resolve_variant_path

        meta = self._get_preset_meta()
        variant_override = getattr(self._config, "variant", None)
        model_path = resolve_variant_path(model_dir, meta, override=variant_override)
        if model_path is None:
            raise FileNotFoundError(
                f"No ONNX model found in {model_dir}. "
                f"If you changed the variant override, download it first."
            )

        tokenizer_path = model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"tokenizer.json not found in {model_dir}")

        config_path = model_dir / "config.json"
        if config_path.exists():
            self._model_config = json.loads(config_path.read_text(encoding="utf-8"))

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

        from .local_embedding_identity import compute_local_embedding_model_fingerprint

        fingerprint = compute_local_embedding_model_fingerprint(
            self._config,
            runtime_paths=self._runtime_paths,
        )
        self._model_identity = fingerprint.identity_key if fingerprint is not None else None

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
        self._tokenizer = await asyncio.to_thread(Tokenizer.from_file, str(tokenizer_path))
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


__all__ = ["LocalEmbeddingLifecycleMixin"]
