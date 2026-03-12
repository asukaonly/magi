from __future__ import annotations

from magi.config.models import AppConfig, LLMProvider


class DummyAdapter:
    def __init__(self, *, provider_name: str, model_name: str) -> None:
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name


def _build_test_config() -> AppConfig:
    return AppConfig(
        llm={
            "providers": {
                "openai": {
                    "enabled": True,
                    "provider_type": LLMProvider.OPENAI,
                    "display_name": "OpenAI",
                    "api_key": "sk-openai",
                    "base_url": "https://api.openai.com/v1",
                },
                "anthropic": {
                    "enabled": True,
                    "provider_type": LLMProvider.ANTHROPIC,
                    "display_name": "Anthropic",
                    "api_key": "sk-anthropic",
                    "base_url": "https://api.anthropic.com/v1",
                },
            },
            "selections": {
                "context_decider": {
                    "provider_id": "openai",
                    "model": "gpt-5-mini",
                },
                "core": {
                    "provider_id": "anthropic",
                    "model": "claude-sonnet-4-6",
                },
            },
        }
    )


def test_scenario_llm_pool_returns_distinct_adapters_for_distinct_scenarios():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[tuple[str, str]] = []

    def adapter_factory(*, provider_type: str, api_key: str, model: str, base_url: str | None, timeout: int) -> DummyAdapter:
        created.append((provider_type, model))
        return DummyAdapter(provider_name=provider_type, model_name=model)

    pool = ScenarioLLMPool(config=_build_test_config(), adapter_factory=adapter_factory)

    context_llm = pool.get(LLMScenario.CONTEXT_DECIDER)
    core_llm = pool.get(LLMScenario.CORE)

    assert context_llm.model_name == "gpt-5-mini"
    assert core_llm.model_name == "claude-sonnet-4-6"
    assert created == [("openai", "gpt-5-mini"), ("anthropic", "claude-sonnet-4-6")]


def test_scenario_llm_pool_rejects_disabled_provider_reference():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    config.llm.providers["anthropic"].enabled = False

    pool = ScenarioLLMPool(
        config=config,
        adapter_factory=lambda **kwargs: DummyAdapter(
            provider_name=str(kwargs["provider_type"]),
            model_name=str(kwargs["model"]),
        ),
    )

    try:
        pool.get(LLMScenario.CORE)
    except ValueError as exc:
        assert "disabled provider" in str(exc)
    else:
        raise AssertionError("Expected ScenarioLLMPool to reject disabled provider references")


def test_scenario_llm_pool_refresh_rebuilds_cached_adapter():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[str] = []

    def adapter_factory(*, provider_type: str, api_key: str, model: str, base_url: str | None, timeout: int) -> DummyAdapter:
        created.append(model)
        return DummyAdapter(provider_name=provider_type, model_name=model)

    config = _build_test_config()
    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    first = pool.get(LLMScenario.CORE)

    updated = _build_test_config()
    updated.llm.selections["core"].model = "claude-opus-4-6"
    pool.refresh(updated)
    second = pool.get(LLMScenario.CORE)

    assert first is not second
    assert second.model_name == "claude-opus-4-6"
    assert created == ["claude-sonnet-4-6", "claude-opus-4-6"]
