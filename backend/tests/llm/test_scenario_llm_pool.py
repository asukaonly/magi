from __future__ import annotations

from magi.config.models import AppConfig, LLMProvider


def _custom_provider(base_provider, *, display_name: str, base_url: str, api_key: str, models: list[str]):
    provider = base_provider.model_copy(deep=True)
    provider.provider_type = LLMProvider.CUSTOM
    provider.display_name = display_name
    provider.services.chat.base_url = base_url
    provider.services.chat.api_key = api_key
    provider.api_format = "openai"
    provider.custom_models = list(models)
    provider.custom_default_model = models[0]
    return provider


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
                    "services": {
                        "chat": {
                            "api_key": "sk-openai",
                            "base_url": "https://api.openai.com/v1",
                        },
                        "embedding": {
                            "api_key": "sk-openai",
                            "base_url": "https://api.openai.com/v1",
                        },
                    },
                },
                "anthropic": {
                    "enabled": True,
                    "provider_type": LLMProvider.ANTHROPIC,
                    "display_name": "Anthropic",
                    "services": {
                        "chat": {
                            "api_key": "sk-anthropic",
                            "base_url": "https://api.anthropic.com/v1",
                        },
                    },
                },
            },
            "selections": {
                "auxiliary": {
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


def _add_dashscope_coding_plan(config: AppConfig, plan_id: str = "codeplan") -> None:
    provider = config.llm.providers["openai"].model_copy(deep=True)
    provider.provider_type = LLMProvider.DASHSCOPE
    provider.display_name = "Alibaba Cloud Coding Plan"
    provider.provider_plan = plan_id
    provider.services.chat.api_key = "sk-sp-dashscope"
    provider.services.chat.base_url = "https://coding.dashscope.aliyuncs.com/v1"
    config.llm.providers["dashscope"] = provider
    config.llm.selections["core"].provider_id = "dashscope"
    config.llm.selections["core"].model = "qwen3.7-plus"
    config.llm.selections["auxiliary"].provider_id = "dashscope"
    config.llm.selections["auxiliary"].model = "qwen3.6-plus"


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

    context_llm = pool.get(LLMScenario.AUXILIARY)
    core_llm = pool.get(LLMScenario.CORE)

    assert context_llm.model_name == "gpt-5-mini"
    assert core_llm.model_name == "claude-sonnet-4-6"
    assert created == [("openai", "gpt-5-mini"), ("anthropic", "claude-sonnet-4-6")]


def test_scenario_llm_pool_projects_configured_tool_schema_limits():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    selection = config.llm.selections["core"]
    selection.capability_override_enabled = True
    selection.limits.max_tool_schemas = 12
    selection.limits.max_schema_tokens = 4096

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        return DummyAdapter(
            provider_name=str(kwargs["provider_type"]),
            model_name=str(kwargs["model"]),
        )

    resolved = ScenarioLLMPool(
        config=config,
        adapter_factory=adapter_factory,
    ).resolve(LLMScenario.CORE)

    assert resolved.context.max_tool_schemas == 12
    assert resolved.context.max_schema_tokens == 4096


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


def test_scenario_llm_pool_allows_interactive_scenarios_for_coding_plan() -> None:
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    _add_dashscope_coding_plan(config)
    created: list[dict[str, object]] = []

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    assert pool.get(LLMScenario.CORE).model_name == "qwen3.7-plus"
    assert pool.get(LLMScenario.AUXILIARY).model_name == "qwen3.6-plus"
    assert [item["provider_plan"] for item in created] == ["codeplan", "codeplan"]


def test_scenario_llm_pool_rejects_background_scenario_for_coding_plan() -> None:
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    _add_dashscope_coding_plan(config)
    pool = ScenarioLLMPool(
        config=config,
        adapter_factory=lambda **kwargs: DummyAdapter(
            provider_name=str(kwargs["provider_type"]),
            model_name=str(kwargs["model"]),
        ),
    )

    try:
        pool.get(LLMScenario.MEMORY_SUMMARIZER)
    except ValueError as exc:
        assert "does not allow scenario 'memory_summarizer'" in str(exc)
    else:
        raise AssertionError("Expected ScenarioLLMPool to reject background plan usage")


def test_scenario_llm_pool_rejects_unknown_provider_plan() -> None:
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    _add_dashscope_coding_plan(config, plan_id="unknown-plan")
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
        assert "Unknown LLM provider plan 'unknown-plan'" in str(exc)
    else:
        raise AssertionError("Expected ScenarioLLMPool to reject an unknown plan")


def test_scenario_llm_pool_resolves_adapter_and_context_profile_together():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    config = _build_test_config()
    selection = config.llm.selections["core"]
    selection.limits.context_window = 1_000_000
    selection.limits.max_output_tokens = 64_000

    pool = ScenarioLLMPool(
        config=config,
        adapter_factory=lambda **kwargs: DummyAdapter(
            provider_name=str(kwargs["provider_type"]),
            model_name=str(kwargs["model"]),
        ),
    )

    resolved = pool.resolve(LLMScenario.CORE)

    assert resolved.adapter.model_name == "claude-sonnet-4-6"
    assert resolved.context.provider_id == "anthropic"
    assert resolved.context.model_id == "claude-sonnet-4-6"
    assert resolved.context.context_window == 1_000_000
    assert resolved.context.max_output_tokens == 64_000


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
    """Custom OpenAI-compatible providers route through the OpenAI adapter,
    keeping ``custom`` as the adapter-level provider name. Vendor (and
    therefore reasoning dialect) is resolved later from
    ``ModelVendor`` declared on the resolved model meta — not from URL
    or display name during adapter construction."""
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_openai"] = _custom_provider(
        config.llm.providers["openai"],
        display_name="My Gateway",
        base_url="https://llm.example.com/v1",
        api_key="sk-custom",
        models=["gpt-4.1-mini"],
    )
    config.llm.selections["core"].provider_id = "custom_openai"
    config.llm.selections["core"].model = "gpt-4.1-mini"

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "custom"
    assert created == [
        {
            "provider_type": "custom",
            "api_key": "sk-custom",
            "model": "gpt-4.1-mini",
            "base_url": "https://llm.example.com/v1",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_builds_keyless_custom_openai_provider():
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_openai"] = _custom_provider(
        config.llm.providers["openai"],
        display_name="Local Gateway",
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        models=["local-model"],
    )
    config.llm.selections["core"].provider_id = "custom_openai"
    config.llm.selections["core"].model = "local-model"

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "custom"
    assert created == [
        {
            "provider_type": "custom",
            "api_key": "",
            "model": "local-model",
            "base_url": "http://127.0.0.1:11434/v1",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_keeps_custom_label_for_glm_compatible_gateway() -> None:
    """A custom gateway hosting GLM models still surfaces ``custom`` as the
    adapter provider name. The GLM dialect comes through later via the
    model's ``ModelVendor.GLM`` declaration / detection — not by renaming
    the provider here."""
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_glm"] = _custom_provider(
        config.llm.providers["openai"],
        display_name="Zai",
        base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        api_key="sk-custom-glm",
        models=["glm-5"],
    )
    config.llm.selections["core"].provider_id = "custom_glm"
    config.llm.selections["core"].model = "glm-5"

    def adapter_factory(**kwargs) -> DummyAdapter:  # type: ignore[no-untyped-def]
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "custom"
    assert created == [
        {
            "provider_type": "custom",
            "api_key": "sk-custom-glm",
            "model": "glm-5",
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_scenario_llm_pool_keeps_custom_label_for_dashscope_gateway() -> None:
    """Same as the GLM-compatible case for DashScope/Bailian gateways."""
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_dashscope"] = _custom_provider(
        config.llm.providers["openai"],
        display_name="Bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-custom-dashscope",
        models=["qwen-plus"],
    )
    config.llm.selections["core"].provider_id = "custom_dashscope"
    config.llm.selections["core"].model = "qwen-plus"

    def adapter_factory(**kwargs) -> DummyAdapter:
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "custom"
    assert created == [
        {
            "provider_type": "custom",
            "api_key": "sk-custom-dashscope",
            "model": "qwen-plus",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "timeout": 60,
            "embedding_dimension": None,
            "proxy_url": None,
        }
    ]


def test_custom_gateway_glm_model_keeps_custom_label() -> None:
    """A custom Bailian-hosted GLM model still surfaces ``custom`` as the
    adapter provider name. Vendor decision (DashScope vs GLM) lives in
    ProviderBridgeOptionsMixin and is exercised in test_provider_bridge."""
    from magi.llm.scenario_pool import LLMScenario, ScenarioLLMPool

    created: list[dict[str, object]] = []
    config = _build_test_config()
    config.llm.providers["custom_dashscope_glm"] = _custom_provider(
        config.llm.providers["openai"],
        display_name="Bailian",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-dashscope",
        models=["glm-4"],
    )
    config.llm.selections["core"].provider_id = "custom_dashscope_glm"
    config.llm.selections["core"].model = "glm-4"

    def adapter_factory(**kwargs) -> DummyAdapter:
        created.append(dict(kwargs))
        return DummyAdapter(provider_name=str(kwargs["provider_type"]), model_name=str(kwargs["model"]))

    pool = ScenarioLLMPool(config=config, adapter_factory=adapter_factory)

    core_llm = pool.get(LLMScenario.CORE)

    assert core_llm.provider_name == "custom"
