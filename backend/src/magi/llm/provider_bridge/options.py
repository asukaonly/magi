"""Provider option and concurrency helpers for LLM provider bridge."""

from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, TypeVar, cast

from ..anthropic import AnthropicAdapter
from ..base import LLMAdapter
from ..cache_observability import build_cache_observation
from .cache_routing import (
    cache_routing_request_kwargs,
    routing_key_from_event_context,
)
from .cache_policy import (
    cache_marked_system_content,
    last_user_message_index,
    mark_history_breakpoint,
    mark_tool_loop_tail_breakpoint,
    turn_context_message_index,
    vendor_supports_cache_marker,
)
from ..concurrency_limiter import LLMConcurrencyLimiter, LLMRequestPriority
from ..reasoning_dialect import (
    ANTHROPIC_THINKING_BUDGETS,
    ReasoningDialect,
    anthropic_thinking_is_adaptive_only,
    build_reasoning_payload,
    merge_payload,
    resolve_dialect,
)
from ...config import get_config
from ...config.constants import DEFAULT_MAX_TOKENS
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

    def _provider_plan(self) -> str | None:
        return str(getattr(self.llm, "provider_plan", "") or "").strip().lower() or None

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
            self._provider_plan(),
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
            _load_provider_registry(), provider_name, model_name, self._provider_plan()
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

    def resolve_effective_reasoning_depth(
        self,
        requested: ThinkingDepth,
    ) -> ThinkingDepth:
        """Return the closest depth the active provider dialect can express."""

        dialect = self._resolve_reasoning_dialect()
        if dialect is ReasoningDialect.NONE:
            return ThinkingDepth.NONE
        if dialect is ReasoningDialect.OPENAI_EFFORT:
            if not self._model_supports_reasoning():
                return ThinkingDepth.NONE
            return ThinkingDepth.HIGH if requested is ThinkingDepth.MAX else requested
        if dialect is ReasoningDialect.DEEPSEEK_THINKING:
            if requested is ThinkingDepth.NONE:
                return ThinkingDepth.NONE
            return ThinkingDepth.MAX if requested is ThinkingDepth.MAX else ThinkingDepth.HIGH
        if dialect in {ReasoningDialect.DASHSCOPE_ENABLE, ReasoningDialect.GLM_TOGGLE}:
            return ThinkingDepth.NONE if requested is ThinkingDepth.NONE else ThinkingDepth.HIGH
        if dialect is ReasoningDialect.ANTHROPIC_BUDGET:
            model_id = str(getattr(self.llm, "model_name", ""))
            if requested is not ThinkingDepth.NONE and anthropic_thinking_is_adaptive_only(
                model_id
            ):
                return ThinkingDepth.HIGH
        return requested

    def _apply_anthropic_thinking_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Apply Anthropic extended-thinking options to request kwargs.

        Anthropic's Messages API has stricter rules than the generic
        dialect builder can express, so the budget path is owned here:

        - When thinking is enabled, ``temperature`` and ``top_k`` must be
          removed entirely (NOT set to 1), and ``top_p`` is only allowed
          inside ``[0.95, 1.0]`` — otherwise it must be removed too.
        - Budgeted models need ``budget_tokens >= 1024`` and strictly
          ``< max_tokens``; we bump ``max_tokens`` to leave answer
          headroom when the budget would meet or exceed it.
        - Adaptive-only models (Opus 4.7+, Fable 5) reject ``budget_tokens``
          and sampling params; they must use ``{type: "adaptive"}``.
        """
        if thinking_depth == ThinkingDepth.NONE:
            # No thinking requested: leave sampling params untouched.
            return kwargs

        kwargs.pop("temperature", None)
        kwargs.pop("top_k", None)
        top_p = kwargs.get("top_p")
        if top_p is not None and not (0.95 <= float(top_p) <= 1.0):
            kwargs.pop("top_p", None)

        model_id = str(getattr(self.llm, "model_name", ""))
        if anthropic_thinking_is_adaptive_only(model_id):
            kwargs["thinking"] = {"type": "adaptive"}
            return kwargs

        budget = ANTHROPIC_THINKING_BUDGETS.get(thinking_depth)
        if budget is None:
            return kwargs
        max_tokens = kwargs.get("max_tokens")
        if isinstance(max_tokens, int) and budget >= max_tokens:
            kwargs["max_tokens"] = budget + DEFAULT_MAX_TOKENS
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        return kwargs

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Inject vendor-specific reasoning parameters into LLM request kwargs."""
        dialect = self._resolve_reasoning_dialect()

        # Anthropic budget is special-cased ahead of the generic builder:
        # it has to strip incompatible sampling params, guarantee
        # max_tokens headroom, and switch adaptive-only models to the
        # budget-less ``adaptive`` shape (see helper docstring).
        if dialect == ReasoningDialect.ANTHROPIC_BUDGET:
            return self._apply_anthropic_thinking_options(kwargs, thinking_depth)

        # OpenAI-effort dialects only fire when the model itself advertises
        # reasoning capability. Other dialects (DashScope toggle, GLM
        # toggle) are always meaningful when the user asks for a thinking
        # depth, so we don't gate them on capability.
        if dialect == ReasoningDialect.OPENAI_EFFORT and not self._model_supports_reasoning():
            return kwargs

        payload = build_reasoning_payload(dialect, thinking_depth)
        return cast(Dict[str, Any], merge_payload(kwargs, payload))

    def _cache_marked_system(self, system_prompt: str, *, cache_whole: bool = False) -> Any:
        """Build the system content with a prompt-cache breakpoint.

        For marker-capable vendors (Anthropic, Qwen/DashScope) the byte-stable
        head — split at the renderer's boundary — gets an ``ephemeral``
        cache_control marker; for automatic-only vendors the boundary is simply
        stripped and a plain string returned. Used by every Anthropic ``system``
        and OpenAI system-message construction site (#110).

        ``cache_whole`` is for auxiliary calls (routing, memory extraction) whose
        whole system prompt is byte-stable but carries no renderer boundary: the
        entire system is marked as one cacheable block for marker vendors.
        """
        vendor = self._marker_vendor()
        # The system head is stable across turns AND conversations, so a 1h TTL
        # (2x write) amortizes far better than the 5m default; only Anthropic is
        # known to honor the longer TTL, so keep DashScope on the default.
        ttl = "1h" if vendor == ModelVendor.ANTHROPIC else None
        return cache_marked_system_content(
            system_prompt,
            supports_marker=vendor_supports_cache_marker(vendor),
            ttl=ttl,
            cache_whole=cache_whole,
        )

    def _mark_message_cache_breakpoints(
        self,
        injected_messages: list[Dict[str, Any]],
        api_messages: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        """Add message-stream cache breakpoints to converted request messages.

        Marker vendors (Anthropic, DashScope — both honor inline ``cache_control``;
        the latter verified by direct probe) cache by prefix and need explicit
        markers. Two breakpoints, both 5m (they sit after the 1h system head,
        satisfying Anthropic's 1h-before-5m ordering):

        - **Rolling history**: the message before the explicit turn-context
          snapshot is the stable history boundary.
        - **Tool-loop tail**: when the raw turn ends in a tool result we are
          mid-loop; mark the last message so the next loop iteration hits the
          growing tool history (P2b made it append-only/cacheable).

        ``tool``-role messages are never marked: OpenAI-compatible tool results
        carry role ``tool`` with plain-string content, and not every compat
        endpoint accepts a content-block list there. Anthropic converts tool
        results to role ``user``, so this guard never skips on the native path —
        the Anthropic behavior is unchanged.

        Indices align 1:1 between model-context messages and converted messages.
        No-op for non-marker vendors or first turns.
        """
        if not vendor_supports_cache_marker(self._marker_vendor()):
            return api_messages
        turn_context_index = turn_context_message_index(injected_messages)
        boundary_index = (
            turn_context_index - 1
            if turn_context_index >= 0
            else last_user_message_index(injected_messages) - 1
        )
        if (
            0 <= boundary_index < len(api_messages)
            and api_messages[boundary_index].get("role") != "tool"
        ):
            api_messages = mark_history_breakpoint(api_messages, boundary_index)
        tail_active = (
            bool(injected_messages)
            and injected_messages[-1].get("role") == "tool"
            and bool(api_messages)
            and api_messages[-1].get("role") != "tool"
        )
        return mark_tool_loop_tail_breakpoint(api_messages, active=tail_active)

    def _marker_vendor(self) -> ModelVendor:
        """Vendor used for cache-marker capability decisions (Anthropic if the
        native path is active, else the resolved OpenAI-compatible vendor)."""
        return ModelVendor.ANTHROPIC if self.is_anthropic() else self._resolve_model_vendor()

    def _apply_cache_routing(
        self, kwargs: Dict[str, Any], event_context: Dict[str, Any] | None
    ) -> Dict[str, Any]:
        """Merge provider cache-routing extras into OpenAI-compatible request kwargs.

        OpenAI's ``prompt_cache_key`` (body) / xAI's ``x-grok-conv-id`` (header)
        pin a conversation to a cache-warm backend node, lifting the hit rate.
        Keyed on ``session_id``, vendor-gated, and merged so existing
        ``extra_body``/``extra_headers`` (e.g. reasoning options) survive. No-op
        when there's no key or the vendor has no hint. OpenAI-compatible path only
        (#98).
        """
        extras = cache_routing_request_kwargs(
            self._resolve_model_vendor(), routing_key_from_event_context(event_context)
        )
        for field, value in extras.items():
            kwargs[field] = {**(kwargs.get(field) or {}), **value}
        return kwargs

    def _with_cache_observation(
        self,
        event_context: Dict[str, Any] | None,
        *,
        system_prompt: str,
        tools: list[dict[str, Any]] | None,
        cache_whole_system: bool = False,
    ) -> Dict[str, Any] | None:
        """Attach sanitized prompt-cache diagnostics to the event context."""
        config = get_config()
        lifecycle = getattr(config, "lifecycle", None)
        llm_usage = getattr(lifecycle, "llm_usage", None)
        settings = getattr(llm_usage, "cache_observability", None)
        if settings is not None and not bool(getattr(settings, "enabled", True)):
            return event_context

        context: Dict[str, Any] = dict(event_context or {})
        store_tool_names = True
        if settings is not None:
            store_tool_names = bool(getattr(settings, "store_tool_names", True))
        context["cache_observation"] = build_cache_observation(
            system_prompt=system_prompt,
            tools=tools,
            vendor=self._marker_vendor(),
            event_context=context,
            cache_whole_system=cache_whole_system,
            store_tool_names=store_tool_names,
        )
        return context

    def _build_concurrency_key(self, request_family: str) -> str:
        base_url = getattr(self.llm, "base_url", None)
        return cast(
            str,
            LLMConcurrencyLimiter.build_key(
                provider_name=self._provider_name(),
                provider_instance_id=getattr(self.llm, "provider_instance_id", None),
                provider_plan=self._provider_plan(),
                model_name=str(getattr(self.llm, "model_name", "unknown")),
                request_family=request_family,
                base_url=base_url,
            ),
        )

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

        return DEFAULT_CHAT_CONCURRENCY_FALLBACK

    async def _run_with_concurrency_limit(
        self,
        *,
        request_family: str,
        operation: Callable[[], Awaitable[T]],
        limit: int | None = None,
        priority: LLMRequestPriority | str | int | None = None,
    ) -> T:
        key = self._build_concurrency_key(request_family)
        return cast(
            T,
            await self._concurrency_limiter.run_with_limit(
                key,
                operation,
                limit=limit,
                priority=priority,
            ),
        )

    @asynccontextmanager
    async def _limit_concurrency(
        self,
        *,
        request_family: str,
        limit: int | None = None,
        priority: LLMRequestPriority | str | int | None = None,
    ) -> AsyncIterator[None]:
        key = self._build_concurrency_key(request_family)
        async with self._concurrency_limiter.limit(key, limit=limit, priority=priority):
            yield
