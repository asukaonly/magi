"""Scenario-based LLM adapter resolution."""

from __future__ import annotations

from typing import Callable

from ..config import AppConfig
from ..config.models import LLMProvider
from ..config.models import LLMScenario


AdapterFactory = Callable[..., object]

_OPTIONAL_SCENARIO_FALLBACKS = {
    LLMScenario.MEMORY_SUMMARIZER: LLMScenario.CORE,
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
        service = provider.services.embedding if scenario == LLMScenario.EMBEDDING else provider.services.chat
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
        adapter = self._adapter_factory(
            provider_type=provider_type,
            api_key=api_key,
            model=selection.model,
            base_url=service.base_url or provider.base_url,
            timeout=self._config.llm.timeout,
            embedding_dimension=selection.embedding_dimension if scenario == LLMScenario.EMBEDDING else None,
            proxy_url=proxy_url,
        )
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
        provider_type = str(getattr(getattr(provider, "provider_type", ""), "value", getattr(provider, "provider_type", "")))
        if provider_type != LLMProvider.CUSTOM.value:
            return provider_type

        api_format = str(getattr(provider, "api_format", "") or "openai").strip().lower()
        if api_format == "anthropic":
            return api_format
        if api_format == "openai":
            return ScenarioLLMPool._detect_openai_compatible_runtime_provider(
                provider=provider,
                selected_model=selected_model,
            )
        if api_format in {"openai", "anthropic"}:
            return api_format

        raise ValueError(f"Unsupported custom provider api_format: {getattr(provider, 'api_format', None)}")

    @staticmethod
    def _detect_openai_compatible_runtime_provider(provider: object, selected_model: str | None = None) -> str:
        """Infer the concrete OpenAI-compatible provider for custom gateways.

        This is a *one-time* dialect hint for custom providers that lack an
        explicit ``reasoning_dialect`` field. The hot path
        (``ProviderBridgeOptionsMixin._apply_provider_options``) consumes
        only the resulting dialect — the URL/name substring matching here
        merely picks which dialect bucket the custom provider falls into.

        Order is significant by design:

        1. DashScope/Bailian must precede GLM. Bailian can proxy GLM
           models, but the platform URL determines the thinking-param
           protocol — once on Bailian you must speak DashScope dialect.
        2. ``glm_codeplan`` precedes plain ``glm`` because the CodePlan
           gateway uses a stricter URL pattern.
        3. Generic vendor names come last so accidental brand overlaps
           (e.g. a deepseek-hosted GLM clone) bias toward the more
           specific gateway.

        For non-custom providers we never reach this code path; their
        dialect is keyed off ``provider_type`` directly via
        ``DEFAULT_PROVIDER_DIALECTS``.
        """
        hint_values = [
            getattr(provider, "display_name", None),
            getattr(getattr(getattr(provider, "services", None), "chat", None), "base_url", None),
            getattr(provider, "custom_default_model", None),
            selected_model,
        ]
        normalized_hints = " ".join(
            str(value or "").strip().lower()
            for value in hint_values
            if str(value or "").strip()
        )

        runtime_provider_hints = (
            ("dashscope", ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com")),
            ("glm_codeplan", ("codeplan",)),
            ("glm", ("bigmodel.cn", "z.ai", "glm-", " glm")),
            ("grok", ("api.x.ai", "x.ai", "grok")),
            ("deepseek", ("deepseek",)),
            ("kimi", ("moonshot", "kimi")),
            ("minimax", ("minimax",)),
            ("gemini", ("gemini", "generativelanguage.googleapis.com")),
        )
        for runtime_provider, markers in runtime_provider_hints:
            if any(marker in normalized_hints for marker in markers):
                return runtime_provider
        return "openai"
