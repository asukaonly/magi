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
                "embedding": {
                    "provider_id": "openai",
                    "model": "text-embedding-3-small",
                    "embedding_dimension": 512,
                },
            },
        }
    )


def test_scenario_llm_pool_returns_distinct_adapters_for_distinct_scenarios():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[tuple[str, str]] = []

    def adapter_factory(
        *,
        provider_type: str,
        api_key: str,
        model: str,
        base_url: str | None,
        timeout: int,
        embedding_dimension: int | None = None,
        proxy_url: str | None = None,
    ) -> DummyAdapter:
        assert embedding_dimension is None
        created.append((provider_type, model))
        return DummyAdapter(provider_name=provider_type, model_name=model)

    pool = ScenarioLLMPool(config=_build_test_config(), adapter_factory=adapter_factory)

    context_llm = pool.get(LLMScenario.CONTEXT_DECIDER)
    core_llm = pool.get(LLMScenario.CORE)

    assert context_llm.model_name == "gpt-5-mini"
    assert core_llm.model_name == "claude-sonnet-4-6"
    assert created == [("openai", "gpt-5-mini"), ("anthropic", "claude-sonnet-4-6")]


def test_scenario_llm_pool_falls_back_to_core_for_memory_summarizer():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[tuple[str, str]] = []

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append((str(kwargs["provider_type"]), str(kwargs["model"])))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=_build_test_config(), adapter_factory=adapter_factory)

    memory_llm = pool.get(LLMScenario.MEMORY_SUMMARIZER)

    assert memory_llm.model_name == "claude-sonnet-4-6"
    assert created == [("anthropic", "claude-sonnet-4-6")]


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

    def adapter_factory(
        *,
        provider_type: str,
        api_key: str,
        model: str,
        base_url: str | None,
        timeout: int,
        embedding_dimension: int | None = None,
        proxy_url: str | None = None,
    ) -> DummyAdapter:
        assert embedding_dimension is None
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


def test_scenario_llm_pool_passes_embedding_dimension_for_embedding_scenario():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=_build_test_config(), adapter_factory=adapter_factory)

    embedding_llm = pool.get(LLMScenario.EMBEDDING)

    assert embedding_llm.model_name == "text-embedding-3-small"
    assert created == [
        {
            "provider_type": "openai",
            "api_key": "sk-openai",
            "model": "text-embedding-3-small",
            "base_url": "https://api.openai.com/v1",
            "timeout": 60,
            "embedding_dimension": 512,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_maps_custom_provider_to_runtime_api_format():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_openai"] = config.llm.providers["openai"].model_copy(
        update={
            "provider_type": LLMProvider.CUSTOM,
            "display_name": "My Gateway",
            "base_url": "https://llm.example.com/v1",
            "api_key": "sk-custom",
            "api_format": "openai",
            "custom_models": ["gpt-4.1-mini"],
            "custom_default_model": "gpt-4.1-mini",
        }
    )
    config.llm.selections["core"].provider_id = "custom_openai"
    config.llm.selections["core"].model = "gpt-4.1-mini"

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "openai"
    assert created == [
        {
            "provider_type": "openai",
            "api_key": "sk-custom",
            "model": "gpt-4.1-mini",
            "base_url": "https://llm.example.com/v1",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_detects_glm_compatible_custom_provider() -> None:
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_glm"] = config.llm.providers["openai"].model_copy(
        update={
            "provider_type": LLMProvider.CUSTOM,
            "display_name": "Zai",
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "api_key": "sk-custom-glm",
            "api_format": "openai",
            "custom_models": ["glm-5"],
            "custom_default_model": "glm-5",
        }
    )
    config.llm.selections["core"].provider_id = "custom_glm"
    config.llm.selections["core"].model = "glm-5"

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "glm"
    assert created == [
        {
            "provider_type": "glm",
            "api_key": "sk-custom-glm",
            "model": "glm-5",
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_detects_dashscope_custom_provider() -> None:
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_dashscope"] = config.llm.providers["openai"].model_copy(
        update={
            "provider_type": LLMProvider.CUSTOM,
            "display_name": "Bailian",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-custom-dashscope",
            "api_format": "openai",
            "custom_models": ["qwen-plus"],
            "custom_default_model": "qwen-plus",
        }
    )
    config.llm.selections["core"].provider_id = "custom_dashscope"
    config.llm.selections["core"].model = "qwen-plus"

    def adapter_factory(**kwargs) -> DummyAdapter:
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "dashscope"
    assert created == [
        {
            "provider_type": "dashscope",
            "api_key": "sk-custom-dashscope",
            "model": "qwen-plus",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_dashscope_provider_takes_priority_over_glm_model_name() -> None:
    """When Bailian proxies a GLM model, platform URL wins over model-name hint."""
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_dashscope_glm"] = config.llm.providers["openai"].model_copy(
        update={
            "provider_type": LLMProvider.CUSTOM,
            "display_name": "Bailian",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "sk-dashscope",
            "api_format": "openai",
            "custom_models": ["glm-4"],
            "custom_default_model": "glm-4",
        }
    )
    config.llm.selections["core"].provider_id = "custom_dashscope_glm"
    config.llm.selections["core"].model = "glm-4"

    def adapter_factory(**kwargs) -> DummyAdapter:
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "dashscope"
