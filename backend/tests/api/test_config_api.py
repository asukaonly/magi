"""Tests for config router extensions."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.config import (
    LLMProviderConfigModel,
    LLMSelectionConfigModel,
    SystemConfigModel,
    _build_system_config,
    _build_onboarding_template,
    _build_update_paths,
    config_router,
)
from magi.api.services.llm_testing_service import _default_llm_provider_registry
from magi.api.routers.llm import llm_router
from magi.config.loader import get_config
from magi.config.models import (
    LLMCapabilityOverridesSettings,
    LLMConcurrencyOverrideSettings,
    LLMLimitsSettings,
    LLMLimitsOverrideSettings,
    LLMModelMetadataOverrideSettings,
    LLMProviderSettings,
    LLMSelectionSettings,
    LLMSettings,
)
from magi.config.llm_registry import (
    build_runtime_llm_defaults,
    resolve_provider_model_catalog,
    resolve_llm_profile,
)
from magi.i18n import language_context


def _provider_settings(
    provider_type: str = "openai",
    *,
    display_name: str = "OpenAI",
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
) -> LLMProviderSettings:
    provider = LLMProviderSettings(provider_type=provider_type, display_name=display_name)
    provider.api_key = api_key
    provider.base_url = base_url
    provider.services.chat.api_key = api_key
    provider.services.chat.base_url = base_url
    provider.services.embedding.api_key = api_key
    provider.services.embedding.base_url = base_url
    provider.services.image_generation.enabled = True
    provider.services.image_generation.api_key = api_key
    provider.services.image_generation.base_url = base_url
    return provider


def _provider_config_model(
    provider_type: str = "openai",
    *,
    display_name: str = "OpenAI",
    api_key: str = "sk-test",
    base_url: str = "https://api.openai.com/v1",
) -> LLMProviderConfigModel:
    return LLMProviderConfigModel(
        enabled=True,
        provider_type=provider_type,
        display_name=display_name,
        api_key=api_key,
        base_url=base_url,
        services={
            "chat": {"enabled": True, "api_key": api_key, "base_url": base_url},
            "embedding": {"enabled": True, "api_key": api_key, "base_url": base_url},
            "image_generation": {
                "enabled": True,
                "api_key": api_key,
                "base_url": base_url,
                "timeout": 180,
            },
        },
    )


def test_system_config_defaults_include_llm_provider_pool_and_selections():
    config = SystemConfigModel()

    assert hasattr(config.llm, "providers")
    assert hasattr(config.llm, "selections")
    assert "context_decider" in config.llm.selections
    assert "core" in config.llm.selections
    assert hasattr(config.llm, "model_runtime_overrides")
    assert config.llm.model_runtime_overrides == {}
    assert config.llm.providers == {}
    assert config.llm.selections["image_generation"].capabilities.image_output is True
    assert "max_concurrency" not in config.llm.selections["core"].limits.model_dump()


def test_runtime_llm_defaults_include_image_generation_settings():
    registry = _default_llm_provider_registry()
    defaults = build_runtime_llm_defaults(registry)

    assert defaults["providers"] == {}
    assert defaults["selections"]["image_generation"]["capabilities"]["image_output"] is True


def test_resolved_image_generation_models_include_capability_metadata():
    registry = _default_llm_provider_registry()
    resolved = resolve_provider_model_catalog(registry, "openai")
    image_model = next(
        model for model in resolved.image_generation_models if model.id == "gpt-image-1"
    )

    assert image_model.supported_sizes == ["1024x1024", "1536x1024", "1024x1536"]
    assert image_model.supported_qualities == ["auto", "high", "medium", "low"]
    assert image_model.max_n == 1
    assert image_model.native_protocol == "openai_images"


def test_system_config_defaults_include_memory_lifecycle_settings():
    config = SystemConfigModel()

    assert config.memory.db_path == "~/.magi/data/memory"
    assert config.memory.reranker.top_k == 8
    assert config.memory.reranker.cross_encoder.enabled is False
    assert config.memory.reranker.cross_encoder.managed_model_id is None
    assert config.memory.query_expansion.enabled is True
    assert config.memory.l0.enabled is True
    assert config.memory.l4.enabled is True
    assert config.memory.retention_days == 90
    assert config.memory.history_behavior == "delete"
    assert config.memory.l0.checkpoint_interval_seconds == 30
    assert config.memory.l2.batch_flush_interval_seconds == 60
    assert config.memory.l2.conflict_arbitration_enabled is True
    assert config.memory.l2.conflict_arbitration_min_confidence == 0.85
    assert config.memory.l3.temporal_llm_timeout_seconds == 3.0
    assert config.memory.l3.temporal_llm_min_event_count == 2
    assert config.memory.l1.vectors_enabled is True
    assert config.memory.l3.vectors_enabled is True
    assert "async_embeddings" not in config.memory.model_dump(mode="json")
    assert config.memory.embedding.mode == "remote"
    assert config.memory.embedding.local.model_source == "managed"
    assert config.memory.embedding.local.idle_timeout_seconds == 1800
    assert "backend" not in config.memory.embedding.model_dump(mode="json")


def test_system_config_defaults_include_close_to_tray_enabled_preference():
    config = SystemConfigModel()

    assert config.preferences.close_to_tray_enabled is True
    assert config.preferences.default_chat_workspace_path == "~/.magi/chat-workspace"


def test_build_system_config_loads_close_to_tray_enabled_preference_from_raw_yaml(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "magi.api.routers.config._read_raw_yaml",
        lambda: {"preferences": {"close_to_tray_enabled": False}},
    )

    config = _build_system_config()

    assert config.preferences.close_to_tray_enabled is False


def test_build_system_config_loads_default_chat_workspace_path_from_raw_yaml(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "magi.api.routers.config._read_raw_yaml",
        lambda: {"preferences": {"default_chat_workspace_path": "/Users/asuka/code/magi"}},
    )

    config = _build_system_config()

    assert config.preferences.default_chat_workspace_path == "/Users/asuka/code/magi"


def test_system_config_does_not_expose_internal_runtime_fields():
    config = SystemConfigModel()
    payload = config.model_dump(mode="json")

    assert "loop" not in payload
    assert "message_bus" not in payload
    assert "websocket" not in payload


def test_memory_config_rejects_l2_batch_flush_interval_below_minimum():
    with pytest.raises(ValueError):
        SystemConfigModel(memory={"l2": {"batch_flush_interval_seconds": 29}})


def test_memory_config_rejects_l2_conflict_arbitration_threshold_above_maximum():
    with pytest.raises(ValueError):
        SystemConfigModel(memory={"l2": {"conflict_arbitration_min_confidence": 1.1}})


def test_llm_settings_allow_multiple_instances_of_same_provider_type():
    settings = LLMSettings(
        providers={
            "openai_primary": {"provider_type": "openai", "display_name": "OpenAI"},
            "openai_image": {
                "provider_type": "openai",
                "display_name": "OpenAI Image",
            },
        },
        selections={
            "context_decider": LLMSelectionSettings(provider_id="openai_primary", model="gpt-5.2"),
            "core": LLMSelectionSettings(provider_id="openai_primary", model="gpt-5.2"),
        },
    )

    assert set(settings.providers) == {"openai_primary", "openai_image"}


def test_llm_settings_require_context_decider_and_core_selections():
    with pytest.raises(ValueError):
        LLMSettings(
            selections={
                "context_decider": LLMSelectionSettings(provider_id="openai", model="gpt-5.2"),
            }
        )


def test_llm_provider_settings_support_custom_model_fields():
    provider = LLMProviderSettings(
        provider_type="custom",
        display_name="Proxy",
        custom_models=["foo-1", "foo-2"],
        custom_default_model="foo-1",
    )

    assert provider.custom_models == ["foo-1", "foo-2"]
    assert provider.custom_default_model == "foo-1"


def test_llm_provider_settings_support_model_metadata_overrides():
    provider = LLMProviderSettings(
        provider_type="openai",
        display_name="OpenAI",
        model_metadata_overrides={
            "gpt-4o-mini": LLMModelMetadataOverrideSettings(
                label="GPT 4o Mini Custom",
                capabilities=LLMCapabilityOverridesSettings(vision=True),
                limits=LLMLimitsOverrideSettings(context_window=65536),
                hidden=True,
            )
        },
    )

    override = provider.model_metadata_overrides["gpt-4o-mini"]
    assert override.label == "GPT 4o Mini Custom"
    assert override.capabilities.vision is True
    assert override.limits.context_window == 65536
    assert override.hidden is True


def test_custom_provider_default_model_must_be_in_model_list():
    with pytest.raises(ValueError):
        LLMProviderSettings(
            provider_type="custom",
            display_name="Proxy",
            custom_models=["foo-1"],
            custom_default_model="foo-2",
        )


def test_build_update_paths_contains_new_sections():
    current = _build_system_config(mask_api_key=False)
    config = SystemConfigModel.model_validate(current.model_dump(mode="json"))
    config.memory.db_path = "/Users/asuka/.magi/data/custom-memories"
    config.memory.reranker.top_k = 12
    config.memory.reranker.cross_encoder.enabled = True
    config.memory.reranker.cross_encoder.managed_model_id = "bge-reranker-v2-m3"
    config.memory.query_expansion.enabled = False
    config.memory.l0.enabled = not current.memory.l0.enabled
    config.preferences.default_chat_workspace_path = "/Users/asuka/code/magi"
    config.memory.l2.batch_flush_interval_seconds = 90
    config.llm.model_runtime_overrides["openai::gpt-5.2::chat"] = LLMConcurrencyOverrideSettings(
        max_concurrency=7
    )
    config.memory.l2.conflict_arbitration_enabled = False
    config.memory.l2.conflict_arbitration_min_confidence = 0.9
    config.memory.l3.temporal_llm_timeout_seconds = 1.5
    config.memory.l3.temporal_llm_min_event_count = 3
    config.timeline.sources.photo_library.enabled = (
        not current.timeline.sources.photo_library.enabled
    )
    updates = _build_update_paths(config)

    assert updates["agent.memory.db_path"] == "/Users/asuka/.magi/data/custom-memories"
    assert updates["agent.memory.reranker.top_k"] == 12
    assert updates["agent.memory.reranker.cross_encoder.enabled"] is True
    assert updates["agent.memory.reranker.cross_encoder.managed_model_id"] == "bge-reranker-v2-m3"
    assert updates["agent.memory.query_expansion.enabled"] is False
    assert "agent.memory.l0.enabled" in updates
    assert updates["agent.memory.l0.enabled"] == config.memory.l0.enabled
    assert updates["agent.memory.l2.batch_flush_interval_seconds"] == 90
    assert updates["llm.model_runtime_overrides"]["openai::gpt-5.2::chat"]["max_concurrency"] == 7
    assert "max_concurrency" not in config.llm.selections["core"].limits.model_dump()
    assert updates["agent.memory.l2.conflict_arbitration_enabled"] is False
    assert updates["agent.memory.l2.conflict_arbitration_min_confidence"] == 0.9
    assert updates["agent.memory.l3.temporal_llm_timeout_seconds"] == 1.5
    assert updates["agent.memory.l3.temporal_llm_min_event_count"] == 3
    assert "timeline" in updates
    assert "enabled" not in updates["timeline"]
    assert "expert_mode_edge_override" not in updates["timeline"]
    assert (
        updates["timeline"]["sources"]["photo_library"]["enabled"]
        == config.timeline.sources.photo_library.enabled
    )
    assert updates["preferences"]["default_chat_workspace_path"] == "/Users/asuka/code/magi"
    assert "agent.memory.async_embeddings" not in updates
    assert "agent.memory.embedding.backend" not in updates
    assert "agent.memory.l4.enabled" not in updates
    assert "memory_layers" not in updates
    assert "tools.skills" not in updates
    assert "agent.personality.name" not in updates


def test_build_system_config_hides_internal_memory_vector_backend_settings():
    config = _build_system_config()
    payload = config.model_dump(mode="json")

    assert "async_embeddings" not in payload["memory"]
    assert "embedding" in payload["memory"]
    assert "backend" not in payload["memory"]["embedding"]


def test_build_update_paths_persists_model_metadata_overrides():
    current = _build_system_config(mask_api_key=False)
    config = SystemConfigModel.model_validate(current.model_dump(mode="json"))
    config.llm.providers["openai"] = _provider_config_model()
    config.llm.providers["openai"].model_metadata_overrides = {
        "gpt-4o-mini": LLMModelMetadataOverrideSettings(
            label="OpenAI Compact",
            capabilities=LLMCapabilityOverridesSettings(vision=True),
            limits=LLMLimitsOverrideSettings(max_output_tokens=4096),
        )
    }

    updates = _build_update_paths(config)

    assert (
        updates["llm.providers"]["openai"]["model_metadata_overrides"]["gpt-4o-mini"]["label"]
        == "OpenAI Compact"
    )
    assert (
        updates["llm.providers"]["openai"]["model_metadata_overrides"]["gpt-4o-mini"][
            "capabilities"
        ]["vision"]
        is True
    )
    assert (
        updates["llm.providers"]["openai"]["model_metadata_overrides"]["gpt-4o-mini"]["limits"][
            "max_output_tokens"
        ]
        == 4096
    )


def test_build_update_paths_prunes_empty_null_fields_from_model_metadata_overrides():
    current = _build_system_config(mask_api_key=False)
    config = SystemConfigModel.model_validate(current.model_dump(mode="json"))
    config.llm.providers["openai"] = _provider_config_model()
    config.llm.providers["openai"].model_metadata_overrides = {
        "gpt-5.2": LLMModelMetadataOverrideSettings(
            capabilities=LLMCapabilityOverridesSettings(vision=True),
        ),
        "gpt-empty": LLMModelMetadataOverrideSettings(),
    }

    updates = _build_update_paths(config)

    override_payload = updates["llm.providers"]["openai"]["model_metadata_overrides"]
    assert override_payload["gpt-5.2"] == {
        "capabilities": {
            "vision": True,
        }
    }
    assert "gpt-empty" not in override_payload


def test_timeline_defaults_include_source_retention_and_edge_whitelists():
    config = SystemConfigModel()

    assert "enabled" not in config.timeline.model_dump(mode="json")
    assert "expert_mode_edge_override" not in config.timeline.model_dump(mode="json")
    assert "browser_history" not in config.timeline.sources.model_dump(mode="json")
    assert "chat" not in config.timeline.sources.model_dump(mode="json")
    assert "manual_journal" not in config.timeline.sources.model_dump(mode="json")
    assert config.timeline.sources.photo_library.default_retention_mode == "analyze_only"
    assert "CAPTURED" in config.timeline.sources.photo_library.edge_whitelist
    assert "DISLIKES" not in config.timeline.sources.photo_library.edge_whitelist


def test_onboarding_template_includes_timeline_defaults():
    template = _build_onboarding_template()

    assert "browser_history" not in template.timeline.sources.model_dump(mode="json")
    assert template.timeline.sources.photo_library.fetch_page_content is False
    assert "manual_journal" not in template.timeline.sources.model_dump(mode="json")
    assert "core" in template.llm.selections


def test_build_update_paths_skip_masked_api_key():
    runtime_config = get_config()
    original_provider = runtime_config.llm.providers.get("openai")
    runtime_config.llm.providers["openai"] = _provider_settings(api_key="sk-openai")
    runtime_config.llm.providers["openai"].services.image_generation.api_key = "sk-image-openai"

    try:
        current = _build_system_config(mask_api_key=False)
        config = SystemConfigModel.model_validate(current.model_dump(mode="json"))
        config.llm.providers["openai"].display_name = "OpenAI Override"
        config.llm.providers["openai"].services.chat.api_key = "***"
        config.llm.providers["openai"].services.image_generation.api_key = "***"
        updates = _build_update_paths(config)
        assert (
            updates["llm.providers"]["openai"]["services"]["chat"].get("api_key")
            == current.llm.providers["openai"].services.chat.api_key
        )
        assert (
            updates["llm.providers"]["openai"]["services"]["image_generation"].get("api_key")
            == "sk-image-openai"
        )
    finally:
        if original_provider is None:
            runtime_config.llm.providers.pop("openai", None)
        else:
            runtime_config.llm.providers["openai"] = original_provider


def test_build_system_config_returns_real_llm_api_keys_by_default(
    monkeypatch: pytest.MonkeyPatch,
):
    runtime_config = get_config()
    original_provider = runtime_config.llm.providers.get("openai")
    runtime_config.llm.providers["openai"] = _provider_settings(api_key="sk-visible-openai")

    try:
        config = _build_system_config()
        assert config.llm.providers["openai"].services.chat.api_key == "sk-visible-openai"
    finally:
        if original_provider is None:
            runtime_config.llm.providers.pop("openai", None)
        else:
            runtime_config.llm.providers["openai"] = original_provider


def test_build_update_paths_applies_builtin_provider_defaults_before_save():
    config = SystemConfigModel()
    config.llm.providers = {
        "glm": _provider_config_model(
            provider_type="glm",
            display_name="",
            api_key="glm-key",
            base_url="",
        )
    }
    config.llm.selections["context_decider"] = LLMSelectionConfigModel(provider_id="glm", model="")
    config.llm.selections["core"] = LLMSelectionConfigModel(provider_id="glm", model="")
    config.llm.selections["embedding"] = LLMSelectionConfigModel(provider_id="glm", model="")

    updates = _build_update_paths(config)

    assert updates["llm.providers"]["glm"]["provider_type"] == "glm"
    assert updates["llm.providers"]["glm"]["display_name"] == "Z.ai"
    assert updates["llm.providers"]["glm"]["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert updates["llm.selections"]["context_decider"]["model"] == "glm-4.6"
    assert updates["llm.selections"]["core"]["model"] == "glm-5"
    assert updates["llm.selections"]["embedding"]["model"] == "embedding-3"
    assert updates["llm.selections"]["embedding"]["embedding_dimension"] == 1024


def test_build_update_paths_does_not_depend_on_legacy_llm_env_vars(
    monkeypatch: pytest.MonkeyPatch,
):
    config = SystemConfigModel()
    config.llm.providers["glm"] = _provider_config_model(
        provider_type="glm",
        display_name="Z.ai",
        api_key="glm-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )
    config.llm.selections["core"] = LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    updates = _build_update_paths(config)

    assert updates["llm.providers"]["glm"]["services"]["chat"]["api_key"] == "glm-key"
    assert "LLM_API_KEY" not in __import__("os").environ


def test_build_update_paths_rejects_selection_pointing_to_disabled_provider():
    config = SystemConfigModel()
    config.llm.providers["openai"] = _provider_config_model()
    config.llm.providers["openai"].enabled = False
    config.llm.selections["core"] = LLMSelectionConfigModel(provider_id="openai", model="gpt-5.2")

    with pytest.raises(ValueError):
        _build_update_paths(config)


def test_default_registry_exposes_model_metadata():
    registry = _default_llm_provider_registry()

    assert registry.providers
    assert registry.providers[0].chat_models
    assert registry.providers[0].chat_models[0].capabilities.tool_calling is True
    assert registry.providers[0].chat_models[0].limits.max_output_tokens is not None


def test_default_registry_exposes_embedding_concurrency_defaults():
    registry = _default_llm_provider_registry()

    assert registry.providers
    assert registry.providers[0].chat_models[0].limits.max_concurrency is not None
    assert registry.providers[0].embedding_models[0].limits.max_concurrency is not None


def test_default_registry_includes_extended_builtin_providers():
    registry = _default_llm_provider_registry()
    providers_by_id = {provider.id: provider for provider in registry.providers}

    assert {
        "openai",
        "anthropic",
        "glm",
        "gemini",
        "deepseek",
        "kimi",
        "minimax",
    } <= providers_by_id.keys()
    assert (
        providers_by_id["gemini"].default_base_url
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert providers_by_id["deepseek"].default_base_url == "https://api.deepseek.com"
    assert providers_by_id["kimi"].default_base_url == "https://api.moonshot.cn/v1"
    assert providers_by_id["minimax"].default_base_url == "https://api.minimaxi.com/v1"
    assert providers_by_id["glm"].default_classify_model == "glm-4.6"
    assert providers_by_id["openai"].embedding_models[0].dimensions[0] == 1536


def test_build_update_paths_assigns_embedding_dimension_from_registry_default():
    config = SystemConfigModel()
    config.llm.providers["openai"] = _provider_config_model()
    config.llm.selections["embedding"] = LLMSelectionConfigModel(
        provider_id="openai",
        model="text-embedding-3-small",
        embedding_dimension=None,
    )

    updates = _build_update_paths(config)

    assert updates["llm.selections"]["embedding"]["embedding_dimension"] == 1536


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


def test_resolve_llm_profile_applies_custom_provider_model_overrides():
    registry = _default_llm_provider_registry()
    selection = LLMSelectionSettings(
        provider_id="custom_proxy",
        model="foo-vision",
        capability_override_enabled=False,
    )
    provider = LLMProviderSettings(
        provider_type="custom",
        display_name="Proxy",
        custom_models=["foo-vision"],
        model_metadata_overrides={
            "foo-vision": LLMModelMetadataOverrideSettings(
                capabilities=LLMCapabilityOverridesSettings(vision=True),
            )
        },
    )

    resolved = resolve_llm_profile(selection, registry, provider_settings=provider)

    assert resolved.capabilities.vision is True


def test_resolve_provider_model_catalog_applies_builtin_and_manual_overrides():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="openai",
        display_name="OpenAI",
        custom_models=["acme-vision-embed"],
        model_metadata_overrides={
            "gpt-4o-mini": LLMModelMetadataOverrideSettings(
                label="Compact 4o",
                capabilities=LLMCapabilityOverridesSettings(vision=True),
                hidden=True,
            ),
            "acme-vision-embed": LLMModelMetadataOverrideSettings(
                label="Acme Vision Embed",
                capabilities=LLMCapabilityOverridesSettings(vision=True, embedding=True),
            ),
        },
    )

    resolved = resolve_provider_model_catalog(registry, "openai", provider)

    builtin_model = next(model for model in resolved.chat_models if model.id == "gpt-4o-mini")
    manual_chat_model = next(
        model for model in resolved.chat_models if model.id == "acme-vision-embed"
    )
    manual_embedding_model = next(
        model for model in resolved.embedding_models if model.id == "acme-vision-embed"
    )

    assert builtin_model.label == "Compact 4o"
    assert builtin_model.capabilities.vision is True
    assert builtin_model.hidden is True
    assert manual_chat_model.source == "manual"
    assert manual_chat_model.capabilities.vision is True
    assert manual_embedding_model.source == "manual"
    assert manual_embedding_model.capabilities.embedding is True


def test_resolve_provider_model_catalog_ignores_manual_image_generation_overrides():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="openai",
        display_name="OpenAI",
        model_metadata_overrides={
            "acme-image-1": LLMModelMetadataOverrideSettings(
                label="Acme Image 1",
                capabilities=LLMCapabilityOverridesSettings(image_output=True),
            ),
        },
    )

    resolved = resolve_provider_model_catalog(registry, "openai", provider)

    assert all(model.id != "acme-image-1" for model in resolved.image_generation_models)
    assert all(model.id != "acme-image-1" for model in resolved.chat_models)


def test_resolve_llm_profile_does_not_accept_manual_image_generation_models():
    registry = _default_llm_provider_registry()
    selection = LLMSelectionSettings(
        provider_id="openai",
        model="acme-image-1",
        capability_override_enabled=False,
    )
    provider = LLMProviderSettings(
        provider_type="openai",
        display_name="OpenAI",
        model_metadata_overrides={
            "acme-image-1": LLMModelMetadataOverrideSettings(
                capabilities=LLMCapabilityOverridesSettings(image_output=True),
            ),
        },
    )

    resolved = resolve_llm_profile(selection, registry, provider_settings=provider)

    assert resolved.capabilities.image_output is False
    assert resolved.capabilities.embedding is False


def test_onboarding_template_includes_model_capability_defaults():
    template = _build_onboarding_template()

    assert template.llm.selections["core"].capabilities.tool_calling is True
    assert template.llm.selections["core"].limits.max_output_tokens is None


def test_onboarding_template_endpoint_returns_config_only():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    response = client.get("/config/onboarding-template")

    assert response.status_code == 200
    payload = response.json()
    assert "config" in payload["data"]
    assert "llm_providers" not in payload["data"]


def test_onboarding_template_ignores_llm_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.setenv("LLM_MODEL", "glm-5")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example.com/v1")

    template = _build_onboarding_template()

    assert template.llm.providers == {}
    assert template.llm.selections["core"].provider_id == ""
    assert template.llm.selections["core"].model == ""


def test_runtime_llm_defaults_use_scenario_llm_structure():
    data = build_runtime_llm_defaults(_default_llm_provider_registry())

    assert "providers" in data
    assert "selections" in data
    assert "provider" not in data
    assert "model" not in data
    assert data["providers"] == {}
    assert data["selections"]["context_decider"]["provider_id"] == ""
    assert data["selections"]["context_decider"]["model"] == ""
    assert data["selections"]["core"]["provider_id"] == ""
    assert data["selections"]["core"]["model"] == ""
    assert "model_runtime_overrides" in data
    assert data["model_runtime_overrides"] == {}


def test_discover_llm_models_returns_models_from_provider_endpoint(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(llm_router, prefix="/llm")
    client = TestClient(app)

    async def _fake_discover(_: str, __: str | None, ___: str | None):
        return ["foo-1", "foo-2"]

    monkeypatch.setattr(
        "magi.api.routers.llm._discover_openai_compatible_models",
        _fake_discover,
    )

    with language_context("zh-CN"):
        response = client.post(
            "/llm/providers/discover-models",
            json={
                "provider_type": "custom",
                "base_url": "https://proxy.example.com/v1",
                "api_key": "sk-test",
                "api_format": "openai",
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "LLM 提供商模型已发现"
    assert response.json()["data"]["models"] == ["foo-1", "foo-2"]
    assert response.json()["data"]["default_model"] == "foo-1"


def test_discover_llm_models_returns_clear_error_for_unsupported_format():
    app = FastAPI()
    app.include_router(llm_router, prefix="/llm")
    client = TestClient(app)

    response = client.post(
        "/llm/providers/discover-models",
        json={
            "provider_type": "custom",
            "base_url": "https://proxy.example.com/v1",
            "api_key": "sk-test",
            "api_format": "custom",
        },
    )

    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]


def test_config_test_endpoint_accepts_new_llm_structure():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    response = client.post(
        "/config/test",
        json=SystemConfigModel().model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_config_test_endpoint_returns_localized_validation_message():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    payload = SystemConfigModel().model_dump(mode="json")
    payload["llm"]["selections"].pop("core")

    response = client.post(
        "/config/test",
        json=payload,
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["message"] == "必须配置 LLM 场景选择"


def test_config_update_validation_error_is_localized():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    payload = SystemConfigModel()
    payload.llm.providers["openai"] = _provider_config_model()
    payload.llm.providers["openai"].enabled = False
    payload.llm.selections["core"] = LLMSelectionConfigModel(provider_id="openai", model="gpt-5.2")

    response = client.put(
        "/config/",
        json=payload.model_dump(mode="json"),
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "LLM 选择“core”引用了已禁用的提供商“openai”"


def test_telegram_connection_invalid_token_returns_localized_detail():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    response = client.post(
        "/config/channels/telegram/test",
        json={"bot_token": "", "proxy": ""},
        headers={"Accept-Language": "zh-CN"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "需要有效的机器人令牌"


def test_llm_provider_test_endpoint_uses_request_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(llm_router, prefix="/llm")
    client = TestClient(app)

    captured: dict[str, object] = {}

    async def _fake_probe(provider_id: str, provider, model: str):  # type: ignore[no-untyped-def]
        captured["provider_id"] = provider_id
        captured["provider_type"] = provider.provider_type
        captured["api_key"] = provider.services.chat.api_key
        captured["base_url"] = provider.base_url
        captured["model"] = model
        return {"model": model, "latency_ms": 42, "preview": "hello"}

    monkeypatch.setattr(
        "magi.api.routers.llm._test_llm_provider_connection",
        _fake_probe,
        raising=False,
    )

    with language_context("en"):
        response = client.post(
            "/llm/providers/test",
            json={
                "provider_id": "openai",
                "model": "gpt-5.2",
                "provider": {
                    "enabled": True,
                    "provider_type": "openai",
                    "display_name": "OpenAI",
                    "services": {
                        "chat": {
                            "enabled": True,
                            "api_key": "sk-live",
                            "base_url": "https://api.openai.com/v1",
                        }
                    },
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "LLM provider connection succeeded"
    assert response.json()["data"]["model"] == "gpt-5.2"
    assert captured == {
        "provider_id": "openai",
        "provider_type": "openai",
        "api_key": "sk-live",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.2",
    }


def test_llm_provider_test_endpoint_inherits_provider_connection_defaults(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(llm_router, prefix="/llm")
    client = TestClient(app)

    captured: dict[str, object] = {}

    async def _fake_probe(provider_id: str, provider, model: str):  # type: ignore[no-untyped-def]
        captured["provider_id"] = provider_id
        captured["provider_type"] = provider.provider_type
        captured["provider_api_key"] = provider.api_key
        captured["provider_base_url"] = provider.base_url
        captured["chat_api_key"] = provider.services.chat.api_key
        captured["chat_base_url"] = provider.services.chat.base_url
        captured["model"] = model
        return {"model": model, "latency_ms": 42, "preview": "hello"}

    monkeypatch.setattr(
        "magi.api.routers.llm._test_llm_provider_connection",
        _fake_probe,
        raising=False,
    )

    response = client.post(
        "/llm/providers/test",
        json={
            "provider_id": "openai",
            "model": "gpt-5.2",
            "provider": {
                "enabled": True,
                "provider_type": "openai",
                "display_name": "OpenAI",
                "api_key": "sk-parent",
                "base_url": "https://api.openai.com/v1",
                "services": {
                    "chat": {
                        "enabled": True,
                        "api_key": "",
                        "base_url": "",
                    }
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured == {
        "provider_id": "openai",
        "provider_type": "openai",
        "provider_api_key": "sk-parent",
        "provider_base_url": "https://api.openai.com/v1",
        "chat_api_key": "sk-parent",
        "chat_base_url": "https://api.openai.com/v1",
        "model": "gpt-5.2",
    }


def test_llm_provider_test_endpoint_falls_back_to_registry_default_base_url(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(llm_router, prefix="/llm")
    client = TestClient(app)

    captured: dict[str, object] = {}

    async def _fake_probe(provider_id: str, provider, model: str):  # type: ignore[no-untyped-def]
        captured["provider_id"] = provider_id
        captured["provider_type"] = provider.provider_type
        captured["base_url"] = provider.base_url
        captured["model"] = model
        return {"model": model, "latency_ms": 12, "preview": "hello"}

    monkeypatch.setattr(
        "magi.api.routers.llm._test_llm_provider_connection",
        _fake_probe,
        raising=False,
    )

    response = client.post(
        "/llm/providers/test",
        json={
            "provider_id": "glm",
            "model": "glm-4.7-flash",
            "provider": {
                "enabled": True,
                "provider_type": "glm",
                "display_name": "GLM",
                "services": {
                    "chat": {
                        "enabled": True,
                        "api_key": "glm-key",
                        "base_url": "",
                    }
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured == {
        "provider_id": "glm",
        "provider_type": "glm",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.7-flash",
    }


def test_update_config_reloads_config_and_refreshes_runtime_llm_cache(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    calls: list[str] = []
    payload = SystemConfigModel()
    payload.llm.providers["glm"] = _provider_config_model(
        provider_type="glm",
        display_name="Z.ai",
        api_key="glm-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )
    payload.llm.selections["context_decider"] = LLMSelectionConfigModel(
        provider_id="glm",
        model="glm-4.6",
    )

    def _fake_save_config(_: dict) -> bool:
        calls.append("save")
        return True

    def _fake_reload_config():
        calls.append("reload")
        return get_config()

    def _fake_refresh_runtime_llm_config(config) -> None:  # type: ignore[no-untyped-def]
        assert config is get_config()
        calls.append("refresh")

    async def _fake_enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
        assert reason == "config_updated"
        calls.append("enqueue")

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", _fake_reload_config)
    monkeypatch.setattr(
        "magi.api.routers.config.refresh_runtime_llm_config",
        _fake_refresh_runtime_llm_config,
    )
    monkeypatch.setattr(
        "magi.api.routers.config._enqueue_runtime_llm_refresh_command",
        _fake_enqueue_runtime_llm_refresh_command,
    )

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh", "enqueue"]


def test_update_config_preserves_close_to_tray_enabled_preference_in_preferences_payload(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    captured_updates: dict[str, object] = {}

    def _fake_save_config(updates: dict) -> bool:
        captured_updates.update(updates)
        return True

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: get_config())
    monkeypatch.setattr("magi.api.routers.config.refresh_runtime_llm_config", lambda config: None)

    payload = SystemConfigModel().model_dump(mode="json")
    payload["preferences"]["close_to_tray_enabled"] = False

    response = client.put("/config/", json=payload)

    assert response.status_code == 200
    assert captured_updates["preferences"]["close_to_tray_enabled"] is False


def test_update_config_persists_changed_settings_and_returns_rebuilt_config(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    payload = SystemConfigModel()
    expected_updates = {
        "agent.memory.l0.enabled": False,
        "tools.web_fetch.default_provider": "browser",
    }
    captured_updates: dict[str, object] = {}

    def _fake_save_config(updates: dict) -> bool:
        captured_updates.update(updates)
        return True

    refreshed_config = object()
    returned_config = SystemConfigModel()
    returned_config.memory.l0.enabled = False
    returned_config.tools.builtIn.webFetch.usePlaywright = True

    monkeypatch.setattr(
        "magi.api.routers.config._build_update_paths", lambda config: expected_updates
    )
    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: refreshed_config)
    monkeypatch.setattr("magi.api.routers.config.refresh_runtime_llm_config", lambda config: None)
    monkeypatch.setattr(
        "magi.api.routers.config._build_system_config",
        lambda mask_api_key=False: returned_config,
    )

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert captured_updates == expected_updates
    assert response.json()["data"]["memory"]["l0"]["enabled"] is False
    assert response.json()["data"]["tools"]["builtIn"]["webFetch"]["usePlaywright"] is True


def test_complete_onboarding_reloads_config_and_refreshes_runtime_llm_cache(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    calls: list[str] = []
    payload = SystemConfigModel()

    def _fake_save_config(_: dict) -> bool:
        calls.append("save")
        return True

    def _fake_reload_config():
        calls.append("reload")
        return get_config()

    def _fake_refresh_runtime_llm_config(config) -> None:  # type: ignore[no-untyped-def]
        assert config is get_config()
        calls.append("refresh")

    async def _fake_enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
        assert reason == "onboarding_completed"
        calls.append("enqueue")

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", _fake_reload_config)
    monkeypatch.setattr(
        "magi.api.routers.config.refresh_runtime_llm_config",
        _fake_refresh_runtime_llm_config,
    )
    monkeypatch.setattr(
        "magi.api.routers.config._enqueue_runtime_llm_refresh_command",
        _fake_enqueue_runtime_llm_refresh_command,
    )
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: object())

    response = client.post("/config/onboarding-complete", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh", "enqueue"]


def test_complete_onboarding_quick_mode_uses_locale_seed_personality(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    payload = SystemConfigModel()
    payload.preferences.user_mode = "quick"
    payload.preferences.language = "zh"
    payload.personality.name = "Custom Persona"

    captured: dict[str, str] = {}

    def _capture_update_paths(config: SystemConfigModel) -> dict:
        captured["name"] = config.personality.name
        return {}

    monkeypatch.setattr("magi.api.routers.config._build_update_paths", _capture_update_paths)
    monkeypatch.setattr("magi.api.routers.config.save_config", lambda _: True)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: get_config())
    monkeypatch.setattr("magi.api.routers.config.refresh_runtime_llm_config", lambda _: None)
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: object())

    response = client.post("/config/onboarding-complete", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert captured["name"] == "Echo-01"


def test_complete_onboarding_quick_mode_uses_english_seed_without_zh_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    payload = SystemConfigModel()
    payload.preferences.user_mode = "quick"
    payload.preferences.language = "en"
    payload.personality.name = "Custom Persona"

    captured: dict[str, str] = {}

    def _capture_update_paths(config: SystemConfigModel) -> dict:
        captured["name"] = config.personality.name
        return {}

    monkeypatch.setattr("magi.api.routers.config._build_update_paths", _capture_update_paths)
    monkeypatch.setattr("magi.api.routers.config.save_config", lambda _: True)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: get_config())
    monkeypatch.setattr("magi.api.routers.config.refresh_runtime_llm_config", lambda _: None)
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: object())

    response = client.post("/config/onboarding-complete", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert captured["name"] == "Nova"
