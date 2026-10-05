from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from magi.api.routers.plugins_common import _serialize_contribution
from magi.api.routers.plugins import plugins_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.plugins import ContributionType, ExtensionFieldSpec, PluginContribution


class _FakeManager:
    def __init__(self) -> None:
        self._plugin_instances: dict = {}
        self.calls: list[str] = []
        self.last_settings_updates: dict = {}
        self.state = type(
            "PluginState",
            (),
            {
                "manifest": type(
                    "Manifest",
                    (),
                    {
                        "protocol_version": 2,
                        "min_sdk_version": "0.2.0",
                        "execution_mode": "trusted_process",
                        "settings_fields": [], "settings_actions": [],
                        "settings_resources": [], "settings_ui_blocks": [],
                        "activation_flow": None,
                        "plugin_id": "core-tools",
                        "name": "Core Tools",
                        "version": "1.0.0",
                        "description": "Built-in tools",
                        "author": "Magi Team",
                        "icon": "lucide:wrench",
                        "display_group": None,
                        "official": True,
                        "contribution_types": [type("ContributionType", (), {"value": "tool"})()],
                        "source": "builtin",
                        "plugin_dir": "/tmp/plugins/core-tools",
                        "manifest_path": "/tmp/plugins/core-tools/plugin.toml",
                        # Newer manifest contract fields the router reads:
                        # kind filters out libraries; capabilities feed the
                        # permission payload.
                        "kind": "plugin",
                        "capabilities": [],
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
        self.last_settings_updates = dict(updates)
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

    async def start_plugin_settings_action(
        self, plugin_id: str, action_id: str, *, field_values=None
    ):
        self.calls.append(f"start_action:{plugin_id}:{action_id}:{field_values or {}}")
        result = type(
            "PluginSettingsActionResult",
            (),
            {
                "status": "pending",
                "message": "Scan the code",
                "data": {"qr_code_url": "data:image/png;base64,abc"},
                "settings_updates": {},
            },
        )()
        return type("PluginSettingsActionRun", (), {"session_id": "session-1", "result": result})()

    async def poll_plugin_settings_action(
        self, plugin_id: str, action_id: str, *, session_id: str, field_values=None
    ):
        self.calls.append(f"poll_action:{plugin_id}:{action_id}:{session_id}:{field_values or {}}")
        result = type(
            "PluginSettingsActionResult",
            (),
            {
                "status": "succeeded",
                "message": "Connected",
                "data": {},
                "settings_updates": {"account_id": "account-1"},
            },
        )()
        return type("PluginSettingsActionRun", (), {"session_id": session_id, "result": result})()

    async def cancel_plugin_settings_action(
        self, plugin_id: str, action_id: str, *, session_id: str
    ):
        self.calls.append(f"cancel_action:{plugin_id}:{action_id}:{session_id}")
        result = type(
            "PluginSettingsActionResult",
            (),
            {
                "status": "cancelled",
                "message": "Cancelled",
                "data": {},
                "settings_updates": {},
            },
        )()
        return type("PluginSettingsActionRun", (), {"session_id": session_id, "result": result})()


class _FakeRuntimeQueue:
    def __init__(self) -> None:
        self.refresh_channel_reasons: list[str | None] = []

    async def enqueue_refresh_channels(self, command) -> int:
        self.refresh_channel_reasons.append(command.reason)
        return len(self.refresh_channel_reasons)


@pytest.mark.parametrize(
    ("path_template", "location", "invalid_ids"),
    [
        ("/install/registry/plan", "body", ["", "a" * 65, "Uppercase", "../escape"]),
        ("/install/registry", "body", ["", "a" * 65, "Uppercase", "../escape"]),
        ("/install/registry/jobs", "body", ["", "a" * 65, "Uppercase", "../escape"]),
        ("/{plugin_id}/update", "path", ["Uppercase", "a" * 65]),
        ("/{plugin_id}/update/jobs", "path", ["Uppercase", "a" * 65]),
    ],
)
def test_invalid_plugin_identifiers_are_rejected_at_owning_http_field(
    path_template, location, invalid_ids, monkeypatch
):
    from unittest.mock import Mock
    from magi.api.routers import plugins_install_routes

    work = Mock(side_effect=AssertionError("Invalid identifiers must not reach installation"))
    monkeypatch.setattr(plugins_install_routes, "_plugin_install_service", work)
    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )
    client = TestClient(app)
    for plugin_id in invalid_ids:
        body = {"plugin_id": plugin_id} if location == "body" else {}
        if path_template.endswith("/plan"):
            body["update"] = False
        else:
            body["plan_fingerprint"] = "a" * 64
        response = client.post(
            "/api/plugins" + path_template.format(plugin_id=plugin_id), json=body
        )
        assert response.status_code == 422
        assert [error["loc"] for error in response.json()["detail"]] == [[location, "plugin_id"]]
    work.assert_not_called()


def test_plugin_secret_settings_are_write_only(monkeypatch):
    app = FastAPI()
    app.include_router(
        _build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]),
        prefix="/api/plugins",
    )
    manager = _FakeManager()
    manager.state.current_settings = {
        "auth.token": "stored-plugin-secret",
        "display.label": "Core",
    }
    manager.state.contributions = [
        PluginContribution(
            plugin_id="core-tools",
            contribution_id="tool.core",
            contribution_type=ContributionType.TOOL,
            display_name="Core",
            fields=[
                ExtensionFieldSpec(
                    key="auth.token",
                    type="secret",
                    label="Access token",
                    default="must-not-be-returned",
                )
            ],
        )
    ]
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue", lambda: queue
    )
    client = TestClient(app)

    listed = client.get("/api/plugins")
    assert listed.status_code == 200
    manifest = listed.json()["plugins"][0]["manifest"]
    assert (manifest["plugin_id"], manifest["icon"]) == ("core-tools", "lucide:wrench")
    assert listed.json()["plugins"][0]["current_settings"]["auth.token"] == "***"
    assert listed.json()["plugins"][0]["contributions"][0]["fields"][0]["default"] == ""
    assert "stored-plugin-secret" not in listed.text
    assert "must-not-be-returned" not in listed.text


def test_plugins_api_resolves_packaged_icon(monkeypatch, tmp_path):
    from magi_plugin_sdk import PluginDisplayGroupSpec

    app = FastAPI()
    app.include_router(_build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    manager = _FakeManager()
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1H0z"/></svg>',
        encoding="utf-8",
    )
    manager.state.manifest.icon = "asset:assets/icon.svg"
    manager.state.manifest.display_group = PluginDisplayGroupSpec(
        id="tools", name="Tools", icon="asset:assets/icon.svg"
    )
    manager.state.manifest.plugin_dir = str(tmp_path)
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)

    response = TestClient(app).get("/api/plugins")

    assert response.status_code == 200
    assert response.json()["plugins"][0]["manifest"]["icon"].startswith(
        "data:image/svg+xml;base64,"
    )
    assert response.json()["plugins"][0]["manifest"]["display_group"]["icon"] == (
        response.json()["plugins"][0]["manifest"]["icon"]
    )


def test_plugins_api_supports_reload_and_rescan(monkeypatch):
    app = FastAPI()
    app.include_router(_build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    manager = _FakeManager()
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue", lambda: queue
    )
    client = TestClient(app)

    reload_response = client.post("/api/plugins/core-tools/reload")
    assert reload_response.status_code == 200
    assert reload_response.json()["manifest"]["plugin_id"] == "core-tools"

    rescan_response = client.post("/api/plugins/rescan")
    assert rescan_response.status_code == 200
    assert rescan_response.json()["total"] == 1
    assert rescan_response.json()["plugins"][0]["enabled"] is True

    assert manager.calls == ["get:core-tools", "reload:core-tools", "rescan"]
    assert queue.refresh_channel_reasons == ["plugin_core-tools_reloaded"]


@pytest.mark.asyncio
async def test_plugin_lifecycle_route_does_not_block_the_event_loop(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(_build_public_router(plugins_router, _PUBLIC_ROUTE_METHODS["plugins"]), prefix="/api/plugins")
    operation_started = threading.Event()
    release_operation = threading.Event()

    class _BlockingManager(_FakeManager):
        def reload_plugin(self, plugin_id: str):
            operation_started.set()
            if not release_operation.wait(timeout=2):
                raise TimeoutError("Timed out waiting to release plugin lifecycle operation")
            return super().reload_plugin(plugin_id)

    manager = _BlockingManager()
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr(
        "magi.api.routers.plugins_common.resolve_plugin_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue",
        lambda: queue,
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        request_task = asyncio.create_task(client.post("/api/plugins/core-tools/reload"))
        deadline = asyncio.get_running_loop().time() + 1
        while not operation_started.is_set():
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)

        heartbeat_started = asyncio.get_running_loop().time()
        await asyncio.sleep(0.02)
        heartbeat_elapsed = asyncio.get_running_loop().time() - heartbeat_started
        assert heartbeat_elapsed < 0.2

        release_operation.set()
        response = await request_task

    assert response.status_code == 200
    assert queue.refresh_channel_reasons == ["plugin_core-tools_reloaded"]


def test_plugins_api_translates_settings_action_metadata():
    contribution = PluginContribution(
        plugin_id="weixin",
        contribution_id="weixin:channel",
        contribution_type=ContributionType.CHANNEL,
        display_name="Weixin",
        description="Channel",
        surface="extensions",
        metadata={
            "settings_actions": [
                {
                    "action_id": "qr_login",
                    "label": "Weixin QR Login",
                    "description": "Scan with Weixin.",
                    "button_label": "Start QR Login",
                }
            ]
        },
    )

    class FakeI18n:
        def t(self, key, fallback="", **kwargs):
            translations = {
                "actions.qr_login.label": "微信扫码登录",
                "actions.qr_login.description": "用微信扫描二维码完成授权。",
                "actions.qr_login.button_label": "开始扫码登录",
            }
            return translations.get(key, fallback)

    serialized = _serialize_contribution(contribution, FakeI18n())

    action = serialized.metadata["settings_actions"][0]
    assert action["label"] == "微信扫码登录"
    assert action["description"] == "用微信扫描二维码完成授权。"
    assert action["button_label"] == "开始扫码登录"


@pytest.mark.parametrize("path_kind", ["file", "directory"])
def test_manifest_response_preserves_picker_and_first_sync_settings(tmp_path, path_kind):
    from magi.api.routers.plugins_serialization import _serialize_manifest
    from magi_plugin_sdk import ActivationFlowSpec, PluginManifest
    field = ExtensionFieldSpec(key="sources.example.root", type="path", path_kind=path_kind, label="Root")
    manifest = PluginManifest(id="example", name="Example", version="1.0.0", plugin_dir=str(tmp_path), settings_fields=[field], activation_flow=ActivationFlowSpec(title="Connect source", enabled_key="sources.example.enabled", configured_key="sources.example.configured", fields=[field], first_context={"max_items_per_sync": 75, "settings_overrides": {"sources.example.lookback_days": 7}}))
    response = _serialize_manifest(manifest, packages={}).model_dump(mode="json")
    assert response["settings_fields"][0]["path_kind"] == path_kind
    assert response["activation_flow"]["fields"][0]["path_kind"] == path_kind
    assert response["activation_flow"]["first_context"] == {"max_items_per_sync": 75, "settings_overrides": {"sources.example.lookback_days": 7}}
