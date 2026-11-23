"""Verify shipped catalog references and runtime consumption, not vendor accuracy."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from magi.config.llm_registry import LLMProviderRegistryModel, load_llm_provider_registry
from magi.config.llm_registry_model_resolution import (
    resolve_provider_model_catalog,
    resolve_provider_plan_meta,
)
from magi.config.llm_registry_profile import resolve_llm_profile
from magi.config.models import (
    AppConfig,
    LLMProviderSettings,
    LLMSelectionSettings,
    LLMSettings,
    LLMScenario,
)
from magi.context.window_budget import build_context_window_budget, measure_context_window_usage
from magi.llm.scenario_pool import ScenarioLLMPool

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "configs" / "llm_providers.yaml"


def _load_registry():
    registry = load_llm_provider_registry(REGISTRY_PATH, fallback=LLMProviderRegistryModel())
    assert registry.providers
    return registry


@pytest.mark.parametrize("provider_id", [provider.id for provider in _load_registry().providers])
def test_shipped_defaults_resolve_into_model_limits_and_usable_budget(provider_id):
    registry = _load_registry()
    provider = next(item for item in registry.providers if item.id == provider_id)
    settings = LLMProviderSettings(
        provider_type=provider_id, api_key="test-key", base_url=provider.default_base_url
    )
    catalog = resolve_provider_model_catalog(registry, provider_id, settings)
    models = {model.id: model for model in catalog.chat_models}
    assert len(models) == len(catalog.chat_models)
    for scenario, model_id in [
        (LLMScenario.CORE, provider.default_model),
        (LLMScenario.AUXILIARY, provider.default_classify_model),
    ]:
        assert model_id in models
        metadata = models[model_id]
        assert metadata.limits.context_window > 0
        if metadata.limits.max_output_tokens is not None:
            assert 0 < metadata.limits.max_output_tokens < metadata.limits.context_window
        selection = LLMSelectionSettings(provider_id=provider_id, model=model_id)
        profile = resolve_llm_profile(selection, registry, settings)
        selection.capabilities = profile.capabilities
        selection.limits = profile.limits
        factory = MagicMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
        config = AppConfig(
            llm=LLMSettings(
                providers={provider_id: settings}, selections={"core": selection, scenario.value: selection}
            )
        )
        resolved = ScenarioLLMPool(config=config, adapter_factory=factory).resolve(scenario)
        assert resolved.adapter.model == model_id
        assert resolved.context.context_window == metadata.limits.context_window
        assert resolved.context.max_output_tokens == metadata.limits.max_output_tokens
        assert resolved.context.supports_images is metadata.capabilities.vision
        assert factory.call_args.kwargs["base_url"] == provider.default_base_url
        budget = build_context_window_budget(resolved.context)
        assert budget.uses_fallback is False
        assert budget.input_capacity + budget.output_reserve == metadata.limits.context_window
        assert 0 < budget.output_reserve <= (metadata.limits.max_output_tokens or 8192)
        assert (
            measure_context_window_usage(
                budget, "", observed_input_tokens=budget.compaction_trigger_tokens - 1
            ).requires_compaction
            is False
        )
        assert (
            measure_context_window_usage(
                budget, "", observed_input_tokens=budget.compaction_trigger_tokens
            ).requires_compaction
            is True
        )
        assert (
            measure_context_window_usage(
                budget, "", observed_input_tokens=budget.input_capacity + 1
            ).fits_input_capacity
            is False
        )

    for family in ("embedding_models", "image_generation_models"):
        source_models = {model.id: model for model in getattr(provider, family)}
        resolved_models = {model.id: model for model in getattr(catalog, family)}
        assert set(resolved_models) == set(source_models)
        for model_id, model in resolved_models.items():
            authored = source_models[model_id]
            if family == "embedding_models":
                assert model.capabilities.embedding is True
                assert model.dimensions == authored.dimensions
                assert all(dimension > 0 for dimension in model.dimensions)
            else:
                assert model.capabilities.image_output is True
                assert model.supported_sizes == authored.supported_sizes
                assert model.supported_qualities == authored.supported_qualities
                assert model.max_n == authored.max_n >= 1
                assert model.native_protocol == authored.native_protocol


@pytest.mark.parametrize(
    "provider_id,plan_id",
    [(provider.id, plan.id) for provider in _load_registry().providers for plan in provider.plans],
)
def test_subscription_plan_catalog_and_runtime_enforce_interactive_only_policy(
    monkeypatch, provider_id, plan_id
):
    registry = _load_registry()
    monkeypatch.setattr("magi.llm.scenario_pool._load_provider_registry", lambda: registry)
    provider = next(item for item in registry.providers if item.id == provider_id)
    plan = next(item for item in provider.plans if item.id == plan_id)
    effective = resolve_provider_plan_meta(provider, plan_id)
    settings = LLMProviderSettings(
        provider_type=provider_id,
        provider_plan=plan_id,
        api_key="test-plan-key",
        base_url=effective.default_base_url,
    )
    catalog = resolve_provider_model_catalog(registry, provider_id, settings)
    expected_models = plan.chat_models if plan.chat_models is not None else provider.chat_models
    assert {model.id for model in catalog.chat_models} == {model.id for model in expected_models}
    assert effective.default_model in {model.id for model in catalog.chat_models}
    assert effective.default_classify_model in {model.id for model in catalog.chat_models}
    # Subscription plans are product-restricted to interactive chat and compaction.
    allowed = {LLMScenario.CORE, LLMScenario.AUXILIARY, LLMScenario.CONTEXT_COMPACT}
    for scenario in LLMScenario:
        selection = LLMSelectionSettings(provider_id=provider_id, model=effective.default_model)
        config = AppConfig(
            llm=LLMSettings(
                providers={provider_id: settings}, selections={"core": selection, scenario.value: selection}
            )
        )
        factory = MagicMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
        pool = ScenarioLLMPool(config=config, adapter_factory=factory)
        if scenario in allowed:
            assert pool.get(scenario).model == effective.default_model
            assert factory.call_args.kwargs["provider_plan"] == plan_id
            assert factory.call_args.kwargs["base_url"] == effective.default_base_url
        else:
            with pytest.raises(ValueError, match="does not allow scenario"):
                pool.get(scenario)
            factory.assert_not_called()


def test_same_provider_accounts_resolve_distinct_credentials_and_cached_adapters():
    registry = _load_registry()
    provider = next(item for item in registry.providers if item.id == "openai")
    account_ids = ["openai-work", "openai-personal"]
    providers = {
        account: LLMProviderSettings(
            provider_type="openai",
            api_key=account + "-key",
            base_url="https://" + account + ".example/v1",
        )
        for account in account_ids
    }
    config = AppConfig(
        llm=LLMSettings(
            providers=providers,
            selections={
                scenario.value: LLMSelectionSettings(
                    provider_id=account, model=provider.default_model
                )
                for scenario, account in zip([LLMScenario.CORE, LLMScenario.AUXILIARY], account_ids)
            },
        )
    )
    factory = MagicMock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    pool = ScenarioLLMPool(config=config, adapter_factory=factory)
    core, auxiliary = pool.get(LLMScenario.CORE), pool.get(LLMScenario.AUXILIARY)
    assert core is not auxiliary
    assert pool.get(LLMScenario.CORE) is core
    assert pool.get(LLMScenario.AUXILIARY) is auxiliary
    assert [
        (call.kwargs["api_key"], call.kwargs["base_url"], call.kwargs["model"])
        for call in factory.call_args_list
    ] == [
        (account + "-key", "https://" + account + ".example/v1", provider.default_model)
        for account in account_ids
    ]
    assert [adapter._provider_instance_id for adapter in [core, auxiliary]] == account_ids


def test_current_catalog_has_live_defaults_and_provider_plan_boundaries():
    providers = {p.id: p for p in _load_registry().providers}
    expected = {
        "openai": "gpt-6.2-sol", "anthropic": "claude-sonnet-5-5", "glm": "glm-5.3",
        "gemini": "gemini-4-hydrogen", "grok": "grok-4.7", "deepseek": "deepseek-flash",
        "dashscope": "qwen3.7-plus", "kimi": "kimi-k3.1-pro", "minimax": "MiniMax-M3.1-Flash",
        "xiaomimimo": "mimo-v2.6-pro",
    }
    assert {id: provider.default_model for id, provider in providers.items()} == expected
    assert {m.id for m in providers["dashscope"].plans[0].chat_models} == {
        "qwen3.7-plus", "qwen3.6-plus", "kimi-k2.5", "glm-5", "MiniMax-M2.5", "qwen3.5-plus",
    }
    assert {m.id for m in providers["glm"].plans[0].chat_models} == {"glm-5.3", "glm-5.3-flash"}
    assert {m.id for m in providers["minimax"].plans[0].chat_models} == {"MiniMax-M3.1-Flash"}
    retired = {"mimo-v2.5", "mimo-v2.5-pro", "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"}
    for provider in providers.values():
        assert retired.isdisjoint(m.id for m in provider.chat_models)
        for plan in provider.plans:
            assert retired.isdisjoint(m.id for m in plan.chat_models or [])
    assert not any(m.id.startswith("imagen-") for m in providers["gemini"].image_generation_models)
    assert all(m.capabilities.vision for m in providers["xiaomimimo"].chat_models)
    assert providers["deepseek"].chat_models[0].capabilities.vision


def test_minimal_registry_keeps_all_default_references_resolvable():
    from magi.config.llm_registry_defaults import build_default_llm_provider_registry
    provider = build_default_llm_provider_registry().providers[0]
    models = {model.id for model in provider.chat_models}
    assert {provider.default_model, provider.default_classify_model} <= models
    assert provider.default_model == "gpt-6.2-sol"
    assert provider.image_generation_models[0].id == "gpt-image-2.6-sunburst"

def test_recommendations_preserve_metadata_and_scope_saved_selections():
    from magi.config.llm_registry import build_provider_catalog
    registry = _load_registry()
    entries = {e.id: e for e in build_provider_catalog(registry)}
    assert sum(len(e.resolved_chat_models) for e in entries.values()) == 26
    assert sum(len(e.resolved_embedding_models) for e in entries.values()) == 7
    assert sum(len(e.resolved_image_generation_models) for e in entries.values()) == 7
    for entry in entries.values():
        assert {m.id for m in entry.image_generation_models} == {m.id for m in entry.resolved_image_generation_models}
    assert {m.id for m in entries["dashscope"].plans[0].chat_models} == {"qwen3.7-plus"}
    assert entries["dashscope"].plans[0].default_classify_model == "qwen3.7-plus"
    tokenplan = next(plan for plan in entries["dashscope"].plans if plan.id == "tokenplan")
    assert tokenplan.default_base_url == "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    assert {m.id for m in tokenplan.chat_models} == {"qwen3.7-plus", "qwen3.8-flash", "qwen4-max"}
    assert all(m.cost.input_per_million_tokens is None for m in tokenplan.chat_models)
    assert all(e.default_model in {m.id for m in e.resolved_chat_models} for e in entries.values())
    for provider in registry.providers:
        ids = {m.id for models in (provider.chat_models, provider.embedding_models, provider.image_generation_models,
                                   provider.audio_generation_models) for m in models}
        assert set(provider.recommended_models or ()) <= ids
    assert "gpt-5.2" not in {m.id for m in entries["openai"].resolved_chat_models}
    saved = build_provider_catalog(registry, {"work": LLMProviderSettings(provider_type="openai")},
                                  selections={"core": LLMSelectionSettings(provider_id="work", model="gpt-5.2")})
    old = next(m for e in saved if e.id == "work" for m in e.resolved_chat_models if m.id == "gpt-5.2")
    assert old.cost.input_per_million_tokens == 1.75 and old.capabilities.tool_calling
    assert "gpt-5.2" not in {m.id for m in saved[0].resolved_chat_models}
