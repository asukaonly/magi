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
from ...config.llm_registry_model_resolution import _BUILTIN_PROVIDER_VENDOR
from ...config.models import ModelVendor, ThinkingDepth
from ...config.vendor_detection import detect_vendor_from_hints

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

        Transport-level check; reasoning payload shape goes through
        ``ReasoningDialect`` instead.
        """
        return isinstance(self.llm, AnthropicAdapter)

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

    def _resolve_model_vendor(self) -> ModelVendor:
        """Resolve the active model's vendor.

        Lookup order:
        1. User config override (``LLMModelMetadataOverrideSettings.vendor``)
           — already merged into runtime model metadata when a resolved
           catalog is available.
        2. Packaged registry: ``LLMModelMetaModel.vendor`` if set,
           otherwise the per-provider builtin default.
        3. Heuristic detection from model id + base url. Only fires for
           custom-gateway models that have no override and no packaged
           entry.
        """
        provider_name = self._provider_name()
        model_name = str(getattr(self.llm, "model_name", "unknown"))

        # 1+2: user override merged into resolved catalog
        config = get_config()
        provider_settings = (
            config.llm.providers.get(provider_name)
            if hasattr(config, "llm") and hasattr(config.llm, "providers")
            else None
        )
        if provider_settings is not None:
            override = (provider_settings.model_metadata_overrides or {}).get(model_name)
            if override is not None and override.vendor is not None:
                return override.vendor

        # 2: packaged registry
        model_meta = find_chat_model_meta(
            _load_provider_registry(), provider_name, model_name
        )
        if model_meta is not None and model_meta.vendor is not None:
            return model_meta.vendor
        builtin_default = _BUILTIN_PROVIDER_VENDOR.get(provider_name)
        if builtin_default is not None:
            return builtin_default

        # 3: detect from model id / base url for custom-gateway models
        return detect_vendor_from_hints(
            model_id=model_name,
            base_url=getattr(self.llm, "base_url", None),
        )

    def _resolve_reasoning_dialect(self) -> ReasoningDialect:
        """Resolve which reasoning dialect this model uses.

        Anthropic transport short-circuits to ``ANTHROPIC_BUDGET`` because
        the AnthropicAdapter never exposes a vendor-tagged model meta on
        its own; everything else looks up vendor via
        :meth:`_resolve_model_vendor` and then maps to a dialect.
        """
        if self.is_anthropic():
            return ReasoningDialect.ANTHROPIC_BUDGET
        return resolve_dialect(self._resolve_model_vendor())

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Inject vendor-specific reasoning parameters into LLM request kwargs."""
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
