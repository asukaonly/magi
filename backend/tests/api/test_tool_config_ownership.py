"""Public API coverage for independently owned tool configuration."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers import config as config_routes
from magi.api.routers import tools as tool_routes
from magi.api.routers.config_schemas import FullPersonalityConfigModel
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.config import loader as config_loader


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(config_loader, "get_magi_home", lambda: tmp_path)
    monkeypatch.setattr(config_loader, "_loader", None)
    monkeypatch.setattr(config_routes, "_load_full_personality", FullPersonalityConfigModel)
    monkeypatch.setattr(config_routes, "_refresh_or_initialize_runtime_after_config_update", AsyncMock())
    monkeypatch.setattr(config_routes, "_enqueue_runtime_channels_refresh_command", AsyncMock())
    monkeypatch.setattr(tool_routes, "_ensure_plugins_loaded", lambda: None)
    app = FastAPI()
    app.include_router(
        _build_public_router(config_routes.config_router, _PUBLIC_ROUTE_METHODS["config"]),
        prefix="/api/config",
    )
    app.include_router(
        _build_public_router(tool_routes.tools_router, _PUBLIC_ROUTE_METHODS["tools"]),
        prefix="/api/tools",
    )
    return TestClient(app)


def test_tool_save_survives_later_general_settings_save(client: TestClient) -> None:
    initial = client.get("/api/config/")
    assert initial.status_code == 200
    stale_general_config = initial.json()["data"]
    assert "tools" not in stale_general_config

    tool_changes = {
        "web-search": {
            "enabled": False,
            "updates": {"default_provider": "tavily", "providers.tavily.api_key": "test-search-key"},
        },
        "weather": {"enabled": False, "updates": {"default_provider": "qweather"}},
        "web-fetch": {
            "enabled": False,
            "updates": {
                "allow_rfc2544_benchmark_range": False,
                "allow_private_network": True,
                "private_network_allowlist": ["trusted.example"],
            },
        },
    }
    for name, change in tool_changes.items():
        response = client.put(f"/api/tools/{name}/config", json=change)
        assert response.status_code == 200
        assert response.json()["success"] is True

    stale_general_config["preferences"]["close_to_tray_enabled"] = False
    stale_general_config["skills"] = ["selected-skill"]
    saved = client.put("/api/config/", json=stale_general_config)
    assert saved.status_code == 200
    assert saved.json()["data"]["preferences"]["close_to_tray_enabled"] is False
    assert "tools" not in saved.json()["data"]

    listed = client.get("/api/tools/config")
    assert listed.status_code == 200
    tools = {item["name"]: item for item in listed.json()["tools"]}
    for name in tool_changes:
        assert tools[name]["enabled"] is False
    assert tools["web-search"]["current_values"]["default_provider"] == "tavily"
    assert "providers.tavily.api_key" not in tools["web-search"]["current_values"]
    assert tools["weather"]["current_values"]["default_provider"] == "qweather"
    assert tools["web-fetch"]["current_values"] == tool_changes["web-fetch"]["updates"]

    stored = yaml.safe_load(config_loader.get_config_file_path().read_text())
    assert "builtIn" not in stored["tools"]
    assert stored["tools"]["skills"] == ["selected-skill"]
    assert stored["tools"]["web_search"]["enabled"] is False
    assert stored["tools"]["web_search"]["providers"]["tavily"]["api_key"] == "test-search-key"
    assert stored["tools"]["web_fetch"]["allow_rfc2544_benchmark_range"] is False


def test_fake_ip_policy_update_does_not_enable_private_access(client: TestClient) -> None:
    initial = client.get("/api/tools/web-fetch/config")
    assert initial.status_code == 200
    assert initial.json()["current_values"]["allow_rfc2544_benchmark_range"] is True

    for enabled in (False, True):
        response = client.put(
            "/api/tools/web-fetch/config",
            json={"updates": {"allow_rfc2544_benchmark_range": enabled}},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        current = client.get("/api/tools/web-fetch/config").json()
        assert current["enabled"] is True
        assert current["current_values"] == {
            "allow_rfc2544_benchmark_range": enabled,
            "allow_private_network": False,
            "private_network_allowlist": [],
        }


def test_failed_tool_save_is_an_http_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("magi.config.save_config", lambda updates: False)
    response = client.put(
        "/api/tools/web-fetch/config",
        json={"updates": {"allow_rfc2544_benchmark_range": True}},
    )
    assert response.status_code == 500
