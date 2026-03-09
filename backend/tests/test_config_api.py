"""Tests for config router extensions."""

from magi.api.routers.config import (
    SystemConfigModel,
    _build_onboarding_template,
    _build_update_paths,
    _default_llm_provider_registry,
)
from magi.config.llm_registry import LLMProviderRegistryModel, resolve_llm_profile


def test_build_update_paths_contains_new_sections():
    config = SystemConfigModel()
    updates = _build_update_paths(config)

    assert "preferences" in updates
    assert "memory_layers" in updates
    assert "tools.builtIn" in updates
    assert "tools.skills" in updates
    assert "agent.personality.name" in updates
    assert "llm.capability_override_enabled" in updates
    assert "llm.capabilities" in updates
    assert "llm.limits" in updates
    assert "llm.provider_options" in updates


def test_build_update_paths_skip_masked_api_key():
    config = SystemConfigModel()
    config.llm.api_key = "***"
    updates = _build_update_paths(config)
    assert "llm.api_key" not in updates


def test_default_registry_exposes_model_metadata():
    registry = _default_llm_provider_registry()

    assert registry.providers
    assert registry.providers[0].models
    assert registry.providers[0].models[0].capabilities.tool_calling is True
    assert registry.providers[0].models[0].limits.max_output_tokens is not None


def test_registry_supports_legacy_model_options_shape():
    registry = LLMProviderRegistryModel(
        providers=[
            {
                "id": "legacy",
                "model_options": ["legacy-model"],
            }
        ],
    )

    assert registry.providers[0].models[0].id == "legacy-model"
    assert registry.providers[0].models[0].capabilities.reasoning is True


def test_resolve_llm_profile_prefers_registry_defaults_until_override_enabled():
    registry = _default_llm_provider_registry()
    config = SystemConfigModel()
    config.llm.provider = "glm"
    config.llm.model = "glm-5"
    config.llm.capabilities.vision = True
    config.llm.capability_override_enabled = False

    resolved = resolve_llm_profile(config.llm, registry)
    assert resolved.capabilities.vision is False
    assert resolved.limits.context_window == 204800

    config.llm.capability_override_enabled = True
    resolved = resolve_llm_profile(config.llm, registry)
    assert resolved.capabilities.vision is True


def test_onboarding_template_includes_model_capability_defaults():
    template = _build_onboarding_template()

    assert template.llm.capabilities.tool_calling is True
    assert template.llm.limits.max_output_tokens is not None
