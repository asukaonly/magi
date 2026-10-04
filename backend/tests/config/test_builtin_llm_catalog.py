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
        assert budget.output_reserve == (metadata.limits.max_output_tokens or 8192)
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
