from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.plugins import plugins_router


class _FakeManager:
    def __init__(self) -> None:
        self._plugin_instances: dict = {}
        self.state = type(
            "PluginState",
            (),
            {
                "manifest": type(
                    "Manifest",
                    (),
                    {
                        "plugin_id": "core-tools",
                        "name": "Core Tools",
                        "version": "1.0.0",
                        "description": "Built-in tools",
                        "author": "Magi Team",
                        "official": True,
                        "contribution_types": [type("ContributionType", (), {"value": "tool"})()],
                        "source": "builtin",
                        "plugin_dir": "/tmp/plugins/core-tools",
                        "manifest_path": "/tmp/plugins/core-tools/plugin.toml",
                    },
                )(),
                "enabled": True,
                "trusted": True,
                "loaded": True,
                "healthy": True,
                "last_error": None,
                "contributions": [],
                "current_settings": {},
            },
        )()

    def list_packages(self):
        return [self.state]

    def get_package(self, plugin_id: str):
        return self.state if plugin_id == "core-tools" else None

    def enable_plugin(self, plugin_id: str):
        return self.state

    def disable_plugin(self, plugin_id: str):
        self.state.enabled = False
        return self.state

    def reload_plugin(self, plugin_id: str):
        return self.state

    def rescan_runtime(self, *, persist_discovery: bool = True):
        _ = persist_discovery
        return [self.state]

    def update_plugin_settings(self, plugin_id: str, updates):
        self.state.current_settings.update(updates)
        return self.state


def test_plugins_api_lists_and_updates_plugin_settings(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    monkeypatch.setattr("magi.api.routers.plugins.require_plugin_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert response.json()["plugins"][0]["manifest"]["plugin_id"] == "core-tools"

    update_response = client.put("/api/plugins/core-tools/settings", json={"updates": {"display.label": "Core"}})
    assert update_response.status_code == 200
    assert update_response.json()["current_settings"]["display.label"] == "Core"
