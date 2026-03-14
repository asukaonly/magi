"""Tests for config router extensions."""

from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.config import (
    LLMProviderConfigModel,
    LLMSelectionConfigModel,
    SystemConfigModel,
    _build_system_config,
    _build_onboarding_template,
    _build_update_paths,
    _default_llm_provider_registry,
    config_router,
)
from magi.config.loader import get_config
from magi.config.models import LLMProviderSettings, LLMSelectionSettings, LLMSettings
from magi.config.llm_registry import LLMProviderRegistryModel, resolve_llm_profile


def test_system_config_defaults_include_llm_provider_pool_and_selections():
    config = SystemConfigModel()

    assert hasattr(config.llm, "providers")
    assert hasattr(config.llm, "selections")
    assert "context_decider" in config.llm.selections
    assert "core" in config.llm.selections


def test_system_config_defaults_include_memory_lifecycle_settings():
    config = SystemConfigModel()

    assert config.memory.enable_l0 is True
    assert config.memory.enable_l4 is True
    assert config.memory.l0_checkpoint_interval_seconds == 30
    assert config.memory.enable_l2_llm_extraction is True
    assert config.memory.enable_l4_skill_extraction is True


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


def test_llm_provider_settings_support_custom_model_fields():
    provider = LLMProviderSettings(
        provider_type="custom",
        display_name="Proxy",
        custom_models=["foo-1", "foo-2"],
        custom_default_model="foo-1",
    )

    assert provider.custom_models == ["foo-1", "foo-2"]
    assert provider.custom_default_model == "foo-1"


def test_custom_provider_default_model_must_be_in_model_list():
    with pytest.raises(ValueError):
        LLMProviderSettings(
            provider_type="custom",
            display_name="Proxy",
            custom_models=["foo-1"],
            custom_default_model="foo-2",
        )


def test_build_update_paths_contains_new_sections():
    config = SystemConfigModel()
    updates = _build_update_paths(config)

    assert "llm.providers" in updates
    assert "llm.selections" in updates
    assert "preferences" in updates
    assert "agent.memory.enable_l0" in updates
    assert "agent.memory.enable_l4" in updates
    assert "agent.memory.l0_checkpoint_interval_seconds" in updates
    assert "agent.memory.enable_l2_llm_extraction" in updates
    assert "memory_layers" not in updates
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
    assert "core" in template.llm.selections


def test_build_update_paths_skip_masked_api_key():
    config = SystemConfigModel()
    config.llm.providers["openai"].api_key = "***"
    updates = _build_update_paths(config)
    assert updates["llm.providers"]["openai"].get("api_key") in (None, "")


def test_build_system_config_returns_real_llm_api_keys_by_default(monkeypatch: pytest.MonkeyPatch):
    runtime_config = get_config()
    original_api_key = runtime_config.llm.providers["openai"].api_key
    runtime_config.llm.providers["openai"].api_key = "sk-visible-openai"

    try:
        config = _build_system_config()
        assert config.llm.providers["openai"].api_key == "sk-visible-openai"
    finally:
        runtime_config.llm.providers["openai"].api_key = original_api_key


def test_build_update_paths_applies_builtin_provider_defaults_before_save():
    config = SystemConfigModel()
    config.llm.providers = {
        "glm": LLMProviderConfigModel(
            enabled=True,
            provider_type="openai",
            display_name="",
            api_key="glm-key",
            base_url="",
        )
    }
    config.llm.selections["context_decider"] = LLMSelectionConfigModel(provider_id="glm", model="")
    config.llm.selections["core"] = LLMSelectionConfigModel(provider_id="glm", model="")

    updates = _build_update_paths(config)

    assert updates["llm.providers"]["glm"]["provider_type"] == "glm"
    assert updates["llm.providers"]["glm"]["display_name"] == "Z.ai"
    assert updates["llm.providers"]["glm"]["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert updates["llm.selections"]["context_decider"]["model"] == "glm-5"
    assert updates["llm.selections"]["core"]["model"] == "glm-5"


def test_build_update_paths_does_not_depend_on_legacy_llm_env_vars(monkeypatch: pytest.MonkeyPatch):
    config = SystemConfigModel()
    config.llm.providers["glm"] = LLMProviderSettings(
        enabled=True,
        provider_type="glm",
        display_name="Z.ai",
        api_key="glm-key",
        base_url="https://open.bigmodel.cn/api/paas/v4",
    )
    config.llm.selections["core"] = LLMSelectionSettings(provider_id="glm", model="glm-4.7-flash")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    updates = _build_update_paths(config)

    assert updates["llm.providers"]["glm"]["api_key"] == "glm-key"
    assert "LLM_API_KEY" not in __import__("os").environ


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


def test_default_registry_includes_extended_builtin_providers():
    registry = _default_llm_provider_registry()
    providers_by_id = {provider.id: provider for provider in registry.providers}

    assert {"openai", "anthropic", "glm", "gemini", "deepseek", "kimi", "minimax"} <= providers_by_id.keys()
    assert providers_by_id["gemini"].default_base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert providers_by_id["deepseek"].default_base_url == "https://api.deepseek.com"
    assert providers_by_id["kimi"].default_base_url == "https://api.moonshot.cn/v1"
    assert providers_by_id["minimax"].default_base_url == "https://api.minimaxi.com/v1"


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
    assert template.llm.selections["core"].limits.max_output_tokens is None


def test_onboarding_template_ignores_llm_environment_variables(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.setenv("LLM_MODEL", "glm-5")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example.com/v1")

    template = _build_onboarding_template()

    assert template.llm.providers
    assert all(provider.enabled is False for provider in template.llm.providers.values())
    assert all(provider.api_key in (None, "") for provider in template.llm.providers.values())
    assert template.llm.selections["core"].provider_id == ""
    assert template.llm.selections["core"].model == ""


def test_example_config_uses_scenario_llm_structure():
    example_path = Path(__file__).resolve().parents[2] / "configs" / "config.example.yaml"
    data = yaml.safe_load(example_path.read_text(encoding="utf-8"))

    assert "providers" in data["llm"]
    assert "selections" in data["llm"]
    assert "provider" not in data["llm"]
    assert "model" not in data["llm"]
    assert data["llm"]["providers"]["openai"]["enabled"] is False
    assert data["llm"]["selections"]["context_decider"]["provider_id"] == ""
    assert data["llm"]["selections"]["context_decider"]["model"] == ""
    assert data["llm"]["selections"]["core"]["provider_id"] == ""
    assert data["llm"]["selections"]["core"]["model"] == ""


def test_discover_llm_models_returns_models_from_provider_endpoint(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    async def _fake_discover(_: str, __: str | None, ___: str | None):
        return ["foo-1", "foo-2"]

    monkeypatch.setattr(
        "magi.api.routers.config._discover_openai_compatible_models",
        _fake_discover,
    )

    response = client.post(
        "/config/llm/providers/discover-models",
        json={
            "provider_type": "custom",
            "base_url": "https://proxy.example.com/v1",
            "api_key": "sk-test",
            "api_format": "openai",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["models"] == ["foo-1", "foo-2"]
    assert response.json()["data"]["default_model"] == "foo-1"


def test_discover_llm_models_returns_clear_error_for_unsupported_format():
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    response = client.post(
        "/config/llm/providers/discover-models",
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


def test_llm_provider_test_endpoint_uses_request_provider_payload(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    captured: dict[str, object] = {}

    async def _fake_probe(provider_id: str, provider, model: str):  # type: ignore[no-untyped-def]
        captured["provider_id"] = provider_id
        captured["provider_type"] = provider.provider_type
        captured["api_key"] = provider.api_key
        captured["base_url"] = provider.base_url
        captured["model"] = model
        return {"model": model, "latency_ms": 42, "preview": "hello"}

    monkeypatch.setattr(
        "magi.api.routers.config._test_llm_provider_connection",
        _fake_probe,
        raising=False,
    )

    response = client.post(
        "/config/llm/providers/test",
        json={
            "provider_id": "openai",
            "model": "gpt-5.2",
            "provider": {
                "enabled": True,
                "provider_type": "openai",
                "display_name": "OpenAI",
                "api_key": "sk-live",
                "base_url": "https://api.openai.com/v1",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["model"] == "gpt-5.2"
    assert captured == {
        "provider_id": "openai",
        "provider_type": "openai",
        "api_key": "sk-live",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.2",
    }


def test_llm_provider_test_endpoint_falls_back_to_registry_default_base_url(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    captured: dict[str, object] = {}

    async def _fake_probe(provider_id: str, provider, model: str):  # type: ignore[no-untyped-def]
        captured["provider_id"] = provider_id
        captured["provider_type"] = provider.provider_type
        captured["base_url"] = provider.base_url
        captured["model"] = model
        return {"model": model, "latency_ms": 12, "preview": "hello"}

    monkeypatch.setattr(
        "magi.api.routers.config._test_llm_provider_connection",
        _fake_probe,
        raising=False,
    )

    response = client.post(
        "/config/llm/providers/test",
        json={
            "provider_id": "glm",
            "model": "glm-4.7-flash",
            "provider": {
                "enabled": True,
                "provider_type": "glm",
                "display_name": "GLM",
                "api_key": "glm-key",
                "base_url": "",
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


def test_update_config_reloads_config_and_refreshes_runtime_llm_cache(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(config_router, prefix="/config")
    client = TestClient(app)

    calls: list[str] = []
    payload = SystemConfigModel()
    payload.llm.providers["glm"] = LLMProviderConfigModel(
        enabled=True,
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

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", _fake_reload_config)
    monkeypatch.setattr(
        "magi.api.routers.config.refresh_runtime_llm_config",
        _fake_refresh_runtime_llm_config,
    )

    response = client.put("/config/", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh"]


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

    monkeypatch.setattr("magi.api.routers.config.save_config", _fake_save_config)
    monkeypatch.setattr("magi.api.routers.config.reload_config", _fake_reload_config)
    monkeypatch.setattr(
        "magi.api.routers.config.refresh_runtime_llm_config",
        _fake_refresh_runtime_llm_config,
    )
    monkeypatch.setattr(
        "magi.api.routers.config._save_personality_to_user",
        lambda _: True,
    )

    response = client.post("/config/onboarding-complete", json=payload.model_dump(mode="json"))

    assert response.status_code == 200
    assert calls == ["save", "reload", "refresh"]
