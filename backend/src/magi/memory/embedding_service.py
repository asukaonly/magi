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