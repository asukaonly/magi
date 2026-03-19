"""Embedding helpers for the memory subsystem."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..llm import LLMScenario, ScenarioLLMPool

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmbeddingResult:
    """Normalized embedding payload used by vector-backed memory stores."""

    model_name: str
    dimension: int
    vector: list[float]


class MemoryEmbeddingService:
    """Resolves the embedding adapter and generates vectors for memory text."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    async def embed_text(self, text: str) -> Optional[EmbeddingResult]:
        normalized_text = text.strip()
        if not normalized_text or self._scenario_llm_pool is None:
            return None

        try:
            adapter = self._scenario_llm_pool.get(LLMScenario.EMBEDDING)
        except Exception as exc:
            logger.debug("Embedding adapter unavailable: %s", exc)
            return None

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return None

        vector = await adapter.get_embedding(normalized_text)
        if not vector:
            return None

        values = [float(value) for value in vector]
        return EmbeddingResult(
            model_name=str(getattr(adapter, "model_name", "embedding")),
            dimension=len(values),
            vector=values,
        )

    async def embed_texts(self, texts: list[str]) -> list[Optional[EmbeddingResult]]:
        normalized_texts = [text.strip() for text in texts]
        if not normalized_texts or self._scenario_llm_pool is None:
            return [None] * len(texts)

        try:
            adapter = self._scenario_llm_pool.get(LLMScenario.EMBEDDING)
        except Exception as exc:
            logger.debug("Embedding adapter unavailable: %s", exc)
            return [None] * len(texts)

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return [None] * len(texts)

        try:
            vectors = await adapter.get_embeddings(normalized_texts)
        except Exception as exc:
            logger.debug("Batch embedding call failed: %s", exc)
            return [None] * len(texts)

        model_name = str(getattr(adapter, "model_name", "embedding"))
        results: list[Optional[EmbeddingResult]] = []
        for index, text in enumerate(normalized_texts):
            if not text:
                results.append(None)
                continue
            vector = vectors[index] if index < len(vectors) else None
            if not vector:
                results.append(None)
                continue
            values = [float(value) for value in vector]
            results.append(
                EmbeddingResult(
                    model_name=model_name,
                    dimension=len(values),
                    vector=values,
                )
            )
        return results
