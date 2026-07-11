"""Scenario-based LLM adapter resolution."""

from __future__ import annotations

from typing import Callable

from ..config import AppConfig
from ..config.models import LLMProvider
from ..config.models import LLMScenario
from .model_context import ModelContextProfile, ResolvedModel

AdapterFactory = Callable[..., object]

_OPTIONAL_SCENARIO_FALLBACKS = {
    LLMScenario.MEMORY_SUMMARIZER: LLMScenario.CORE,
    LLMScenario.TIMELINE_DIARY_NARRATIVE: LLMScenario.CORE,
}


class ScenarioLLMPool:
    """Resolves and caches LLM adapters by runtime scenario."""

    def __init__(self, *, config: AppConfig, adapter_factory: AdapterFactory) -> None:
        self._config = config
        self._adapter_factory = adapter_factory
        self._cache: dict[LLMScenario, object] = {}
        self._adapter_configurators: list[Callable[[object], None]] = []

    def get(self, scenario: LLMScenario) -> object:
        if scenario not in self._cache:
            self._cache[scenario] = self._build_adapter(scenario)
        return self._cache[scenario]

    def resolve(self, scenario: LLMScenario) -> ResolvedModel:
        """Resolve an adapter together with the limits of its selected model."""
        selection = self._selection_for_scenario(scenario)
        if selection is None:
            raise ValueError(f"Missing LLM selection for scenario '{scenario.value}'")
        limits = getattr(selection, "limits", None)
        context_window = getattr(limits, "context_window", None)
        max_output_tokens = getattr(limits, "max_output_tokens", None)
        return ResolvedModel(
            adapter=self.get(scenario),
            context=ModelContextProfile(
                provider_id=str(getattr(selection, "provider_id", "") or ""),
                model_id=str(getattr(selection, "model", "") or ""),
                context_window=(
                    context_window
                    if isinstance(context_window, int) and context_window > 0
                    else None
                ),
                max_output_tokens=(
                    max_output_tokens
                    if isinstance(max_output_tokens, int) and max_output_tokens > 0
                    else None
                ),
            ),
        )

    def refresh(self, config: AppConfig) -> None:
        self._config = config
        self._cache.clear()

    def add_adapter_configurator(self, configurator: Callable[[object], None]) -> None:
        self._adapter_configurators.append(configurator)
        for adapter in self._cache.values():
            configurator(adapter)

    def _build_adapter(self, scenario: LLMScenario) -> object:
        selection = self._selection_for_scenario(scenario)
        if selection is None:
            raise ValueError(f"Missing LLM selection for scenario '{scenario.value}'")

        provider = self._config.llm.providers.get(selection.provider_id)
        if provider is None:
            raise ValueError(
                f"LLM scenario '{scenario.value}' references unknown provider '{selection.provider_id}'"
            )
        if not provider.enabled:
            raise ValueError(
                f"LLM scenario '{scenario.value}' references disabled provider '{selection.provider_id}'"
            )
        service = (
            provider.services.embedding
            if scenario == LLMScenario.EMBEDDING
            else provider.services.chat
        )
        service_label = "embedding" if scenario == LLMScenario.EMBEDDING else "chat"
        if not service.enabled:
            raise ValueError(
                f"LLM provider '{selection.provider_id}' has {service_label} service disabled for scenario '{scenario.value}'"
            )
        api_key = service.api_key or provider.api_key
        if not api_key:
            raise ValueError(
                f"LLM provider '{selection.provider_id}' is missing an API key for scenario '{scenario.value}'"
            )

        provider_type = self._resolve_runtime_provider_type(provider, selection.model)
        proxy_url = self._config.network.proxy_url() if hasattr(self._config, "network") else None
        adapter_kwargs = {
            "provider_type": provider_type,
            "api_key": api_key,
            "model": selection.model,
            "base_url": service.base_url or provider.base_url,
            "timeout": self._config.llm.timeout,
            "embedding_dimension": (
                selection.embedding_dimension if scenario == LLMScenario.EMBEDDING else None
            ),
            "proxy_url": proxy_url,
        }
        provider_plan = str(getattr(provider, "provider_plan", "") or "").strip() or None
        if provider_plan:
            adapter_kwargs["provider_plan"] = provider_plan
        adapter = self._adapter_factory(**adapter_kwargs)
        for configurator in self._adapter_configurators:
            configurator(adapter)
        return adapter

    def _selection_for_scenario(self, scenario: LLMScenario) -> object | None:
        selection = self._config.llm.selections.get(scenario.value)
        if selection is not None:
            return selection
        fallback = _OPTIONAL_SCENARIO_FALLBACKS.get(scenario)
        if fallback is None:
            return None
        return self._config.llm.selections.get(fallback.value)

    @staticmethod
    def _resolve_runtime_provider_type(provider: object, selected_model: str | None = None) -> str:
        """Pick the adapter ``provider_type`` for ``create_llm_adapter``.

        For non-custom providers this is just the declared ``provider_type``.
        For custom providers we look at ``api_format`` to decide which
        adapter (OpenAI or Anthropic transport) to use; vendor-specific
        dialects (reasoning payload shape, tool-calling format, ...) are
        no longer baked into the provider name. The runtime picks them
        up later from ``ModelVendor`` declared on the resolved model meta
        (with a model-id-based heuristic as a last-resort default).
        """
        del selected_model  # vendor inference moved to ProviderBridgeOptionsMixin
        provider_type = str(
            getattr(
                getattr(provider, "provider_type", ""),
                "value",
                getattr(provider, "provider_type", ""),
            )
        )
        if provider_type != LLMProvider.CUSTOM.value:
            return provider_type

        api_format = str(getattr(provider, "api_format", "") or "openai").strip().lower()
        if api_format == "anthropic":
            return LLMProvider.ANTHROPIC.value
        if api_format == "openai":
            # Custom OpenAI-compatible gateway. Keep ``custom`` as the
            # adapter-level provider name; ProviderBridgeOptionsMixin
            # resolves the actual vendor (and therefore the reasoning
            # dialect) per-model from the resolved registry / overrides
            # / model-id heuristic, not from this string.
            return LLMProvider.CUSTOM.value

        raise ValueError(
            f"Unsupported custom provider api_format: {getattr(provider, 'api_format', None)}"
        )
