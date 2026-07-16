"""Embedding helpers for the memory subsystem."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypeVar

from ...config import get_config
from ...config.models import EmbeddingMode
from ...llm import LLMScenario, ScenarioLLMPool, get_llm_concurrency_limiter
from ...llm.usage_tracing import publish_llm_usage_span

T = TypeVar("T")

if TYPE_CHECKING:
    from .local_embedding_manager import LocalEmbeddingManager

logger = logging.getLogger(__name__)
DEFAULT_EMBEDDING_CONCURRENCY_FALLBACK = 4


@dataclass(slots=True)
class EmbeddingResult:
    """Normalized embedding payload used by vector-backed memory stores."""

    model_name: str
    dimension: int
    vector: list[float]
    model_identity: str | None = None
    index_identity: str | None = None


@dataclass(slots=True)
class EmbeddingProfile:
    """Stable identifier for one embedding configuration."""

    profile_id: str
    provider_name: str
    model_name: str
    dimension: int | None
    text_builder_version: str
    identity_kind: str = "remote"
    identity_key: str = ""
    provenance: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        provider_name: str,
        model_name: str,
        dimension: int | None,
        text_builder_version: str,
        identity_kind: str = "remote",
        identity_key: str | None = None,
        provenance: dict[str, str | None] | None = None,
    ) -> "EmbeddingProfile":
        normalized_provider_name = str(provider_name).strip() or "unknown"
        normalized_model_name = str(model_name).strip() or "embedding"
        normalized_identity_kind = str(identity_kind).strip().lower() or "remote"
        normalized_identity_key = str(identity_key or normalized_model_name).strip()
        normalized_text_builder_version = str(text_builder_version).strip() or "v1"
        normalized_dimension = int(dimension) if dimension is not None else None
        payload = {
            "identity_kind": normalized_identity_kind,
            "identity_key": normalized_identity_key,
            "model_name": normalized_model_name if normalized_identity_kind == "remote" else None,
            "dimension": normalized_dimension,
            "text_builder_version": normalized_text_builder_version,
        }
        digest = hashlib.sha1(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:12]
        return cls(
            profile_id=digest,
            provider_name=normalized_provider_name,
            model_name=normalized_model_name,
            dimension=normalized_dimension,
            text_builder_version=normalized_text_builder_version,
            identity_kind=normalized_identity_kind,
            identity_key=normalized_identity_key,
            provenance=dict(provenance or {}),
        )


class MemoryEmbeddingService:
    """Resolves the embedding adapter and generates vectors for memory text."""

    def __init__(self, scenario_llm_pool: ScenarioLLMPool | None) -> None:
        self._scenario_llm_pool = scenario_llm_pool
        self._local_manager: Optional["LocalEmbeddingManager"] = None
        self._local_manager_config_key: tuple[str, ...] | None = None

    def _get_local_manager(self) -> Optional["LocalEmbeddingManager"]:
        """Return a cached LocalEmbeddingManager, rebuilding if config changed."""
        config = get_config()
        local_cfg = config.agent.memory.embedding.local
        cache_key = (
            str(local_cfg.model_source),
            str(local_cfg.managed_model_id or ""),
            str(local_cfg.model_dir_path or ""),
            str(local_cfg.variant or ""),
            str(local_cfg.idle_timeout_seconds),
        )
        if cache_key != self._local_manager_config_key:
            # Config changed — shutdown old manager if any
            if self._local_manager is not None:
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._local_manager.shutdown())
                except RuntimeError:
                    pass
            from .local_embedding_manager import LocalEmbeddingManager

            self._local_manager = LocalEmbeddingManager(local_cfg)
            self._local_manager_config_key = cache_key
        return self._local_manager

    def _is_local_mode(self) -> bool:
        """Check if local embedding mode is active."""
        config = get_config()
        return config.agent.memory.embedding.mode == EmbeddingMode.LOCAL

    def _is_off_mode(self) -> bool:
        """Check if embedding is disabled."""
        config = get_config()
        return config.agent.memory.embedding.mode == EmbeddingMode.OFF

    def get_active_profile(self, *, text_builder_version: str) -> Optional[EmbeddingProfile]:
        if self._is_off_mode():
            return None
        if self._is_local_mode():
            manager = self._get_local_manager()
            if manager is None:
                return None
            from .local_embedding_identity import compute_local_embedding_model_fingerprint

            config = get_config()
            fingerprint = compute_local_embedding_model_fingerprint(
                config.agent.memory.embedding.local
            )
            model_name = (
                fingerprint.model_name if fingerprint is not None else manager.model_name
            ) or "local"
            dimension = fingerprint.dimension if fingerprint is not None else manager.dimension
            return EmbeddingProfile.build(
                provider_name="local",
                model_name=model_name,
                dimension=dimension,
                text_builder_version=text_builder_version,
                identity_kind="local",
                identity_key=fingerprint.identity_key if fingerprint is not None else model_name,
                provenance={
                    "model_source": str(config.agent.memory.embedding.local.model_source),
                    "model_dir_path": (
                        str(fingerprint.model_dir) if fingerprint is not None else None
                    ),
                },
            )

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
            identity_kind="remote",
            identity_key=model_name,
            provenance={
                "provider_name": provider_name,
                "base_url": str(getattr(adapter, "base_url", "") or "") or None,
            },
        )

    def profile_from_result(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingProfile:
        if self._is_local_mode():
            profile = EmbeddingProfile.build(
                provider_name="local",
                model_name=result.model_name,
                dimension=result.dimension,
                text_builder_version=text_builder_version,
                identity_kind="local",
                identity_key=result.model_identity or result.model_name,
            )
        else:
            adapter = self._get_adapter()
            provider_name = (
                str(getattr(adapter, "provider_name", "unknown"))
                if adapter is not None
                else "unknown"
            )
            profile = EmbeddingProfile.build(
                provider_name=provider_name,
                model_name=result.model_name,
                dimension=result.dimension,
                text_builder_version=text_builder_version,
                identity_kind="remote",
                identity_key=result.model_name,
            )
        if result.index_identity:
            profile.profile_id = str(result.index_identity)
        return profile

    def result_for_index(
        self,
        result: EmbeddingResult,
        *,
        text_builder_version: str,
    ) -> EmbeddingResult:
        profile = self.profile_from_result(result, text_builder_version=text_builder_version)
        return EmbeddingResult(
            model_name=result.model_name,
            dimension=result.dimension,
            vector=result.vector,
            model_identity=result.model_identity,
            index_identity=profile.profile_id,
        )

    async def embed_text(self, text: str) -> Optional[EmbeddingResult]:
        if self._is_local_mode():
            return await self._embed_text_local(text)
        return await self._embed_text_remote(text)

    async def embed_texts(self, texts: list[str]) -> list[Optional[EmbeddingResult]]:
        if self._is_local_mode():
            return await self._embed_texts_local(texts)
        return await self._embed_texts_remote(texts)

    # ── Local embedding ─────────────────────────────────────────────────

    async def _embed_text_local(self, text: str) -> Optional[EmbeddingResult]:
        manager = self._get_local_manager()
        if manager is None:
            return None
        try:
            vector = await manager.embed(text)
        except Exception as exc:
            logger.error("Local embedding failed: %s", exc)
            return None
        if not vector:
            return None
        return EmbeddingResult(
            model_name=manager.model_name or "local",
            dimension=len(vector),
            vector=vector,
            model_identity=manager.model_identity,
        )

    async def _embed_texts_local(self, texts: list[str]) -> list[Optional[EmbeddingResult]]:
        manager = self._get_local_manager()
        if manager is None:
            return [None] * len(texts)
        try:
            vectors = await manager.embed_batch(texts)
        except Exception as exc:
            logger.error("Local batch embedding failed: %s", exc)
            return [None] * len(texts)
        model_name = manager.model_name or "local"
        results: list[Optional[EmbeddingResult]] = []
        for vec in vectors:
            if vec is None:
                results.append(None)
            else:
                results.append(
                    EmbeddingResult(
                        model_name=model_name,
                        dimension=len(vec),
                        vector=vec,
                        model_identity=manager.model_identity,
                    )
                )
        return results

    # ── Remote embedding ────────────────────────────────────────────────

    async def _embed_text_remote(self, text: str) -> Optional[EmbeddingResult]:
        normalized_text = text.strip()
        adapter = self._get_adapter()
        if not normalized_text or adapter is None:
            return None

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return None

        started_at = time.time()
        try:
            vector, prompt_tokens = await self._run_with_embedding_concurrency_limit(
                adapter=adapter,
                operation=lambda: adapter.get_embedding_with_usage(normalized_text),
            )
        except Exception as exc:
            await self._publish_embedding_usage(
                adapter, started_at=started_at, success=False, error=str(exc), prompt_tokens=0
            )
            raise
        await self._publish_embedding_usage(
            adapter, started_at=started_at, success=bool(vector), prompt_tokens=prompt_tokens
        )
        if not vector:
            return None

        values = [float(value) for value in vector]
        return EmbeddingResult(
            model_name=str(getattr(adapter, "model_name", "embedding")),
            dimension=len(values),
            vector=values,
        )

    # DashScope (Alibaba) embedding API caps at 10 inputs per request.
    _REMOTE_EMBED_BATCH_SIZE = 10

    async def _embed_texts_remote(self, texts: list[str]) -> list[Optional[EmbeddingResult]]:
        normalized_texts = [text.strip() for text in texts]
        adapter = self._get_adapter()
        if not normalized_texts or adapter is None:
            return [None] * len(texts)

        if not bool(getattr(adapter, "supports_embeddings", False)):
            return [None] * len(texts)

        # Sub-batch to stay within provider per-request input limits.
        all_vectors: list[Optional[list[float]]] = [None] * len(normalized_texts)
        batch_sz = self._REMOTE_EMBED_BATCH_SIZE
        for start in range(0, len(normalized_texts), batch_sz):
            sub_texts = normalized_texts[start : start + batch_sz]
            sub_start = start  # capture for lambda
            started_at = time.time()
            try:
                sub_vectors, prompt_tokens = await self._run_with_embedding_concurrency_limit(
                    adapter=adapter,
                    operation=lambda _st=sub_texts: adapter.get_embeddings_with_usage(_st),
                )
            except Exception as exc:
                await self._publish_embedding_usage(
                    adapter, started_at=started_at, success=False, error=str(exc), prompt_tokens=0
                )
                logger.debug("Batch embedding sub-batch failed (offset %d): %s", start, exc)
                continue
            await self._publish_embedding_usage(
                adapter,
                started_at=started_at,
                success=bool(sub_vectors and any(vector for vector in sub_vectors)),
                prompt_tokens=prompt_tokens,
            )
            if sub_vectors:
                for i, vec in enumerate(sub_vectors):
                    all_vectors[sub_start + i] = vec

        model_name = str(getattr(adapter, "model_name", "embedding"))
        results: list[Optional[EmbeddingResult]] = []
        for index, text in enumerate(normalized_texts):
            if not text:
                results.append(None)
                continue
            vector = all_vectors[index]
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
            provider_instance_id=getattr(adapter, "provider_instance_id", None),
            provider_plan=getattr(adapter, "provider_plan", None),
            model_name=str(getattr(adapter, "model_name", "embedding")),
            request_family="embedding",
            base_url=getattr(adapter, "base_url", None),
        )

    def _resolve_embedding_concurrency_limit(self, adapter: object) -> int:
        key = self._build_embedding_concurrency_key(adapter)
        runtime_config = get_config()
        runtime_overrides = (
            getattr(getattr(runtime_config, "llm", None), "model_runtime_overrides", {}) or {}
        )
        override = runtime_overrides.get(key)
        if override is not None:
            override_limit = getattr(override, "max_concurrency", None)
            if override_limit is not None:
                return int(override_limit)

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

    async def _publish_embedding_usage(
        self,
        adapter: object,
        *,
        started_at: float,
        success: bool,
        error: str | None = None,
        prompt_tokens: int = 0,
    ) -> None:
        try:
            # Embeddings have no completion tokens; total == prompt.
            await publish_llm_usage_span(
                provider=str(getattr(adapter, "provider_name", "unknown") or "unknown"),
                model=str(getattr(adapter, "model_name", "embedding") or "embedding"),
                request_kind="embedding",
                success=success,
                started_at=started_at,
                error=error,
                prompt_tokens=prompt_tokens,
                total_tokens=prompt_tokens,
                usage_available=(prompt_tokens > 0),
                event_context={"agent_id": "memory:embedding"},
            )
        except Exception:
            logger.debug("Embedding usage publication failed", exc_info=True)
