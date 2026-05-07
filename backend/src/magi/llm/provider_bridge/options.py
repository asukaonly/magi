"""Provider option and concurrency helpers for LLM provider bridge."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, TypeVar, cast

from ..anthropic import AnthropicAdapter
from ..base import LLMAdapter
from ..concurrency_limiter import LLMConcurrencyLimiter
from ..reasoning_dialect import (
    ReasoningDialect,
    build_reasoning_payload,
    merge_payload,
    resolve_dialect,
)
from ...config import get_config
from ...config.loader import get_llm_provider_registry_file
from ...config.llm_registry import (
    LLMProviderRegistryModel,
    find_chat_model_meta,
    load_llm_provider_registry,
)
from ...config.models import ThinkingDepth

DEFAULT_CHAT_CONCURRENCY_FALLBACK = 4
T = TypeVar("T")


@lru_cache(maxsize=1)
def _load_provider_registry() -> LLMProviderRegistryModel:
    """Load the packaged LLM provider registry once per process."""
    return load_llm_provider_registry(
        get_llm_provider_registry_file(),
        fallback=LLMProviderRegistryModel(),
    )


class ProviderBridgeOptionsMixin:
    """Apply provider-specific thinking options and request concurrency limits."""

    llm: LLMAdapter
    _concurrency_limiter: LLMConcurrencyLimiter

    def _provider_name(self) -> str:
        return str(getattr(self.llm, "provider_name", "") or "").lower()

    def is_anthropic(self) -> bool:
        """Return True when the adapter speaks the Anthropic Messages API.

        This is a transport-level check used by the Anthropic-specific
        request paths. Reasoning/thinking parameter construction now goes
        through ``ReasoningDialect`` instead — do not gate payload shape
        on this method.
        """
        return isinstance(self.llm, AnthropicAdapter)

    def is_glm(self) -> bool:
        """Return True when the adapter targets a GLM-toggle dialect provider.

        Kept as a public facade method for callers that historically asked
        "is this GLM?" to decide payload shape. New code should call
        ``_resolve_reasoning_dialect()`` and compare against
        ``ReasoningDialect.GLM_TOGGLE`` instead.
        """
        return self._resolve_reasoning_dialect() == ReasoningDialect.GLM_TOGGLE

    def _model_supports_reasoning(self) -> bool:
        """Check if the current model advertises reasoning capability."""
        model_meta = find_chat_model_meta(
            _load_provider_registry(),
            self._provider_name(),
            str(getattr(self.llm, "model_name", "unknown")),
        )
        if model_meta is not None:
            return bool(model_meta.capabilities.reasoning)
        return False

    def _resolve_reasoning_dialect(self) -> ReasoningDialect:
        """Resolve which reasoning dialect this provider uses.

        Capability (`model_meta.capabilities.reasoning`) decides *whether*
        we may inject a reasoning param at all; dialect decides *how* to
        spell it. Anthropic is special-cased on adapter type because the
        Anthropic API has no provider_name string at the adapter layer.
        """
        if self.is_anthropic():
            return ReasoningDialect.ANTHROPIC_BUDGET
        return resolve_dialect(self._provider_name())

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Inject provider-specific reasoning parameters into LLM request kwargs."""
        dialect = self._resolve_reasoning_dialect()

        # OpenAI-effort dialects only fire when the model itself advertises
        # reasoning capability. Other dialects (Anthropic budget, DashScope
        # toggle, GLM toggle) are always meaningful when the user asks for
        # a thinking depth, so we don't gate them on capability.
        if dialect == ReasoningDialect.OPENAI_EFFORT and not self._model_supports_reasoning():
            return kwargs

        payload = build_reasoning_payload(dialect, thinking_depth)
        return merge_payload(kwargs, payload)

    def _build_concurrency_key(self, request_family: str) -> str:
        base_url = getattr(self.llm, "base_url", None)
        return cast(str, LLMConcurrencyLimiter.build_key(
            provider_name=self._provider_name(),
            model_name=str(getattr(self.llm, "model_name", "unknown")),
            request_family=request_family,
            base_url=base_url,
        ))

    def _resolve_chat_concurrency_limit(self) -> int:
        """Resolve the effective concurrency cap for chat requests."""
        key = self._build_concurrency_key("chat")
        runtime_config = get_config()
        runtime_override = getattr(runtime_config.llm, "model_runtime_overrides", {}) or {}
        override = runtime_override.get(key)
        if override is not None:
            override_limit = getattr(override, "max_concurrency", None)
            if override_limit is not None:
                return int(override_limit)

        model_meta = find_chat_model_meta(
            _load_provider_registry(),
            self._provider_name(),
            str(getattr(self.llm, "model_name", "unknown")),
        )
        if model_meta is not None and model_meta.limits.max_concurrency is not None:
            return int(model_meta.limits.max_concurrency)

        return DEFAULT_CHAT_CONCURRENCY_FALLBACK

    async def _run_with_concurrency_limit(
        self,
        *,
        request_family: str,
        operation: Callable[[], Awaitable[T]],
        limit: int | None = None,
    ) -> T:
        key = self._build_concurrency_key(request_family)
        return cast(T, await self._concurrency_limiter.run_with_limit(key, operation, limit=limit))
