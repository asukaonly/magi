"""ONNX Runtime scorer for cross-encoder retrieval reranking."""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from pathlib import Path
from typing import Any, Optional

from ..onnx_variants import _find_onnx_model

logger = logging.getLogger(__name__)


class CrossEncoderScorer:
    """ONNX Runtime cross-encoder scorer with lazy loading and idle unloading."""

    def __init__(
        self,
        model_dir: Path,
        *,
        idle_timeout_seconds: int = 1800,
    ) -> None:
        self._model_dir = model_dir
        self._idle_timeout_seconds = idle_timeout_seconds
        self._session: Any = None
        self._tokenizer: Any = None
        self._max_length: int = 512
        self._last_used: float = 0.0
        self._lock = asyncio.Lock()
        self._unload_task: Optional[asyncio.Task[None]] = None

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    async def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score a batch of (query, document) pairs.

        Returns a list of relevance scores in [0, 1] (sigmoid of logit).
        """
        if not pairs:
            return []
        async with self._lock:
            await self._ensure_loaded()
            session = self._session
            tokenizer = self._tokenizer
            max_length = self._max_length
        if session is None or tokenizer is None:
            return [0.0] * len(pairs)
        self._last_used = time.monotonic()
        return await asyncio.to_thread(self._score_sync, pairs, session, tokenizer, max_length)

    async def shutdown(self) -> None:
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
            try:
                await self._unload_task
            except asyncio.CancelledError:
                pass
        await self._unload()

    async def _ensure_loaded(self) -> None:
        if self._session is not None:
            return

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError("Cross-encoder requires: pip install onnxruntime tokenizers") from exc

        model_path = _find_onnx_model(self._model_dir)
        if model_path is None:
            raise FileNotFoundError(f"No ONNX model found in {self._model_dir}")

        tokenizer_path = self._model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(f"tokenizer.json not found in {self._model_dir}")

        config_path = self._model_dir / "config.json"
        if config_path.exists():
            import json

            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                self._max_length = cfg.get("max_position_embeddings", cfg.get("max_length", 512))
            except Exception:
                pass

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 4
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        logger.info("Loading cross-encoder model: %s", model_path.name)
        self._session = await asyncio.to_thread(
            ort.InferenceSession,
            str(model_path),
            opts,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = await asyncio.to_thread(Tokenizer.from_file, str(tokenizer_path))
        self._last_used = time.monotonic()
        self._schedule_idle_check()
        logger.info("Cross-encoder model loaded: %s", self._model_dir.name)

    async def _unload(self) -> None:
        async with self._lock:
            if self._session is not None:
                del self._session
                del self._tokenizer
                self._session = None
                self._tokenizer = None
                gc.collect()
                logger.info("Cross-encoder model unloaded")

    def _schedule_idle_check(self) -> None:
        if self._unload_task is not None and not self._unload_task.done():
            return
        self._unload_task = asyncio.create_task(self._idle_unload_loop())

    async def _idle_unload_loop(self) -> None:
        check_interval = 60.0
        try:
            while self._session is not None:
                await asyncio.sleep(check_interval)
                idle = time.monotonic() - self._last_used
                if idle >= self._idle_timeout_seconds:
                    logger.info("Cross-encoder idle for %.0fs, unloading", idle)
                    await self._unload()
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("Cross-encoder idle unload loop failed", exc_info=True)

    def _score_sync(
        self,
        pairs: list[tuple[str, str]],
        session: Any,
        tokenizer: Any,
        max_length: int,
    ) -> list[float]:
        """Synchronous scoring, run in a thread pool."""
        import numpy as np

        if session is None or tokenizer is None:
            return [0.0] * len(pairs)

        tokenizer.enable_padding(direction="right")
        tokenizer.enable_truncation(max_length=max_length)
        encodings = tokenizer.encode_batch([(q, d) for q, d in pairs])

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        input_names = {inp.name for inp in session.get_inputs()}
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)

        output_names = [session.get_outputs()[0].name]
        outputs = session.run(output_names, feeds)
        logits = outputs[0]

        if logits.ndim == 2:
            if logits.shape[1] == 1:
                logits = logits[:, 0]
            else:
                logits = logits[:, -1]

        scores = 1.0 / (1.0 + np.exp(-logits.astype(np.float64)))
        return scores.tolist()


__all__ = ["CrossEncoderScorer", "_find_onnx_model"]
