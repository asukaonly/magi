from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magi.api.routers.plugins import plugins_router


class _FakeManager:
    def __init__(self) -> None:
        self._plugin_instances: dict = {}
        self.calls: list[str] = []
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
        self.calls.append("list")
        return [self.state]

    def get_package(self, plugin_id: str):
        self.calls.append(f"get:{plugin_id}")
        return self.state if plugin_id == "core-tools" else None

    def enable_plugin(self, plugin_id: str):
        self.calls.append(f"enable:{plugin_id}")
        self.state.enabled = True
        return self.state

    def disable_plugin(self, plugin_id: str):
        self.calls.append(f"disable:{plugin_id}")
        self.state.enabled = False
        return self.state

    def reload_plugin(self, plugin_id: str):
        self.calls.append(f"reload:{plugin_id}")
        return self.state

    def rescan_runtime(self, *, persist_discovery: bool = True):
        _ = persist_discovery
        self.calls.append("rescan")
        return [self.state]

    def update_plugin_settings(self, plugin_id: str, updates):
        self.calls.append(f"update:{plugin_id}")
        self.state.current_settings.update(updates)
        return self.state

    def read_plugin_settings_resource(self, plugin_id: str, resource_name: str):
        self.calls.append(f"resource:{plugin_id}:{resource_name}")
        if plugin_id != "core-tools" or resource_name != "calendar_lists":
            raise KeyError(resource_name)
        return {
            "plugin_id": plugin_id,
            "resource_name": resource_name,
            "resource_type": "collection",
            "data": {
                "groups": [
                    {
                        "group_id": "icloud",
                        "label": "iCloud",
                        "items": [
                            {
                                "item_id": "calendar-personal",
                                "label": "Personal",
                                "description": "Primary calendar",
                                "accent_color": "#2F80ED",
                            }
                        ],
                    }
                ]
            },
        }


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


def test_plugins_api_supports_enable_disable_reload_rescan_and_settings(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    monkeypatch.setattr("magi.api.routers.plugins.require_plugin_manager", lambda: manager)
    client = TestClient(app)

    disable_response = client.post("/api/plugins/core-tools/disable")
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False

    settings_response = client.get("/api/plugins/core-tools/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["enabled"] is False

    enable_response = client.post("/api/plugins/core-tools/enable")
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True

    reload_response = client.post("/api/plugins/core-tools/reload")
    assert reload_response.status_code == 200
    assert reload_response.json()["manifest"]["plugin_id"] == "core-tools"

    rescan_response = client.post("/api/plugins/rescan")
    assert rescan_response.status_code == 200
    assert rescan_response.json()["total"] == 1
    assert rescan_response.json()["plugins"][0]["enabled"] is True

    assert manager.calls == [
        "get:core-tools",
        "disable:core-tools",
        "get:core-tools",
        "get:core-tools",
        "enable:core-tools",
        "get:core-tools",
        "reload:core-tools",
        "rescan",
    ]


def test_plugins_api_reads_plugin_settings_resources(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    monkeypatch.setattr("magi.api.routers.plugins.require_plugin_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/plugins/core-tools/settings/resources/calendar_lists")

    assert response.status_code == 200
    payload = response.json()
    assert payload["plugin_id"] == "core-tools"
    assert payload["resource_name"] == "calendar_lists"
    assert payload["resource_type"] == "collection"
    assert payload["data"]["groups"][0]["items"][0]["item_id"] == "calendar-personal"
    assert manager.calls == ["get:core-tools", "resource:core-tools:calendar_lists"]
