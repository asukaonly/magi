"""Safety tests for onboarding configuration access and writes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import config as config_module
from magi.api.routers.config_schemas import LLMProviderConfigModel, SystemConfigModel


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(config_module.config_router, prefix="/config")
    return TestClient(app)


def _write_onboarding_state(path: Path, *, completed: bool) -> None:
    path.write_text(
        f"preferences:\n  onboarding_completed: {'true' if completed else 'false'}\n",
        encoding="utf-8",
    )


def _patch_config_path(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(config_module, "get_config_file_path", lambda: path)


def _patch_successful_runtime_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _skip_runtime_refresh(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        _skip_runtime_refresh,
    )


def _config_with_provider_key(api_key: str) -> SystemConfigModel:
    config = SystemConfigModel()
    config.llm.providers["openai"] = LLMProviderConfigModel(
        enabled=True,
        provider_type="openai",
        display_name="OpenAI",
        api_key=api_key,
        base_url="https://api.openai.com/v1",
        services={
            "chat": {
                "enabled": True,
                "api_key": api_key,
                "base_url": "https://api.openai.com/v1",
            },
            "embedding": {
                "enabled": True,
                "api_key": api_key,
                "base_url": "https://api.openai.com/v1",
            },
            "image_generation": {
                "enabled": True,
                "api_key": api_key,
                "base_url": "https://api.openai.com/v1",
            },
            "tts": {
                "enabled": True,
                "api_key": api_key,
                "base_url": "https://api.openai.com/v1",
            },
        },
    )
    config.llm.selections["core"].provider_id = "openai"
    config.llm.selections["core"].model = "gpt-5.6"
    return config


def test_onboarding_status_reads_persisted_completion_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=True)
    _patch_config_path(monkeypatch, config_path)

    response = client.get("/config/onboarding-status")

    assert response.status_code == 200
    assert response.json()["data"] == {"completed": True}


def test_onboarding_status_treats_missing_config_as_first_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "missing-agent.yaml"
    _patch_config_path(monkeypatch, config_path)

    response = client.get("/config/onboarding-status")

    assert response.status_code == 200
    assert response.json()["data"] == {"completed": False}


def test_onboarding_status_rejects_invalid_persisted_config(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    config_path.write_text("preferences: [", encoding="utf-8")
    _patch_config_path(monkeypatch, config_path)

    response = client.get("/config/onboarding-status")

    assert response.status_code == 500


def test_completed_installation_cannot_load_onboarding_template(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=True)
    _patch_config_path(monkeypatch, config_path)
    template_called = False

    def _unexpected_template() -> SystemConfigModel:
        nonlocal template_called
        template_called = True
        return SystemConfigModel()

    monkeypatch.setattr(config_module, "_build_onboarding_template", _unexpected_template)

    response = client.get("/config/onboarding-template")

    assert response.status_code == 409
    assert template_called is False


def test_onboarding_template_recovers_only_masked_backend_llm_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=False)
    _patch_config_path(monkeypatch, config_path)
    calls: list[bool] = []

    def _build_recovered_config(mask_secrets: bool = True) -> SystemConfigModel:
        calls.append(mask_secrets)
        return _config_with_provider_key(
            "***" if mask_secrets else "sk-draft-secret",
        )

    monkeypatch.setattr(config_module, "_build_system_config", _build_recovered_config)

    response = client.get("/config/onboarding-template")

    assert response.status_code == 200
    assert calls == [True]
    payload = response.json()["data"]["config"]
    assert payload["llm"]["providers"]["openai"]["api_key"] == "***"
    for service_name in ("chat", "embedding", "image_generation", "tts"):
        assert payload["llm"]["providers"]["openai"]["services"][service_name][
            "api_key"
        ] == "***"
    assert "sk-draft-secret" not in response.text


def test_onboarding_draft_only_saves_language_and_llm(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=False)
    _patch_config_path(monkeypatch, config_path)
    captured: dict[str, Any] = {}
    payload = SystemConfigModel()

    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda updates: captured.update(updates) is None,
    )
    monkeypatch.setattr(config_module, "reload_config", lambda: object())
    build_calls: list[bool] = []

    def _build_saved_config(mask_secrets: bool = True) -> SystemConfigModel:
        build_calls.append(mask_secrets)
        return _config_with_provider_key(
            "***" if mask_secrets else "sk-saved-secret",
        )

    monkeypatch.setattr(config_module, "_build_system_config", _build_saved_config)
    _patch_successful_runtime_refresh(monkeypatch)

    response = client.put(
        "/config/onboarding-draft",
        json={"language": "en", "llm": payload.llm.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert set(captured) == {
        "llm.providers",
        "llm.selections",
        "llm.model_runtime_overrides",
        "preferences.language",
    }
    assert captured["preferences.language"] == "en"
    assert build_calls == [False, True]
    assert response.json()["data"]["llm"]["providers"]["openai"]["api_key"] == (
        "***"
    )
    assert "sk-saved-secret" not in response.text


def test_onboarding_completion_preserves_unrelated_settings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=False)
    _patch_config_path(monkeypatch, config_path)
    captured: dict[str, Any] = {}
    payload = SystemConfigModel()
    payload.preferences.language = "en"
    payload.preferences.product_tour_completed = False
    payload.memory.retention_days = 777
    payload.network.host = "should-not-be-saved.example"
    payload.tools.builtIn.webFetch.enabled = False

    monkeypatch.setattr(config_module, "_normalize_masked_secrets", lambda config: config)
    monkeypatch.setattr(
        config_module,
        "save_config",
        lambda updates: captured.update(updates) is None,
    )
    monkeypatch.setattr(config_module, "reload_config", lambda: object())
    build_calls: list[bool] = []

    def _build_saved_config(mask_secrets: bool = True) -> SystemConfigModel:
        build_calls.append(mask_secrets)
        return _config_with_provider_key(
            "***" if mask_secrets else "sk-finished-secret",
        )

    monkeypatch.setattr(config_module, "_build_system_config", _build_saved_config)
    _patch_successful_runtime_refresh(monkeypatch)

    response = client.post(
        "/config/onboarding-complete",
        json={"language": "en", "llm": payload.llm.model_dump(mode="json")},
    )

    assert response.status_code == 200
    assert set(captured) == {
        "llm.providers",
        "llm.selections",
        "llm.model_runtime_overrides",
        "preferences.language",
        "preferences.onboarding_completed",
        "preferences.product_tour_completed",
    }
    assert captured["preferences.onboarding_completed"] is True
    assert captured["preferences.product_tour_completed"] is True
    assert build_calls == [False, True]
    assert response.json()["data"]["llm"]["providers"]["openai"]["api_key"] == (
        "***"
    )
    assert "sk-finished-secret" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "complete"),
    [
        ("put", "/config/onboarding-draft", False),
        ("post", "/config/onboarding-complete", True),
    ],
)
def test_onboarding_explicitly_cleared_key_is_not_restored(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    complete: bool,
) -> None:
    current = _config_with_provider_key("sk-old-secret")
    current.llm.providers["openai"].base_url = "https://old.example/v1"
    current.llm.providers["openai"].services.chat.base_url = "https://old.example/v1"
    submitted = _config_with_provider_key("")
    submitted.llm.providers["openai"].base_url = "http://127.0.0.1:11434/v1"
    submitted.llm.providers["openai"].services.chat.base_url = (
        "http://127.0.0.1:11434/v1"
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(config_module, "get_config", lambda: current)

    def _build_config(mask_secrets: bool = True) -> SystemConfigModel:
        return submitted.model_copy(deep=True) if mask_secrets else current.model_copy(deep=True)

    monkeypatch.setattr(config_module, "_build_system_config", _build_config)

    async def _capture_persist(**kwargs: Any) -> object:
        updates, proposed = kwargs["prepare_update"]()
        captured["updates"] = updates
        captured["proposed"] = proposed
        return object()

    monkeypatch.setattr(config_module, "_persist_config_update", _capture_persist)

    response = client.request(
        method,
        path,
        json={
            "language": "en",
            "llm": submitted.llm.model_dump(mode="json"),
        },
    )

    assert response.status_code == 200
    provider_update = captured["updates"]["llm.providers"]["openai"]
    assert provider_update["api_key"] == ""
    for service_name in ("chat", "embedding", "image_generation", "tts"):
        assert provider_update["services"][service_name]["api_key"] == ""
    assert provider_update["base_url"] == "http://127.0.0.1:11434/v1"
    proposed = captured["proposed"]
    assert proposed.llm.providers["openai"].api_key == ""
    for service_name in ("chat", "embedding", "image_generation", "tts"):
        assert getattr(proposed.llm.providers["openai"].services, service_name).api_key == ""
    assert provider_update.get("api_key") != "sk-old-secret"
    assert ("preferences.onboarding_completed" in captured["updates"]) is complete


def test_completed_installation_rejects_repeated_onboarding_completion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=True)
    _patch_config_path(monkeypatch, config_path)
    save_called = False

    def _unexpected_save(_: dict[str, Any]) -> bool:
        nonlocal save_called
        save_called = True
        return True

    monkeypatch.setattr(config_module, "save_config", _unexpected_save)
    _patch_successful_runtime_refresh(monkeypatch)

    response = client.post(
        "/config/onboarding-complete",
        json={
            "language": "zh",
            "llm": SystemConfigModel().llm.model_dump(mode="json"),
        },
    )

    assert response.status_code == 409
    assert save_called is False


def test_completed_installation_rejects_onboarding_draft(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=True)
    _patch_config_path(monkeypatch, config_path)
    save_called = False

    def _unexpected_save(_: dict[str, Any]) -> bool:
        nonlocal save_called
        save_called = True
        return True

    monkeypatch.setattr(config_module, "save_config", _unexpected_save)
    payload = SystemConfigModel()

    response = client.put(
        "/config/onboarding-draft",
        json={"language": "zh", "llm": payload.llm.model_dump(mode="json")},
    )

    assert response.status_code == 409
    assert save_called is False


def test_onboarding_update_rejects_unowned_configuration_fields(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=False)
    _patch_config_path(monkeypatch, config_path)
    payload = SystemConfigModel()

    response = client.put(
        "/config/onboarding-draft",
        json={
            "language": "zh",
            "llm": payload.llm.model_dump(mode="json"),
            "memory": payload.memory.model_dump(mode="json"),
        },
    )

    assert response.status_code == 422


def test_general_config_update_cannot_reset_onboarding_completion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "agent.yaml"
    _write_onboarding_state(config_path, completed=True)
    _patch_config_path(monkeypatch, config_path)
    submitted = SystemConfigModel()
    submitted.preferences.onboarding_completed = False
    captured_completed: list[bool] = []

    def _capture_update_paths(config: SystemConfigModel) -> dict[str, Any]:
        captured_completed.append(config.preferences.onboarding_completed)
        return {}

    async def _skip_runtime_refresh(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(config_module, "_build_update_paths", _capture_update_paths)
    monkeypatch.setattr(config_module, "save_config", lambda _: True)
    monkeypatch.setattr(config_module, "reload_config", lambda: object())
    monkeypatch.setattr(
        config_module,
        "_refresh_or_initialize_runtime_after_config_update",
        _skip_runtime_refresh,
    )
    monkeypatch.setattr(
        config_module,
        "_enqueue_runtime_channels_refresh_command",
        _skip_runtime_refresh,
    )
    monkeypatch.setattr(
        config_module,
        "_build_system_config",
        lambda mask_secrets=True: SystemConfigModel(),
    )

    response = client.put("/config/", json=submitted.model_dump(mode="json"))

    assert response.status_code == 200
    assert captured_completed == [True]
