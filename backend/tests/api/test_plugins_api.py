from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from magi.api.routers.plugins_common import _serialize_contribution
from magi.api.routers.plugins import plugins_router
from magi.plugins import ContributionType, PluginContribution


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
    "plugin_id",
    [
        "",
        "a" * 65,
        "Uppercase",
        "../escape",
    ],
)
def test_registry_install_rejects_invalid_plugin_id_before_work(
    plugin_id: str,
) -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")

    response = TestClient(app).post(
        "/api/plugins/install/registry",
        json={
            "plugin_id": plugin_id,
            "expected_fingerprint": "a" * 64,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("suffix", ["update", "update/jobs"])
@pytest.mark.parametrize("plugin_id", ["Uppercase", "a" * 65])
def test_registry_update_rejects_invalid_plugin_id_before_work(
    plugin_id: str,
    suffix: str,
) -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")

    response = TestClient(app).post(
        f"/api/plugins/{plugin_id}/{suffix}",
        json={"expected_fingerprint": "a" * 64},
    )

    assert response.status_code == 422


def test_plugins_api_lists_and_updates_plugin_settings(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue", lambda: queue
    )
    client = TestClient(app)

    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert response.json()["plugins"][0]["manifest"]["plugin_id"] == "core-tools"
    assert response.json()["plugins"][0]["manifest"]["icon"] == "lucide:wrench"

    update_response = client.put(
        "/api/plugins/core-tools/settings", json={"updates": {"display.label": "Core"}}
    )
    assert update_response.status_code == 200
    assert update_response.json()["current_settings"]["display.label"] == "Core"
    assert queue.refresh_channel_reasons == ["plugin_core-tools_settings_updated"]


def test_plugins_api_resolves_packaged_icon(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "icon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1H0z"/></svg>',
        encoding="utf-8",
    )
    manager.state.manifest.icon = "asset:assets/icon.svg"
    manager.state.manifest.plugin_dir = str(tmp_path)
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)

    response = TestClient(app).get("/api/plugins")

    assert response.status_code == 200
    assert response.json()["plugins"][0]["manifest"]["icon"].startswith(
        "data:image/svg+xml;base64,"
    )


def test_plugins_api_supports_enable_disable_reload_rescan_and_settings(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue", lambda: queue
    )
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
    assert queue.refresh_channel_reasons == [
        "plugin_core-tools_disabled",
        "plugin_core-tools_enabled",
        "plugin_core-tools_reloaded",
    ]


@pytest.mark.asyncio
async def test_plugin_lifecycle_route_does_not_block_the_event_loop(
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    operation_started = threading.Event()
    release_operation = threading.Event()

    class _BlockingManager(_FakeManager):
        def enable_plugin(self, plugin_id: str):
            operation_started.set()
            if not release_operation.wait(timeout=2):
                raise TimeoutError("Timed out waiting to release plugin lifecycle operation")
            return super().enable_plugin(plugin_id)

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
        request_task = asyncio.create_task(client.post("/api/plugins/core-tools/enable"))
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
    assert queue.refresh_channel_reasons == ["plugin_core-tools_enabled"]


def test_plugins_api_reads_plugin_settings_resources(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    client = TestClient(app)

    response = client.get("/api/plugins/core-tools/settings/resources/calendar_lists")

    assert response.status_code == 200
    payload = response.json()
    assert payload["plugin_id"] == "core-tools"
    assert payload["resource_name"] == "calendar_lists"
    assert payload["resource_type"] == "collection"
    assert payload["data"]["groups"][0]["items"][0]["item_id"] == "calendar-personal"
    # Phase 4: the resource route additionally resolves any ``*_i18n_key`` references
    # in the payload, which involves looking up the plugin package to find its i18n
    # bundle. That extra ``get_package`` call is expected and harmless when no keys match.
    assert manager.calls == [
        "get:core-tools",
        "resource:core-tools:calendar_lists",
        "get:core-tools",
    ]


def test_plugins_api_runs_plugin_settings_actions(monkeypatch):
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api/plugins")
    manager = _FakeManager()
    queue = _FakeRuntimeQueue()
    monkeypatch.setattr("magi.api.routers.plugins_common.resolve_plugin_manager", lambda: manager)
    monkeypatch.setattr(
        "magi.api.routers.plugins_core_routes.require_runtime_command_queue", lambda: queue
    )
    client = TestClient(app)

    start_response = client.post(
        "/api/plugins/core-tools/settings/actions/qr_login/start",
        json={"field_values": {"state_dir": "/tmp/magi"}},
    )
    assert start_response.status_code == 200
    assert start_response.json()["session_id"] == "session-1"
    assert start_response.json()["status"] == "pending"
    assert start_response.json()["data"]["qr_code_url"].startswith("data:image/png")

    poll_response = client.post(
        "/api/plugins/core-tools/settings/actions/qr_login/sessions/session-1/poll",
        json={"field_values": {"state_dir": "/tmp/magi"}},
    )
    assert poll_response.status_code == 200
    assert poll_response.json()["status"] == "succeeded"
    assert poll_response.json()["settings_updates"] == {"account_id": "account-1"}

    cancel_response = client.post(
        "/api/plugins/core-tools/settings/actions/qr_login/sessions/session-1/cancel",
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    assert manager.calls == [
        "get:core-tools",
        "start_action:core-tools:qr_login:{'state_dir': '/tmp/magi'}",
        "get:core-tools",
        "poll_action:core-tools:qr_login:session-1:{'state_dir': '/tmp/magi'}",
        "get:core-tools",
        "cancel_action:core-tools:qr_login:session-1",
    ]
    assert queue.refresh_channel_reasons == ["plugin_core-tools_settings_action_qr_login_succeeded"]


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
