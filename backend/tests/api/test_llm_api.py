"""Tests for dedicated LLM catalog and template APIs."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routes import register_api_routes
from magi.config.loader import get_config
from magi.config.models import (
    LLMCapabilityOverridesSettings,
    LLMModelMetadataOverrideSettings,
    LLMProviderSettings,
)


def _build_client() -> TestClient:
    app = FastAPI()
    register_api_routes(app)
    return TestClient(app)


def test_llm_provider_catalog_returns_builtin_and_saved_custom_providers() -> None:
    runtime_config = get_config()
    provider_id = "custom_catalog_test"
    original_provider = runtime_config.llm.providers.get(provider_id)
    custom_provider = LLMProviderSettings(
        enabled=True,
        provider_type="custom",
        display_name="Workspace Proxy",
        api_format="openai",
        custom_models=["foo-vision"],
        custom_default_model="foo-vision",
        model_metadata_overrides={
            "foo-vision": LLMModelMetadataOverrideSettings(
                label="Foo Vision",
                capabilities=LLMCapabilityOverridesSettings(vision=True),
            )
        },
    )
    custom_provider.services.chat.api_key = "sk-proxy"
    custom_provider.services.chat.base_url = "https://proxy.example.com/v1"
    runtime_config.llm.providers[provider_id] = custom_provider

    try:
        client = _build_client()
        response = client.get("/api/llm/providers/catalog")
    finally:
        if original_provider is None:
            runtime_config.llm.providers.pop(provider_id, None)
        else:
            runtime_config.llm.providers[provider_id] = original_provider

    assert response.status_code == 200
    payload = response.json()
    providers = payload["data"]["providers"]

    openai_provider = next(provider for provider in providers if provider["id"] == "openai")
    custom_provider = next(provider for provider in providers if provider["id"] == provider_id)

    assert openai_provider["source"] == "builtin"
    assert openai_provider["provider_type"] == "openai"
    assert custom_provider["source"] == "custom"
    assert custom_provider["provider_type"] == "custom"
    assert custom_provider["api_format"] == "openai"
    assert custom_provider["default_model"] == "foo-vision"

    foo_vision = next(model for model in custom_provider["resolved_chat_models"] if model["id"] == "foo-vision")
    assert foo_vision["label"] == "Foo Vision"
    assert foo_vision["capabilities"]["vision"] is True


def test_llm_provider_catalog_preview_resolves_draft_provider_overrides() -> None:
    client = _build_client()

    response = client.post(
        "/api/llm/providers/catalog",
        json={
            "providers": {
                "openai": {
                    "enabled": True,
                    "provider_type": "openai",
                    "display_name": "OpenAI",
                    "services": {
                        "chat": {
                            "enabled": True,
                            "api_key": "sk-openai",
                            "base_url": "https://api.openai.com/v1",
                        },
                        "embedding": {
                            "enabled": True,
                            "api_key": "sk-openai",
                            "base_url": "https://api.openai.com/v1",
                        },
                        "image_generation": {
                            "enabled": False,
                            "api_key": "",
                            "base_url": "https://api.openai.com/v1",
                            "timeout": 180,
                        },
                        "tts": {
                            "enabled": False,
                            "api_key": "",
                            "base_url": "https://api.openai.com/v1",
                        },
                    },
                    "custom_models": ["acme-vision-embed"],
                    "custom_default_model": "acme-vision-embed",
                    "model_metadata_overrides": {
                        "acme-vision-embed": {
                            "label": "Acme Vision Embed",
                            "capabilities": {
                                "vision": True,
                                "embedding": True,
                            },
                        }
                    },
                }
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    providers = payload["data"]["providers"]
    openai_provider = next(provider for provider in providers if provider["id"] == "openai")

    chat_model = next(model for model in openai_provider["resolved_chat_models"] if model["id"] == "acme-vision-embed")
    embedding_model = next(
        model for model in openai_provider["resolved_embedding_models"] if model["id"] == "acme-vision-embed"
    )

    assert chat_model["source"] == "manual"
    assert chat_model["capabilities"]["vision"] is True
    assert embedding_model["capabilities"]["embedding"] is True


def test_llm_custom_provider_template_returns_template_defaults() -> None:
    client = _build_client()

    response = client.get("/api/llm/providers/custom-template")

    assert response.status_code == 200
    payload = response.json()

    assert payload["data"]["defaults"]["provider_type"] == "custom"
    assert payload["data"]["defaults"]["api_format"] == "openai"
    assert payload["data"]["defaults"]["custom_models"] == []
    assert payload["data"]["template"]["fields"]["custom_name"]["required"] is True
