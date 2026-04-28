"""Provider option and concurrency helpers for LLM provider bridge."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict

from .anthropic import AnthropicAdapter
from .base import LLMAdapter
from .concurrency_limiter import LLMConcurrencyLimiter
from .provider_bridge_models import ProviderResponse
from ..config import get_config
from ..config.loader import get_llm_provider_registry_file
from ..config.llm_registry import (
    LLMProviderRegistryModel,
    find_chat_model_meta,
    load_llm_provider_registry,
)
from ..config.models import ThinkingDepth

DEFAULT_CHAT_CONCURRENCY_FALLBACK = 4


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
        return (getattr(self.llm, "provider_name", "") or "").lower()

    def is_anthropic(self) -> bool:
        return isinstance(self.llm, AnthropicAdapter)

    def is_glm(self) -> bool:
        """Check if using GLM provider (including CodePlan)."""
        return self._provider_name() in ("glm", "glm_codeplan")

    @staticmethod
    def _disabled_thinking_extra_body(disable_thinking: bool | None) -> Dict[str, Any] | None:
        """Build provider-specific payload to disable reasoning/thinking mode.

        .. deprecated:: Use ``_build_glm_thinking_params`` with ThinkingDepth.
        """
        if disable_thinking is not True:
            return None
        return {"thinking": {"type": "disabled"}}

    @staticmethod
    def _build_glm_thinking_params(depth: ThinkingDepth) -> Dict[str, Any] | None:
        """Build GLM extra_body payload for the requested thinking depth.

        GLM only supports a binary toggle: thinking enabled or disabled.
        """
        if depth == ThinkingDepth.NONE:
            return {"thinking": {"type": "disabled"}}
        return None

    @staticmethod
    def _build_dashscope_thinking_params(depth: ThinkingDepth) -> Dict[str, Any]:
        """Build DashScope/Bailian extra_body payload for thinking control.

        DashScope uses ``enable_thinking`` boolean in extra_body.
        """
        if depth == ThinkingDepth.NONE:
            return {"enable_thinking": False}
        return {"enable_thinking": True}

    @staticmethod
    def _build_openai_reasoning_params(depth: ThinkingDepth) -> Dict[str, Any]:
        """Build OpenAI-compatible extra kwargs for reasoning effort."""
        mapping = {
            ThinkingDepth.NONE: "none",
            ThinkingDepth.LOW: "low",
            ThinkingDepth.MEDIUM: "medium",
            ThinkingDepth.HIGH: "high",
            ThinkingDepth.MAX: "high",
        }
        return {"reasoning_effort": mapping.get(depth, "medium")}

    @staticmethod
    def _build_anthropic_thinking_params(depth: ThinkingDepth) -> Dict[str, Any] | None:
        """Map ThinkingDepth to Anthropic extended thinking budget."""
        budget_map = {
            ThinkingDepth.NONE: None,
            ThinkingDepth.LOW: 2048,
            ThinkingDepth.MEDIUM: 8192,
            ThinkingDepth.HIGH: 16384,
            ThinkingDepth.MAX: 32768,
        }
        tokens = budget_map.get(depth)
        if tokens is None:
            return None
        return {"thinking": {"type": "enabled", "budget_tokens": tokens}}

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

    def _apply_provider_options(
        self,
        kwargs: Dict[str, Any],
        thinking_depth: ThinkingDepth,
    ) -> Dict[str, Any]:
        """Inject provider-specific parameters into LLM request kwargs."""
        provider = self._provider_name()

        if provider == "dashscope":
            dashscope_extra_body = self._build_dashscope_thinking_params(thinking_depth)
            existing = kwargs.get("extra_body", {})
            kwargs["extra_body"] = {**existing, **dashscope_extra_body}

        elif provider in ("glm", "glm_codeplan"):
            glm_extra_body = self._build_glm_thinking_params(thinking_depth)
            if glm_extra_body:
                existing = kwargs.get("extra_body", {})
                kwargs["extra_body"] = {**existing, **glm_extra_body}

        elif self.is_anthropic():
            budget = self._build_anthropic_thinking_params(thinking_depth)
            if budget:
                kwargs.update(budget)

        elif self._model_supports_reasoning():
            kwargs.update(self._build_openai_reasoning_params(thinking_depth))

        return kwargs

    def _build_concurrency_key(self, request_family: str) -> str:
        base_url = getattr(self.llm, "base_url", None)
        return LLMConcurrencyLimiter.build_key(
            provider_name=self._provider_name(),
            model_name=str(getattr(self.llm, "model_name", "unknown")),
            request_family=request_family,
            base_url=base_url,
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
        operation: Callable[[], Awaitable[ProviderResponse]],
        limit: int | None = None,
    ) -> ProviderResponse:
        key = self._build_concurrency_key(request_family)
        return await self._concurrency_limiter.run_with_limit(key, operation, limit=limit)
