"""Tests for config router extensions."""

import pytest

from magi.api.routers.config import (
    SystemConfigModel,
    _build_onboarding_template,
    _build_update_paths,
    _default_llm_provider_registry,
)
from magi.config.models import LLMSelectionSettings, LLMSettings
from magi.config.llm_registry import LLMProviderRegistryModel, resolve_llm_profile


def test_system_config_defaults_include_llm_provider_pool_and_selections():
    config = SystemConfigModel()

    assert hasattr(config.llm, "providers")
    assert hasattr(config.llm, "selections")
    assert "context_decider" in config.llm.selections
    assert "core" in config.llm.selections


def test_llm_settings_reject_duplicate_builtin_provider_types():
    with pytest.raises(ValueError):
        LLMSettings(
            providers={
                "openai": {"provider_type": "openai", "display_name": "OpenAI"},
                "openai_copy": {"provider_type": "openai", "display_name": "OpenAI Copy"},
            },
            selections={
                "context_decider": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
                "core": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
            },
        )


def test_llm_settings_require_context_decider_and_core_selections():
    with pytest.raises(ValueError):
        LLMSettings(
            selections={
                "context_decider": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
            }
        )


def test_build_update_paths_contains_new_sections():
    config = SystemConfigModel()
    updates = _build_update_paths(config)

    assert "llm.providers" in updates
    assert "llm.selections" in updates
    assert "preferences" in updates
    assert "memory_layers" in updates
    assert "tools.builtIn" in updates
    assert "tools.skills" in updates
    assert "agent.personality.name" in updates
    assert "timeline" in updates


def test_timeline_defaults_include_source_retention_and_edge_whitelists():
    config = SystemConfigModel()

    assert config.timeline.sources.chat.default_retention_mode == "analyze_only"
    assert config.timeline.sources.photo_library.default_retention_mode == "retain_raw"
    assert "LIKES" in config.timeline.sources.browser_history.edge_whitelist
    assert "DISLIKES" not in config.timeline.sources.browser_history.edge_whitelist


def test_onboarding_template_includes_timeline_defaults():
    template = _build_onboarding_template()

    assert template.timeline.sources.browser_history.fetch_page_content is False
    assert template.timeline.sources.manual_journal.default_retention_mode == "retain_raw"
    assert "openai" in template.llm.providers
    assert "core" in template.llm.selections


def test_build_update_paths_skip_masked_api_key():
    config = SystemConfigModel()
    config.llm.providers["openai"].api_key = "***"
    updates = _build_update_paths(config)
    assert updates["llm.providers"]["openai"].get("api_key") in (None, "")


def test_build_update_paths_rejects_selection_pointing_to_disabled_provider():
    config = SystemConfigModel()
    config.llm.providers["openai"].enabled = False

    with pytest.raises(ValueError):
        _build_update_paths(config)


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
    config.llm.selections["core"].provider_id = "glm"
    config.llm.selections["core"].model = "glm-5"
    config.llm.selections["core"].capabilities.vision = True
    config.llm.selections["core"].capability_override_enabled = False

    resolved = resolve_llm_profile(config.llm.selections["core"], registry)
    assert resolved.capabilities.vision is False
    assert resolved.limits.context_window == 204800

    config.llm.selections["core"].capability_override_enabled = True
    resolved = resolve_llm_profile(config.llm.selections["core"], registry)
    assert resolved.capabilities.vision is True


def test_onboarding_template_includes_model_capability_defaults():
    template = _build_onboarding_template()

    assert template.llm.selections["core"].capabilities.tool_calling is True
    assert template.llm.selections["core"].limits.max_output_tokens is not None
