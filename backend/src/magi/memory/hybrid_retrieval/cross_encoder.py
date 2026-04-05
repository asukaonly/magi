"""Cross-encoder reranker backed by ONNX Runtime.

Pipeline: Heuristic (always) → Cross-encoder top-K re-scoring (optional).
The cross-encoder evaluates (query, document) semantic relevance while
heuristic metadata adjustments (role_bias, eventness, verbosity_penalty …)
are preserved and added on top.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import RetrievalConfig
from .reranker import (
    BaseRetrievalReranker,
    HeuristicRetrievalReranker,
    NoopRetrievalReranker,
    _candidate_text_for_item,
    _secondary_timestamp,
)

logger = logging.getLogger(__name__)

# Heuristic trace keys that represent metadata-only adjustments (not semantic).
# These are summed and added on top of the cross-encoder score.
_HEURISTIC_METADATA_KEYS = frozenset({
    "role_bias",
    "fact_density",
    "eventness_score",
    "temporal_anchor_score",
})
_HEURISTIC_PENALTY_KEYS = frozenset({
    "verbosity_penalty",
    "generic_guidance_penalty",
    "generic_penalty",
})


def _find_onnx_model(model_dir: Path) -> Optional[Path]:
    """Find the best ONNX model file in a model directory."""
    for base in [model_dir, model_dir / "onnx"]:
        if not base.is_dir():
            continue
        for name in ["model_quantized.onnx", "model_int8.onnx", "model.onnx"]:
            candidate = base / name
            if candidate.exists():
                return candidate
        fallback = sorted(base.glob("*.onnx"))
        if fallback:
            return fallback[0]
    return None


class CrossEncoderScorer:
    """ONNX Runtime cross-encoder scorer with lazy loading and idle unloading.

    Loads a cross-encoder model that takes (query, document) pairs and
    outputs a relevance score.  Uses the same ONNX + tokenizers stack as
    the local embedding manager.
    """

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

    async def score_pairs(
        self, pairs: list[tuple[str, str]]
    ) -> list[float]:
        """Score a batch of (query, document) pairs.

        Returns a list of relevance scores in [0, 1] (sigmoid of logit).
        """
        if not pairs:
            return []
        async with self._lock:
            await self._ensure_loaded()
        self._last_used = time.monotonic()
        return await asyncio.to_thread(self._score_sync, pairs)

    async def shutdown(self) -> None:
        if self._unload_task and not self._unload_task.done():
            self._unload_task.cancel()
            try:
                await self._unload_task
            except asyncio.CancelledError:
                pass
        await self._unload()

    # ── Model lifecycle ─────────────────────────────────────────────────

    async def _ensure_loaded(self) -> None:
        if self._session is not None:
            return

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Cross-encoder requires: pip install onnxruntime tokenizers"
            ) from exc

        model_path = _find_onnx_model(self._model_dir)
        if model_path is None:
            raise FileNotFoundError(
                f"No ONNX model found in {self._model_dir}"
            )

        tokenizer_path = self._model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise FileNotFoundError(
                f"tokenizer.json not found in {self._model_dir}"
            )

        # Read max_length from config.json if available
        config_path = self._model_dir / "config.json"
        if config_path.exists():
            import json

            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                self._max_length = cfg.get(
                    "max_position_embeddings",
                    cfg.get("max_length", 512),
                )
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
        self._tokenizer = await asyncio.to_thread(
            Tokenizer.from_file, str(tokenizer_path)
        )
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
                    logger.info(
                        "Cross-encoder idle for %.0fs, unloading",
                        idle,
                    )
                    await self._unload()
                    break
        except asyncio.CancelledError:
            pass

    # ── ONNX inference ──────────────────────────────────────────────────

    def _score_sync(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Synchronous scoring — runs in a thread pool."""
        import numpy as np

        session = self._session
        tokenizer = self._tokenizer
        if session is None or tokenizer is None:
            return [0.0] * len(pairs)

        tokenizer.enable_padding(direction="right")
        tokenizer.enable_truncation(max_length=self._max_length)

        # Encode each (query, document) as a pair
        encodings = tokenizer.encode_batch(
            [(q, d) for q, d in pairs],
        )

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encodings], dtype=np.int64
        )

        input_names = {inp.name for inp in session.get_inputs()}
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.array(
                [e.type_ids for e in encodings], dtype=np.int64
            )

        output_names = [session.get_outputs()[0].name]
        outputs = session.run(output_names, feeds)
        logits = outputs[0]  # shape: (batch, num_labels) or (batch,)

        # Cross-encoders typically output a single logit per pair
        if logits.ndim == 2:
            # Some models have 1 output (relevance logit)
            if logits.shape[1] == 1:
                logits = logits[:, 0]
            else:
                # For multi-label models, take the "relevant" class (last)
                logits = logits[:, -1]

        # Sigmoid to [0, 1]
        scores = 1.0 / (1.0 + np.exp(-logits.astype(np.float64)))
        return scores.tolist()


# ---------------------------------------------------------------------------
# Singleton scorer management
# ---------------------------------------------------------------------------

_scorer_cache: dict[str, CrossEncoderScorer] = {}
_scorer_lock = asyncio.Lock()


async def _get_or_create_scorer(model_dir: Path) -> CrossEncoderScorer:
    """Return a cached scorer for the given model directory."""
    key = str(model_dir)
    async with _scorer_lock:
        if key not in _scorer_cache:
            _scorer_cache[key] = CrossEncoderScorer(model_dir)
        return _scorer_cache[key]


def _resolve_cross_encoder_model_dir(config: RetrievalConfig) -> Optional[Path]:
    """Resolve the cross-encoder model directory from config."""
    model_id = (config.cross_encoder_model_id or "").strip()
    if not model_id:
        return None

    from ...utils.runtime import RuntimePaths

    paths = RuntimePaths()
    model_dir = Path(paths.managed_reranker_model_dir(model_id))
    if model_dir.exists() and model_dir.is_dir():
        return model_dir
    return None


# ---------------------------------------------------------------------------
# CrossEncoderReranker — wraps HeuristicRetrievalReranker
# ---------------------------------------------------------------------------


class CrossEncoderReranker(BaseRetrievalReranker):
    """Two-stage reranker: heuristic metadata + cross-encoder semantic scoring.

    Stage 1: Heuristic reranker runs (always), annotating items with
    metadata-based adjustments (role_bias, eventness, etc.).

    Stage 2: Cross-encoder re-scores top-K items by semantic relevance.
    The final score blends cross-encoder semantic relevance with the
    heuristic metadata adjustments that the cross-encoder cannot see.
    """

    def __init__(self, config: RetrievalConfig) -> None:
        super().__init__(config)
        self._heuristic = HeuristicRetrievalReranker(config)

    async def rerank(
        self,
        *,
        layer: str,
        results: List[Dict[str, Any]],
        query: str,
        fused_scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        # Stage 1: always run heuristic
        heuristic_results = await self._heuristic.rerank(
            layer=layer,
            results=results,
            query=query,
            fused_scores=fused_scores,
        )
        if not heuristic_results or not self._enabled_for_layer(layer):
            return heuristic_results

        # Resolve model directory
        model_dir = _resolve_cross_encoder_model_dir(self._config)
        if model_dir is None:
            logger.debug("Cross-encoder model not available, using heuristic only")
            return heuristic_results

        # Stage 2: cross-encoder re-score top-K
        top_k = max(1, int(self._config.reranker_top_k))
        rerank_slice = list(heuristic_results[:top_k])
        remainder = list(heuristic_results[top_k:])

        try:
            scorer = await _get_or_create_scorer(model_dir)
            pairs = [
                (
                    query,
                    _candidate_text_for_item(
                        layer=layer,
                        item=item,
                        max_chars=self._config.reranker_candidate_max_chars,
                    ),
                )
                for item in rerank_slice
            ]
            ce_scores = await scorer.score_pairs(pairs)
        except Exception:
            logger.warning(
                "Cross-encoder scoring failed, falling back to heuristic",
                exc_info=True,
            )
            return heuristic_results

        # Combine: cross-encoder score + heuristic metadata adjustments
        scored: list[tuple[float, Dict[str, Any]]] = []
        for item, ce_score in zip(rerank_slice, ce_scores):
            trace = dict(item.get("retrieval_trace") or {})
            metadata_bonus = sum(
                float(trace.get(k, 0.0) or 0.0) for k in _HEURISTIC_METADATA_KEYS
            )
            metadata_penalty = sum(
                float(trace.get(k, 0.0) or 0.0) for k in _HEURISTIC_PENALTY_KEYS
            )
            final_score = ce_score + metadata_bonus - metadata_penalty

            trace.update({
                "backend": "cross_encoder",
                "base_backend": "heuristic",
                "ce_score": round(ce_score, 6),
                "metadata_bonus": round(metadata_bonus, 6),
                "metadata_penalty": round(metadata_penalty, 6),
            })
            enriched = dict(item)
            enriched["retrieval_score"] = final_score
            enriched["retrieval_trace"] = trace
            enriched["reranker_backend"] = "cross_encoder"
            enriched["reranker_score"] = ce_score
            scored.append((final_score, enriched))

        scored.sort(
            key=lambda pair: (pair[0], _secondary_timestamp(pair[1])),
            reverse=True,
        )
        reranked = [item for _, item in scored]

        # Annotate remainder with noop scores
        remainder_annotated = await NoopRetrievalReranker(self._config).rerank(
            layer=layer,
            results=remainder,
            query=query,
            fused_scores=fused_scores,
        )
        return reranked + remainder_annotated
