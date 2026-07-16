"""Tests for config router extensions."""

import asyncio
from datetime import datetime, timezone

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import config as config_module
from magi.api.routers.config import (
    SystemConfigModel,
    _build_system_config,
    _build_onboarding_template,
    _build_update_paths,
    config_router,
)
from magi.api.routers.config_schemas import LLMProviderConfigModel, LLMSelectionConfigModel
from magi.api.services.llm_testing_service import _default_llm_provider_registry
from magi.api.routers.llm import llm_router
from magi.config.loader import get_config
from magi.config.models import (
    BackgroundTasksSettings,
    LLMCapabilityOverridesSettings,
    LLMConcurrencyOverrideSettings,
    LLMLimitsOverrideSettings,
    LLMModelMetadataOverrideSettings,
    LLMProviderSettings,
    LLMSelectionSettings,
    LLMSettings,
    ModelVendor,
)
from magi.config.memory_models import GraphSpreadingSettings, MemoryL1Settings
from magi.config.agent_models import BackgroundTasksSettings as AgentBackgroundTasksSettings
from magi.config.llm_registry import (
    build_provider_catalog,
    build_runtime_llm_defaults,
    resolve_provider_model_catalog,
    resolve_llm_profile,
)
from magi.llm.pricing import calculate_chat_cost
from magi.i18n import language_context
from magi.system_suggestions.contracts import DismissalKind, DismissalRecord


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


def _remote_embedding_config(
    *,
    model: str = "text-embedding-3-small",
    base_url: str = "https://api.openai.com/v1",
) -> SystemConfigModel:
    config = SystemConfigModel()
    config.memory.embedding.mode = "remote"
    config.llm.providers["embedding-provider"] = _provider_config_model(
        api_key="embedding-key",
        base_url=base_url,
    )
    config.llm.selections["embedding"] = LLMSelectionConfigModel(
        provider_id="embedding-provider",
        model=model,
        embedding_dimension=1536,
        provider_options={"encoding_format": "float"},
    )
    return config


def test_embedding_execution_signature_tracks_vector_inputs_but_not_secrets_or_idle_timeout():
    original = _remote_embedding_config()
    secret_only = original.model_copy(deep=True)
    provider = secret_only.llm.providers["embedding-provider"]
    provider.api_key = "rotated-provider-key"
    provider.services.embedding.api_key = "rotated-service-key"
    secret_only.memory.embedding.local.idle_timeout_seconds += 60

    assert config_module._embedding_execution_signature(
        original
    ) == config_module._embedding_execution_signature(secret_only)

    changed_provider = original.model_copy(deep=True)
    changed_provider.llm.providers[
        "embedding-provider"
    ].services.embedding.base_url = "https://embedding.example/v1"
    assert config_module._embedding_execution_signature(
        original
    ) != config_module._embedding_execution_signature(changed_provider)

    changed_options = original.model_copy(deep=True)
    changed_options.llm.selections["embedding"].provider_options = {"encoding_format": "base64"}
    assert config_module._embedding_execution_signature(
        original
    ) != config_module._embedding_execution_signature(changed_options)

    changed_layer = original.model_copy(deep=True)
    changed_layer.memory.l3.vectors_enabled = False
    assert config_module._embedding_execution_signature(
        original
    ) != config_module._embedding_execution_signature(changed_layer)

    local_original = SystemConfigModel()
    local_original.memory.embedding.mode = "local"
    local_original.memory.embedding.local.managed_model_id = "local-model"
    local_original.memory.embedding.local.variant = "fp16"

    local_idle_change = local_original.model_copy(deep=True)
    local_idle_change.memory.embedding.local.idle_timeout_seconds += 60
    assert config_module._embedding_execution_signature(
        local_original
    ) == config_module._embedding_execution_signature(local_idle_change)

    local_variant_change = local_original.model_copy(deep=True)
    local_variant_change.memory.embedding.local.variant = "int8"
    assert config_module._embedding_execution_signature(
        local_original
    ) != config_module._embedding_execution_signature(local_variant_change)


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
        model for model in resolved.image_generation_models if model.id == "gpt-image-2"
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
    assert config.memory.query_expansion.max_expansions == 2
    assert config.memory.graph_spreading.enabled is True
    assert config.memory.l0.enabled is True
    assert config.memory.l4.enabled is True
    assert config.memory.retention_days == 90
    assert config.memory.history_behavior == "delete"
    assert config.memory.archive_path == "~/.magi/data/memory/archive"
    assert config.memory.l0.checkpoint_interval_seconds == 30
    assert config.memory.l2.batch_flush_interval_seconds == 60
    assert config.memory.l2.conflict_arbitration_enabled is True
    assert config.memory.l2.conflict_arbitration_min_confidence == 0.85
    assert config.memory.l2.shadow_conflict_notification_enabled is True
    assert config.memory.l2.portrait_projection_refresh_delay_seconds == 120
    assert config.memory.l1.retention_days == 30
    assert config.memory.l3.temporal_llm_timeout_seconds == 3.0
    assert config.memory.l3.temporal_llm_min_event_count == 2
    assert config.memory.l3.retention_days == 180
    assert config.memory.l4.inactive_skill_retention_days == 30
    assert config.memory.l4.inactive_skill_min_attempts == 5
    assert config.memory.l1.vectors_enabled is True
    assert config.memory.l3.vectors_enabled is True
    assert "async_embeddings" not in config.memory.model_dump(mode="json")
    assert config.memory.embedding.mode == "remote"
    assert config.memory.embedding.local.model_source == "managed"
    assert config.memory.embedding.local.idle_timeout_seconds == 1800
    assert config.memory.embedding.local.variant is None
    assert "backend" not in config.memory.embedding.model_dump(mode="json")
    assert MemoryL1Settings().retention_days == 30
    assert GraphSpreadingSettings().enabled is True


def test_system_config_defaults_include_close_to_tray_enabled_preference():
    config = SystemConfigModel()

    assert config.preferences.close_to_tray_enabled is True
    assert config.preferences.desktop_notifications_enabled is True
    assert config.preferences.desktop_notification_previews_enabled is True
    assert config.preferences.allow_media_grounding_for_conversation is True
    assert config.preferences.default_chat_workspace_path == "~/.magi/chat-workspace"


def test_background_auto_dispatch_defaults_off():
    config = SystemConfigModel()

    assert config.agent.background_tasks.auto_detect_long_task is False
    assert BackgroundTasksSettings().auto_detect_long_task is False
    assert AgentBackgroundTasksSettings().auto_detect_long_task is False


def test_build_update_paths_includes_background_auto_dispatch_setting(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "magi.api.routers.config._build_system_config",
        lambda mask_api_key=False: SystemConfigModel(),
    )
    config = SystemConfigModel(agent={"background_tasks": {"auto_detect_long_task": True}})

    updates = _build_update_paths(config)

    assert updates["agent.background_tasks.auto_detect_long_task"] is True


def test_build_update_paths_keeps_preferences_yaml_safe_with_dismissals(
    monkeypatch: pytest.MonkeyPatch,
):
    """Preferences must serialize to YAML even when a dismissal record is present.

    Regression: ``suggestion_dismissals`` is typed ``dict[str, DismissalRecord]``,
    so a full-config save round-trips the on-disk string ``"explicit"`` back into
    a ``DismissalKind`` enum. ``_build_update_paths`` dumped preferences with
    ``model_dump(exclude_none=True)`` (python mode), leaving the enum/datetime as
    native objects that ``yaml.safe_dump`` cannot represent — which truncated
    agent.yaml mid-write. The dump must be JSON-mode so values are plain scalars.
    """
    monkeypatch.setattr(
        "magi.api.routers.config._build_system_config",
        lambda mask_api_key=False: SystemConfigModel(),
    )
    config = SystemConfigModel()
    config.preferences.suggestion_dismissals = {
        "demo.suggestion": DismissalRecord(
            dedupe_key="demo.suggestion",
            dismissed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            kind=DismissalKind.EXPLICIT,
        )
    }

    updates = _build_update_paths(config)

    # The exact operation that corrupted agent.yaml in production.
    yaml.safe_dump(updates["preferences"], allow_unicode=True, sort_keys=False)
    dumped = updates["preferences"]["suggestion_dismissals"]["demo.suggestion"]
    assert type(dumped["kind"]) is str
    assert dumped["kind"] == "explicit"


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
        lambda: {"preferences": {"default_chat_workspace_path": "/tmp/magi"}},
    )

    config = _build_system_config()

    assert config.preferences.default_chat_workspace_path == "/tmp/magi"


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
    config.memory.db_path = "/tmp/magi-data/custom-memories"
    config.memory.archive_path = "/tmp/magi-data/custom-archive"
    config.memory.reranker.top_k = 12
    config.memory.reranker.cross_encoder.enabled = True
    config.memory.reranker.cross_encoder.managed_model_id = "bge-reranker-v2-m3"
    config.memory.embedding.local.variant = "test-variant"
    config.memory.query_expansion.enabled = False
    config.memory.query_expansion.max_expansions = 3
    config.memory.graph_spreading.enabled = not current.memory.graph_spreading.enabled
    config.memory.l0.enabled = not current.memory.l0.enabled
    config.preferences.default_chat_workspace_path = "/tmp/magi"
    config.memory.l1.retention_days = 14
    config.memory.l2.batch_flush_interval_seconds = 90
    config.memory.l2.vectors_enabled = not current.memory.l2.vectors_enabled
    config.llm.model_runtime_overrides["openai::gpt-5.2::chat"] = LLMConcurrencyOverrideSettings(
        max_concurrency=7
    )
    config.memory.l2.conflict_arbitration_enabled = False
    config.memory.l2.conflict_arbitration_min_confidence = 0.9
    config.memory.l2.shadow_conflict_notification_enabled = False
    config.memory.l2.portrait_projection_refresh_delay_seconds = 45
    config.memory.l3.retention_days = 210
    config.memory.l4.inactive_skill_retention_days = 45
    config.memory.l4.inactive_skill_min_attempts = 9
    config.memory.l3.temporal_llm_timeout_seconds = 1.5
    config.memory.l3.temporal_llm_min_event_count = 3
    config.timeline.sources.photo_library.enabled = (
        not current.timeline.sources.photo_library.enabled
    )
    updates = _build_update_paths(config)

    assert updates["agent.memory.db_path"] == "/tmp/magi-data/custom-memories"
    assert updates["agent.memory.archive_path"] == "/tmp/magi-data/custom-archive"
    assert updates["agent.memory.reranker.top_k"] == 12
    assert updates["agent.memory.reranker.cross_encoder.enabled"] is True
    assert updates["agent.memory.reranker.cross_encoder.managed_model_id"] == "bge-reranker-v2-m3"
    assert updates["agent.memory.embedding.local.variant"] == "test-variant"
    assert updates["agent.memory.query_expansion.enabled"] is False
    assert updates["agent.memory.query_expansion.max_expansions"] == 3
    assert updates["agent.memory.graph_spreading.enabled"] is config.memory.graph_spreading.enabled
    assert "agent.memory.l0.enabled" in updates
    assert updates["agent.memory.l0.enabled"] == config.memory.l0.enabled
    assert updates["agent.memory.l1.retention_days"] == 14
    assert updates["agent.memory.l2.batch_flush_interval_seconds"] == 90
    assert updates["agent.memory.l2.vectors_enabled"] == config.memory.l2.vectors_enabled
    assert updates["llm.model_runtime_overrides"]["openai::gpt-5.2::chat"]["max_concurrency"] == 7
    assert "max_concurrency" not in config.llm.selections["core"].limits.model_dump()
    assert updates["agent.memory.l2.conflict_arbitration_enabled"] is False
    assert updates["agent.memory.l2.conflict_arbitration_min_confidence"] == 0.9
    assert updates["agent.memory.l2.shadow_conflict_notification_enabled"] is False
    assert updates["agent.memory.l2.portrait_projection_refresh_delay_seconds"] == 45
    assert updates["agent.memory.l3.retention_days"] == 210
    assert updates["agent.memory.l4.inactive_skill_retention_days"] == 45
    assert updates["agent.memory.l4.inactive_skill_min_attempts"] == 9
    assert updates["agent.memory.l3.temporal_llm_timeout_seconds"] == 1.5
    assert updates["agent.memory.l3.temporal_llm_min_event_count"] == 3
    assert "timeline" in updates
    assert "enabled" not in updates["timeline"]
    assert "expert_mode_edge_override" not in updates["timeline"]
    assert (
        updates["timeline"]["sources"]["photo_library"]["enabled"]
        == config.timeline.sources.photo_library.enabled
    )
    assert updates["preferences"]["default_chat_workspace_path"] == "/tmp/magi"
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
    assert updates["llm.selections"]["context_decider"]["model"] == "glm-4.7-flash"
    assert updates["llm.selections"]["core"]["model"] == "glm-5.2"
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


def test_default_registry_does_not_claim_provider_concurrency_limits():
    registry = _default_llm_provider_registry()

    assert registry.providers
    assert "max_concurrency" not in registry.providers[0].chat_models[0].limits.model_dump()
    assert "max_concurrency" not in registry.providers[0].embedding_models[0].limits.model_dump()


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
    assert providers_by_id["glm"].default_classify_model == "glm-4.7-flash"
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


def test_resolve_provider_model_catalog_applies_provider_plan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="glm",
        display_name="Z.ai",
        provider_plan="codeplan",
    )

    resolved = resolve_provider_model_catalog(registry, "glm", provider)

    assert [model.id for model in resolved.chat_models] == [
        "glm-5.2",
        "glm-5-turbo",
        "glm-4.7",
    ]
    assert resolved.embedding_models == []
    assert resolved.image_generation_models == []


def test_build_provider_catalog_exposes_and_applies_provider_plan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="glm",
        display_name="Z.ai",
        provider_plan="codeplan",
    )

    catalog = build_provider_catalog(registry, {"glm": provider})
    glm_entry = next(entry for entry in catalog if entry.id == "glm")

    assert glm_entry.provider_plan == "codeplan"
    assert [plan.id for plan in glm_entry.plans] == ["codeplan"]
    assert [endpoint.label for endpoint in glm_entry.plans[0].endpoints] == ["China", "Global"]
    assert glm_entry.plans[0].endpoints[1].base_url == "https://api.z.ai/api/coding/paas/v4"
    assert glm_entry.default_base_url == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert glm_entry.default_model == "glm-5.2"
    assert glm_entry.default_classify_model == "glm-4.7"
    assert [model.id for model in glm_entry.resolved_embedding_models] == []


def test_resolve_provider_model_catalog_applies_dashscope_codeplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="dashscope",
        display_name="Alibaba Cloud Model Studio",
        provider_plan="codeplan",
    )

    resolved = resolve_provider_model_catalog(registry, "dashscope", provider)

    assert [model.id for model in resolved.chat_models] == [
        "qwen3.7-plus",
        "qwen3.6-plus",
        "kimi-k2.5",
        "glm-5",
        "MiniMax-M2.5",
        "qwen3.5-plus",
        "qwen3-max-2026-01-23",
        "qwen3-coder-next",
        "qwen3-coder-plus",
        "glm-4.7",
    ]
    assert resolved.embedding_models == []
    assert resolved.image_generation_models == []

    models_by_id = {model.id: model for model in resolved.chat_models}
    assert models_by_id["qwen3.7-plus"].vendor == ModelVendor.DASHSCOPE
    assert models_by_id["kimi-k2.5"].vendor == ModelVendor.KIMI
    assert models_by_id["glm-5"].vendor == ModelVendor.GLM
    assert models_by_id["MiniMax-M2.5"].vendor == ModelVendor.MINIMAX
    assert models_by_id["qwen3.7-plus"].cost is not None
    assert models_by_id["qwen3.7-plus"].cost.input_per_million_tokens is None


def test_build_provider_catalog_exposes_and_applies_dashscope_codeplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="dashscope",
        display_name="Alibaba Cloud Model Studio",
        provider_plan="codeplan",
    )

    catalog = build_provider_catalog(registry, {"dashscope": provider})
    dashscope_entry = next(entry for entry in catalog if entry.id == "dashscope")

    assert dashscope_entry.provider_plan == "codeplan"
    assert [plan.id for plan in dashscope_entry.plans] == ["codeplan"]
    assert [endpoint.label for endpoint in dashscope_entry.plans[0].endpoints] == [
        "China",
        "Global",
    ]
    assert (
        dashscope_entry.plans[0].endpoints[1].base_url
        == "https://coding-intl.dashscope.aliyuncs.com/v1"
    )
    assert dashscope_entry.default_base_url == "https://coding.dashscope.aliyuncs.com/v1"
    assert dashscope_entry.default_model == "qwen3.7-plus"
    assert dashscope_entry.default_classify_model == "qwen3.6-plus"
    assert [model.id for model in dashscope_entry.resolved_embedding_models] == []
    assert [model.id for model in dashscope_entry.resolved_image_generation_models] == []


def test_resolve_provider_model_catalog_applies_minimax_tokenplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="minimax",
        display_name="MiniMax",
        provider_plan="tokenplan",
    )

    resolved = resolve_provider_model_catalog(registry, "minimax", provider)

    assert [model.id for model in resolved.chat_models] == [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
    ]
    assert resolved.embedding_models == []
    assert resolved.image_generation_models == []

    m27 = resolved.chat_models[0]
    assert m27.vendor == ModelVendor.MINIMAX
    assert m27.cost is not None
    assert m27.cost.input_per_million_tokens is None


def test_build_provider_catalog_exposes_and_applies_minimax_tokenplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="minimax",
        display_name="MiniMax",
        provider_plan="tokenplan",
    )

    catalog = build_provider_catalog(registry, {"minimax": provider})
    minimax_entry = next(entry for entry in catalog if entry.id == "minimax")

    assert minimax_entry.provider_plan == "tokenplan"
    assert [plan.id for plan in minimax_entry.plans] == ["tokenplan"]
    assert [endpoint.label for endpoint in minimax_entry.plans[0].endpoints] == [
        "China",
        "Global",
    ]
    assert minimax_entry.plans[0].endpoints[1].base_url == "https://api.minimax.io/v1"
    assert minimax_entry.default_base_url == "https://api.minimaxi.com/v1"
    assert minimax_entry.default_model == "MiniMax-M2.7"
    assert minimax_entry.default_classify_model == "MiniMax-M2.7"
    assert [model.id for model in minimax_entry.resolved_embedding_models] == []
    assert [model.id for model in minimax_entry.resolved_image_generation_models] == []


def test_resolve_provider_model_catalog_applies_xiaomi_tokenplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="xiaomimimo",
        display_name="Xiaomi MiMo",
        provider_plan="tokenplan",
    )

    resolved = resolve_provider_model_catalog(registry, "xiaomimimo", provider)

    assert [model.id for model in resolved.chat_models] == [
        "mimo-v2.5-pro",
        "mimo-v2.5",
    ]
    assert resolved.embedding_models == []
    assert resolved.image_generation_models == []
    assert resolved.chat_models[0].cost is not None
    assert resolved.chat_models[0].cost.input_per_million_tokens is None


def test_build_provider_catalog_exposes_and_applies_xiaomi_tokenplan():
    registry = _default_llm_provider_registry()
    provider = LLMProviderSettings(
        provider_type="xiaomimimo",
        display_name="Xiaomi MiMo",
        provider_plan="tokenplan",
    )

    catalog = build_provider_catalog(registry, {"xiaomimimo": provider})
    xiaomi_entry = next(entry for entry in catalog if entry.id == "xiaomimimo")

    assert xiaomi_entry.provider_plan == "tokenplan"
    assert [plan.id for plan in xiaomi_entry.plans] == ["tokenplan"]
    assert [endpoint.label for endpoint in xiaomi_entry.plans[0].endpoints] == [
        "China",
        "Singapore",
        "Europe",
    ]
    assert xiaomi_entry.plans[0].endpoints[2].base_url == "https://token-plan-ams.xiaomimimo.com/v1"
    assert xiaomi_entry.default_base_url == "https://token-plan-cn.xiaomimimo.com/v1"
    assert xiaomi_entry.default_model == "mimo-v2.5-pro"
    assert xiaomi_entry.default_classify_model == "mimo-v2.5"
    assert [model.id for model in xiaomi_entry.resolved_embedding_models] == []
    assert [model.id for model in xiaomi_entry.resolved_image_generation_models] == []


def test_update_paths_apply_provider_plan_defaults():
    config = SystemConfigModel()
    config.llm.providers = {
        "glm": LLMProviderConfigModel(
            provider_type="glm",
            display_name="Z.ai",
            provider_plan="codeplan",
            api_key="sk-glm",
            base_url="",
        )
    }
    config.llm.selections["context_decider"] = LLMSelectionConfigModel(
        provider_id="glm",
        model="",
    )
    config.llm.selections["core"] = LLMSelectionConfigModel(
        provider_id="glm",
        model="",
    )

    updates = _build_update_paths(config)

    persisted_provider = updates["llm.providers"]["glm"]
    assert persisted_provider["provider_type"] == "glm"
    assert persisted_provider["provider_plan"] == "codeplan"
    assert persisted_provider["base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert updates["llm.selections"]["context_decider"]["model"] == "glm-4.7"
    assert updates["llm.selections"]["core"]["model"] == "glm-5.2"


def test_provider_plan_pricing_does_not_inherit_pay_as_you_go_rates():
    registry = _default_llm_provider_registry()

    standard_amount, _ = calculate_chat_cost(
        provider="glm",
        model="glm-5.2",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        registry=registry,
    )
    plan_amount, currency = calculate_chat_cost(
        provider="glm",
        provider_plan="codeplan",
        model="glm-5.2",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        registry=registry,
    )

    assert standard_amount == pytest.approx(5.8)
    assert plan_amount is None
    assert currency is None


def test_dashscope_codeplan_pricing_does_not_apply_pay_as_you_go_rates():
    registry = _default_llm_provider_registry()

    amount, currency = calculate_chat_cost(
        provider="dashscope",
        provider_plan="codeplan",
        model="qwen3.7-plus",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        registry=registry,
    )

    assert amount is None
    assert currency is None


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("minimax", "MiniMax-M3"),
        ("xiaomimimo", "mimo-v2.5-pro"),
    ],
)
def test_tokenplan_pricing_does_not_apply_pay_as_you_go_rates(provider, model):
    registry = _default_llm_provider_registry()

    amount, currency = calculate_chat_cost(
        provider=provider,
        provider_plan="tokenplan",
        model=model,
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        registry=registry,
    )

    assert amount is None
    assert currency is None


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


def test_onboarding_template_endpoint_returns_config_only(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    monkeypatch.setattr("magi.api.routers.config._read_onboarding_completed", lambda: False)

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

    with language_context("en"):
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
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", lambda: object())

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh", "enqueue"]


def test_embedding_config_change_waits_for_rebuild_cancel_before_save_and_resumes_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    calls: list[str] = []
    current = _remote_embedding_config(model="text-embedding-3-small")
    proposed = _remote_embedding_config(model="text-embedding-3-large")

    class RebuildManager:
        async def pause_starts_and_cancel_all(self) -> int:
            calls.append("pause")
            return 1

        async def resume_starts(self) -> None:
            calls.append("resume")

    async def refresh(_config, *, reason: str) -> None:  # type: ignore[no-untyped-def]
        assert reason == "config_updated"
        calls.append("refresh")

    monkeypatch.setattr(config_module, "get_config", lambda: current)
    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(config_module, "_build_update_paths", lambda _config: {})
    monkeypatch.setattr(config_module, "_build_full_update_paths", lambda _config: {})
    monkeypatch.setattr(
        config_module,
        "_get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda _updates: calls.append("save") or True,
    )
    monkeypatch.setattr(
        config_module,
        "reload_config",
        lambda: calls.append("reload") or proposed,
    )
    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        refresh,
    )
    monkeypatch.setattr(
        config_module,
        "_enqueue_runtime_channels_refresh_command",
        lambda **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        config_module,
        "_build_system_config",
        lambda mask_api_key=True: proposed,
    )

    response = client.put("/config/", json=proposed.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["pause", "save", "reload", "refresh", "resume"]


def test_unrelated_config_change_does_not_interrupt_embedding_rebuild(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    current = _remote_embedding_config()
    proposed = current.model_copy(deep=True)
    proposed.tools.builtIn.webFetch.enabled = not current.tools.builtIn.webFetch.enabled

    def unexpected_manager():
        raise AssertionError("Unrelated settings must not pause embedding rebuilds")

    async def refresh(_config, *, reason: str) -> None:  # type: ignore[no-untyped-def]
        assert reason == "config_updated"

    monkeypatch.setattr(config_module, "get_config", lambda: current)
    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(config_module, "_build_update_paths", lambda _config: {})
    monkeypatch.setattr(config_module, "_build_full_update_paths", lambda _config: {})
    monkeypatch.setattr(config_module, "_get_embedding_rebuild_manager", unexpected_manager)
    monkeypatch.setattr(config_module, "save_config", lambda _updates: True)
    monkeypatch.setattr(config_module, "reload_config", lambda: proposed)
    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        refresh,
    )
    monkeypatch.setattr(
        config_module,
        "_enqueue_runtime_channels_refresh_command",
        lambda **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        config_module,
        "_build_system_config",
        lambda mask_api_key=True: proposed,
    )

    response = client.put("/config/", json=proposed.model_dump(mode="json"))

    assert response.status_code == 200


def test_embedding_config_save_failure_still_resumes_rebuild_starts(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    calls: list[str] = []
    current = _remote_embedding_config(model="text-embedding-3-small")
    proposed = _remote_embedding_config(model="text-embedding-3-large")

    class RebuildManager:
        async def pause_starts_and_cancel_all(self) -> int:
            calls.append("pause")
            return 1

        async def resume_starts(self) -> None:
            calls.append("resume")

    monkeypatch.setattr(config_module, "get_config", lambda: current)
    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(config_module, "_build_update_paths", lambda _config: {})
    monkeypatch.setattr(config_module, "_build_full_update_paths", lambda _config: {})
    monkeypatch.setattr(
        config_module,
        "_get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda _updates: calls.append("save") or False,
    )

    response = client.put("/config/", json=proposed.model_dump(mode="json"))

    assert response.status_code == 500
    assert calls == ["pause", "save", "resume"]


def test_embedding_runtime_refresh_failure_still_resumes_rebuild_starts(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    calls: list[str] = []
    current = _remote_embedding_config(model="text-embedding-3-small")
    proposed = _remote_embedding_config(model="text-embedding-3-large")

    class RebuildManager:
        async def pause_starts_and_cancel_all(self) -> int:
            calls.append("pause")
            return 1

        async def resume_starts(self) -> None:
            calls.append("resume")

    async def failing_refresh(_config, *, reason: str) -> None:  # type: ignore[no-untyped-def]
        assert reason == "config_updated"
        calls.append("refresh")
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(config_module, "get_config", lambda: current)
    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(config_module, "_build_update_paths", lambda _config: {})
    monkeypatch.setattr(config_module, "_build_full_update_paths", lambda _config: {})
    monkeypatch.setattr(
        config_module,
        "_get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda _updates: calls.append("save") or True,
    )
    monkeypatch.setattr(
        config_module,
        "reload_config",
        lambda: calls.append("reload") or proposed,
    )
    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        failing_refresh,
    )

    response = client.put("/config/", json=proposed.model_dump(mode="json"))

    assert response.status_code == 500
    assert calls == ["pause", "save", "reload", "refresh", "resume"]


def test_update_language_preference_saves_language_without_runtime_refresh(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    captured_updates: dict[str, object] = {}
    calls: list[str] = []

    def _fake_save_config(updates: dict) -> bool:
        captured_updates.update(updates)
        calls.append("save")
        return True

    def _fake_reload_config():
        calls.append("reload")
        return get_config()

    def _unexpected_runtime_refresh(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("language preference update should not refresh runtime")

    returned_config = SystemConfigModel()
    returned_config.preferences.language = "en"

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", _fake_reload_config)
    monkeypatch.setattr(
        "magi.api.routers.config._refresh_or_initialize_runtime_after_config_update",
        _unexpected_runtime_refresh,
    )
    monkeypatch.setattr("magi.api.routers.config._build_system_config", lambda: returned_config)

    response = client.put("/config/preferences/language", json={"language": "en"})

    assert response.status_code == 200
    assert captured_updates == {"preferences.language": "en"}
    assert calls == ["save", "reload"]
    assert response.json()["data"]["preferences"]["language"] == "en"


def test_update_language_preference_rejects_unsupported_language():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    response = client.put("/config/preferences/language", json={"language": "ja"})

    assert response.status_code == 422


def test_update_config_initializes_runtime_when_runtime_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    calls: list[str] = []
    payload = SystemConfigModel()

    async def _fake_initialize_agent_runtime() -> None:
        calls.append("initialize")

    async def _fake_enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
        assert reason == "config_updated"
        calls.append("enqueue")

    def _require_agent_runtime():
        raise RuntimeError("Runtime is not initialized")

    monkeypatch.setattr("magi.api.routers.config._build_update_paths", lambda _: {})
    monkeypatch.setattr("magi.api.routers.config.save_config", lambda _: True)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: get_config())
    monkeypatch.setattr(
        "magi.bootstrap.backend.initialize_agent_runtime",
        _fake_initialize_agent_runtime,
    )
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", _require_agent_runtime)
    monkeypatch.setattr(
        "magi.api.routers.config._enqueue_runtime_llm_refresh_command",
        _fake_enqueue_runtime_llm_refresh_command,
    )

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["initialize", "enqueue"]


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

    async def _skip_runtime_refresh(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        "magi.api.routers.config._refresh_or_initialize_runtime_after_config_update",
        _skip_runtime_refresh,
    )

    payload = SystemConfigModel().model_dump(mode="json")
    payload["preferences"]["close_to_tray_enabled"] = False
    payload["preferences"]["desktop_notifications_enabled"] = True
    payload["preferences"]["desktop_notification_previews_enabled"] = False

    response = client.put("/config/", json=payload)

    assert response.status_code == 200
    assert captured_updates["preferences"]["close_to_tray_enabled"] is False
    assert captured_updates["preferences"]["desktop_notifications_enabled"] is True
    assert captured_updates["preferences"]["desktop_notification_previews_enabled"] is False


def test_update_config_persists_changed_settings_and_returns_rebuilt_config(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    payload = SystemConfigModel()
    payload.tools.builtIn.webFetch.enabled = False
    expected_updates = {
        "agent.memory.l0.enabled": False,
        "tools.web_fetch.enabled": False,
    }
    captured_updates: dict[str, object] = {}

    def _fake_save_config(updates: dict) -> bool:
        captured_updates.update(updates)
        return True

    refreshed_config = object()
    returned_config = SystemConfigModel()
    returned_config.memory.l0.enabled = False
    returned_config.tools.builtIn.webFetch.enabled = False

    monkeypatch.setattr(
        "magi.api.routers.config._build_update_paths", lambda config: expected_updates
    )
    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: refreshed_config)

    async def _skip_runtime_refresh(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        "magi.api.routers.config._refresh_or_initialize_runtime_after_config_update",
        _skip_runtime_refresh,
    )
    monkeypatch.setattr(
        "magi.api.routers.config._build_system_config",
        lambda mask_api_key=False: returned_config,
    )

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert captured_updates == expected_updates
    assert response.json()["data"]["memory"]["l0"]["enabled"] is False
    assert response.json()["data"]["tools"]["builtIn"]["webFetch"]["enabled"] is False


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
    monkeypatch.setattr("magi.api.routers.config._read_onboarding_completed", lambda: False)

    response = client.post(
        "/config/onboarding-complete",
        json={"language": "zh", "llm": payload.llm.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh", "enqueue"]


@pytest.mark.parametrize(
    ("method", "path", "reason"),
    [
        ("PUT", "/config/onboarding-draft", "onboarding_draft_updated"),
        ("POST", "/config/onboarding-complete", "onboarding_completed"),
    ],
)
def test_onboarding_embedding_change_uses_rebuild_coordination(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    reason: str,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)
    calls: list[str] = []
    current = _remote_embedding_config(model="text-embedding-3-small")
    proposed = _remote_embedding_config(model="text-embedding-3-large")

    class RebuildManager:
        async def pause_starts_and_cancel_all(self) -> int:
            calls.append("pause")
            return 1

        async def resume_starts(self) -> None:
            calls.append("resume")

    async def refresh(_config, *, reason: str) -> None:  # type: ignore[no-untyped-def]
        calls.append(f"refresh:{reason}")

    monkeypatch.setattr(config_module, "get_config", lambda: current)
    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(
        config_module,
        "_build_onboarding_update_paths",
        lambda _config, complete: {},
    )
    monkeypatch.setattr(
        config_module,
        "_get_embedding_rebuild_manager",
        lambda: RebuildManager(),
    )
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda _updates: calls.append("save") or True,
    )
    monkeypatch.setattr(
        config_module,
        "reload_config",
        lambda: calls.append("reload") or proposed,
    )
    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        refresh,
    )
    monkeypatch.setattr(
        config_module,
        "_build_system_config",
        lambda mask_api_key=True: current,
    )
    monkeypatch.setattr(config_module, "_read_onboarding_completed", lambda: False)

    response = client.request(
        method,
        path,
        json={"language": "zh", "llm": proposed.llm.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert calls == ["pause", "save", "reload", f"refresh:{reason}", "resume"]


def test_complete_onboarding_returns_when_runtime_init_exceeds_response_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    payload = SystemConfigModel()
    started = False

    async def _slow_initialize_agent_runtime() -> None:
        nonlocal started
        started = True
        await asyncio.sleep(60)

    async def _fake_enqueue_runtime_llm_refresh_command(*, reason: str) -> None:
        assert reason == "onboarding_completed"

    def _require_agent_runtime():
        raise RuntimeError("Runtime is not initialized")

    monkeypatch.setattr(
        "magi.api.routers.config._build_onboarding_update_paths",
        lambda _, complete: {},
    )
    monkeypatch.setattr("magi.api.routers.config.save_config", lambda _: True)
    monkeypatch.setattr("magi.api.routers.config.reload_config", lambda: get_config())
    monkeypatch.setattr(
        "magi.api.routers.config._enqueue_runtime_llm_refresh_command",
        _fake_enqueue_runtime_llm_refresh_command,
    )
    monkeypatch.setattr(
        "magi.api.routers.config.ONBOARDING_RUNTIME_INIT_RESPONSE_BUDGET_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        "magi.bootstrap.backend.initialize_agent_runtime",
        _slow_initialize_agent_runtime,
    )
    monkeypatch.setattr("magi.core.runtime_bindings.require_agent_runtime", _require_agent_runtime)
    monkeypatch.setattr("magi.api.routers.config._read_onboarding_completed", lambda: False)

    response = client.post(
        "/config/onboarding-complete",
        json={"language": "zh", "llm": payload.llm.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert started is True


def test_user_preferences_has_product_tour_completed_default_false():
    from magi.api.routers.config_schemas import UserPreferencesModel

    prefs = UserPreferencesModel()
    assert prefs.product_tour_completed is False


def test_user_preferences_product_tour_completed_roundtrip():
    from magi.api.routers.config_schemas import UserPreferencesModel

    prefs = UserPreferencesModel(product_tour_completed=True)
    assert prefs.model_dump()["product_tour_completed"] is True
