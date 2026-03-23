"""Embedding helpers for the memory subsystem."""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

from ..config import get_config
from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMProviderRegistryModel,
    find_embedding_model_meta,
    load_llm_provider_registry,
)
from ..llm import LLMScenario, ScenarioLLMPool, get_llm_concurrency_limiter

T = TypeVar("T")

logger = logging.getLogger(__name__)
DEFAULT_EMBEDDING_CONCURRENCY_FALLBACK = 4


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    """Load the packaged provider registry once per process."""
    return load_llm_provider_registry(
        get_llm_provider_registry_file(),
        fallback=LLMProviderRegistryModel(),
    )


@dataclass(slots=True)
class EmbeddingResult:
    """Normalized embedding payload used by vector-backed memory stores."""

    model_name: str
    dimension: int
    vector: list[float]


@dataclass(slots=True)
class EmbeddingProfile:
    """Stable identifier for one embedding configuration."""

    profile_id: str
    provider_name: str
    model_name: str
    dimension: int | None
    text_builder_version: str

    @classmethod
    def build(
        cls,
        *,
        provider_name: str,
        model_name: str,
        dimension: int | None,
        text_builder_version: str,
    ) -> "EmbeddingProfile":
        payload = {
            "provider_name": str(provider_name).strip() or "unknown",
            "model_name": str(model_name).strip() or "embedding",
            "dimension": int(dimension) if dimension is not None else None,
            "text_builder_version": str(text_builder_version).strip() or "v1",
        }
        digest = hashlib.sha1(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:12]
        return cls(profile_id=digest, **payload)


class MemoryEmbeddingService:
    """Resolves the embedding adapter and generates vectors for memory text."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    def get_active_profile(self, *, text_builder_version: str) -> Optional[EmbeddingProfile]:
        adapter = self._get_adapter()
        if adapter is None:
            return None
        if not bool(getattr(adapter, "supports_embeddings", False)):
            return None
        model_name = str(getattr(adapter, "model_name", "embedding"))
        provider_name = str(getattr(adapter, "provider_name", "unknown"))
        raw_dimension = getattr(adapter, "embedding_dimension", None)
        dimension = int(raw_dimension) if raw_dimension is not None else None
        return EmbeddingProfile.build(
            provider_name=provider_name,
            model_name=model_name,
            dimension=dimension,
            text_builder_version=text_builder_version,
        )

    def profile_from_result(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingProfile:
        adapter = self._get_adapter()
        provider_name = str(getattr(adapter, "provider_name", "unknown")) if adapter is not None else "unknown"
        return EmbeddingProfile.build(
            provider_name=provider_name,
            model_name=result.model_name,
            dimension=result.dimension,
            text_builder_version=text_builder_version,
        )

    async def embed_text(self, text: str) -> Optional[EmbeddingResult]:
        normalized_text = text.strip()
        adapter = self._get_adapter()
        if not normalized_text or adapter is None:
            return None

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return None

        vector = await self._run_with_embedding_concurrency_limit(
            adapter=adapter,
            operation=lambda: adapter.get_embedding(normalized_text),
        )
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
        adapter = self._get_adapter()
        if not normalized_texts or adapter is None:
            return [None] * len(texts)

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return [None] * len(texts)

        try:
            vectors = await self._run_with_embedding_concurrency_limit(
                adapter=adapter,
                operation=lambda: adapter.get_embeddings(normalized_texts),
            )
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

    def _get_adapter(self):
        if self._scenario_llm_pool is None:
            return None
        try:
            return self._scenario_llm_pool.get(LLMScenario.EMBEDDING)
        except Exception as exc:
            logger.debug("Embedding adapter unavailable: %s", exc)
            return None

    def _build_embedding_concurrency_key(self, adapter: object) -> str:
        limiter = get_llm_concurrency_limiter()
        return limiter.build_key(
            provider_name=str(getattr(adapter, "provider_name", "unknown")),
            model_name=str(getattr(adapter, "model_name", "embedding")),
            request_family="embedding",
            base_url=getattr(adapter, "base_url", None),
        )

    def _resolve_embedding_concurrency_limit(self, adapter: object) -> int:
        key = self._build_embedding_concurrency_key(adapter)
        runtime_config = get_config()
        runtime_overrides = getattr(getattr(runtime_config, "llm", None), "model_runtime_overrides", {}) or {}
        override = runtime_overrides.get(key)
        if override is not None:
            override_limit = getattr(override, "max_concurrency", None)
            if override_limit is not None:
                return int(override_limit)

        provider_name = str(getattr(adapter, "provider_name", "unknown"))
        model_name = str(getattr(adapter, "model_name", "embedding"))
        model_meta = find_embedding_model_meta(_load_provider_registry(), provider_name, model_name)
        if model_meta is not None and model_meta.limits.max_concurrency is not None:
            return int(model_meta.limits.max_concurrency)

        return DEFAULT_EMBEDDING_CONCURRENCY_FALLBACK

    async def _run_with_embedding_concurrency_limit(
        self,
        *,
        adapter: object,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        limiter = get_llm_concurrency_limiter()
        key = self._build_embedding_concurrency_key(adapter)
        limit = self._resolve_embedding_concurrency_limit(adapter)
        return await limiter.run_with_limit(key, operation, limit=limit)
