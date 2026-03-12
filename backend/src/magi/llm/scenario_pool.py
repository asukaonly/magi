"""Scenario-based LLM adapter resolution."""

from __future__ import annotations

from typing import Callable

from ..config import AppConfig
from ..config.models import LLMScenario


AdapterFactory = Callable[..., object]


class ScenarioLLMPool:
    """Resolves and caches LLM adapters by runtime scenario."""

    def __init__(self, *, config: AppConfig, adapter_factory: AdapterFactory) -> None:
        self._config = config
        self._adapter_factory = adapter_factory
        self._cache: dict[LLMScenario, object] = {}

    def get(self, scenario: LLMScenario) -> object:
        if scenario not in self._cache:
            self._cache[scenario] = self._build_adapter(scenario)
        return self._cache[scenario]

    def refresh(self, config: AppConfig) -> None:
        self._config = config
        self._cache.clear()

    def _build_adapter(self, scenario: LLMScenario) -> object:
        selection = self._config.llm.selections.get(scenario.value)
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
        if not provider.api_key:
            raise ValueError(
                f"LLM provider '{selection.provider_id}' is missing an API key for scenario '{scenario.value}'"
            )

        provider_type = str(getattr(provider.provider_type, "value", provider.provider_type))
        return self._adapter_factory(
            provider_type=provider_type,
            api_key=provider.api_key,
            model=selection.model,
            base_url=provider.base_url,
            timeout=self._config.llm.timeout,
        )
