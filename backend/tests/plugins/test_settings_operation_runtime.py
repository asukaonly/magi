from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from magi_plugin_sdk.contracts import (
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourceSpec,
)
from magi_plugin_sdk.runtime import CapabilityReadiness, OperationSpec, PluginConnection

from magi.agent.background import BackgroundTaskStore
from magi.plugins.operation_authorization import (
    InstalledOperationAuthorizer,
    build_host_invocation,
)
from magi.plugins.operations import PluginOperationRegistry
from magi.plugins.settings_service import PluginSettingsService
from magi.tools.registry import ToolRegistry


@pytest.fixture
def settings_runtime(runtime_paths_with_schema):
    connection = PluginConnection(
        connection_id="setup", plugin_id="test", display_name="Account", enabled=False
    )
    connections = {"setup": connection}
    actions = [
        PluginSettingsActionSpec(
            action_id="login", label="Login", requires_enabled=False
        ),
        PluginSettingsActionSpec(action_id="refresh", label="Refresh"),
    ]
    resources = [
        PluginSettingsResourceSpec(resource_name="qr", requires_enabled=False),
        PluginSettingsResourceSpec(resource_name="private"),
    ]
    manifest = SimpleNamespace(
        source="user",
        execution_mode="trusted_process",
        capabilities=[],
        settings_actions=actions,
        settings_resources=resources,
    )
    package = SimpleNamespace(trusted=True, manifest=manifest)
    config = SimpleNamespace(
        plugins=SimpleNamespace(
            packages={"test": SimpleNamespace(trusted=True, consented_capabilities=[])}
        )
    )
    store = SimpleNamespace(
        get=connections.__getitem__,
        get_readiness=lambda _: [
            CapabilityReadiness(
                connection_id="setup", capability_id="connection", status="ready"
            )
        ],
    )
    plugin = SimpleNamespace(
        invoke_settings_action=AsyncMock(
            return_value=PluginSettingsActionResult(status="pending")
        ),
        read_settings_resource_async=AsyncMock(
            return_value={"qr": "data:image/png;base64,AAA"}
        ),
    )
    setup_plugin = Mock(return_value=plugin)
    authorizer = InstalledOperationAuthorizer(
        get_package=lambda _: package,
        connection_store=store,
        get_connection_plugin=lambda _: (
            plugin if connections["setup"].enabled else None
        ),
        config_provider=lambda: config,
    )
    tools = ToolRegistry()
    tools.bind_tool_effect_ledger(
        BackgroundTaskStore(
            db_path=str(runtime_paths_with_schema.background_tasks_db_path)
        )
    )
    operations = PluginOperationRegistry(
        tools, get_connection=connections.__getitem__, authorize=authorizer
    )
    service = PluginSettingsService(
        get_connection=connections.__getitem__,
        get_connection_plugin=lambda _: (
            plugin if connections["setup"].enabled else None
        ),
        operation_registry=operations,
        update_connection_settings=Mock(),
        get_package=lambda _: package,
        get_setup_plugin=setup_plugin,
    )
    return service, operations, connections, plugin, package, authorizer, setup_plugin


@pytest.mark.asyncio
async def test_disabled_setup_actions_use_exact_host_identity_and_shared_runtime(
    settings_runtime,
):
    service, operations, connections, plugin, package, authorizer, resolver = (
        settings_runtime
    )
    identity = build_host_invocation(connections["setup"], trigger="user")
    assert authorizer.authorize_setup_connection(connections["setup"])
    started = await service.start_plugin_settings_action(
        "setup", "login", identity=identity
    )
    assert started.result.status == "pending"
    assert plugin.invoke_settings_action.await_args.kwargs["identity"] == identity
    result = await operations.invoke(
        "setup",
        "settings:login:start",
        {"session_id": started.session_id, "field_values": {}},
        identity=identity,
    )
    assert result.error_code == "TOOL_EFFECT_ALREADY_COMPLETED"
    assert plugin.invoke_settings_action.await_count == 1
    model = identity.model_copy(
        update={"trigger": "model", "invocation_id": "model-attempt"}
    )
    with pytest.raises(PermissionError):
        await service.start_plugin_settings_action("setup", "login", identity=model)
    with pytest.raises(PermissionError):
        await service.start_plugin_settings_action(
            "setup", "refresh", identity=identity
        )
    package.manifest.settings_actions = []
    with pytest.raises(KeyError):
        await service.poll_plugin_settings_action(
            "setup",
            "login",
            session_id=started.session_id,
            identity=build_host_invocation(connections["setup"], trigger="user"),
        )
    service.unregister_connection("setup")
    assert (
        await operations.invoke("setup", "settings:login:start", {}, identity=identity)
    ).error_code == "OPERATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_resources_are_async_and_pre_enable_access_is_catalog_limited(
    settings_runtime,
):
    service, _, connections, plugin, _, _, resolver = settings_runtime
    result = await service.read_plugin_settings_resource("setup", "qr")
    assert result.data["qr"].startswith("data:")
    identity = plugin.read_settings_resource_async.await_args.kwargs["identity"]
    assert identity.principal_id == "local_user" and identity.trigger == "user"
    assert identity.connection_id == "setup"
    resolver.reset_mock()
    with pytest.raises(PermissionError):
        await service.read_plugin_settings_resource("setup", "private")
    with pytest.raises(KeyError):
        await service.read_plugin_settings_resource("setup", "undeclared")
    resolver.assert_not_called()


@pytest.mark.asyncio
async def test_builtin_resource_callback_runs_off_the_event_loop(settings_runtime):
    service, _, connections, plugin, package, _, _ = settings_runtime
    connections["setup"] = connections["setup"].model_copy(update={"enabled": True})
    package.manifest.source = "builtin"
    del plugin.read_settings_resource_async
    plugin.get_settings_resources = lambda: [
        PluginSettingsResourceSpec(resource_name="thread")
    ]
    plugin.read_settings_resource = lambda _: threading.get_ident()
    result = await service.read_plugin_settings_resource("setup", "thread")
    assert result.data != threading.get_ident()


def test_disabled_registration_flag_cannot_authorize_an_arbitrary_operation(
    settings_runtime,
):
    _, _, connections, _, _, authorizer, _ = settings_runtime
    operation = OperationSpec(
        operation_id="send",
        description="Send",
        input_schema={"type": "object"},
        output_schema={},
        triggers=["user"],
        effect="external_write",
        replay="non_idempotent",
    )
    assert not authorizer.authorize_setup(
        build_host_invocation(connections["setup"], trigger="user"),
        connections["setup"],
        operation,
        {},
    )
