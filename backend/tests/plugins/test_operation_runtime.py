from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from magi_plugin_sdk.runtime import (
    CapabilityReadiness,
    OperationResult,
    OperationSpec,
    PluginConnection,
    ResourceRef,
)
from magi_plugin_sdk.tools import ToolExecutionContext
from magi.agent.background import BackgroundTaskStore
from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.domain_payloads import TaskContext
from magi.plugins.operations import PluginOperationRegistry
from magi.plugins.operation_authorization import (
    InstalledOperationAuthorizer,
    build_host_invocation,
)
from magi.tools.registry import ToolRegistry


def spec(**updates):
    values = dict(
        operation_id="send",
        description="Send a test payload",
        input_schema={
            "type": "object",
            "properties": {"payload": {"type": "integer"}},
            "required": ["payload"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"receipt": {"type": "string"}},
            "required": ["receipt"],
            "additionalProperties": False,
        },
        triggers=["user", "model"],
        effect="external_write",
        replay="non_idempotent",
    )
    values.update(updates)
    return OperationSpec(**values)


@pytest.fixture
def setup(runtime_paths_with_schema):
    connections = {
        "conn_a": PluginConnection(
            connection_id="conn_a", plugin_id="test", display_name="A", enabled=True
        ),
        "conn_b": PluginConnection(
            connection_id="conn_b", plugin_id="test", display_name="B", enabled=True
        ),
    }
    tools = ToolRegistry()
    ledger = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    tools.bind_tool_effect_ledger(ledger)
    registry = PluginOperationRegistry(
        tools,
        get_connection=connections.get,
        authorize=lambda *_: True,
        publish_progress=AsyncMock(),
        validate_resource=lambda *_: True,
    )
    return registry, tools, ledger, connections


@pytest.mark.asyncio
async def test_same_host_ledger_handles_ui_and_model_invocations(setup):
    registry, tools, ledger, connections = setup
    handler = AsyncMock(return_value=OperationResult(status="succeeded", value={"receipt": "ok"}))
    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=handler)
    identity = build_host_invocation(connections["conn_a"], trigger="user", task_id="task")
    result = await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    assert result.status == "succeeded"
    repeated = await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    assert repeated.error_code == "TOOL_EFFECT_ALREADY_COMPLETED"
    assert handler.await_count == 1
    model = await ToolInvocationService(tools).invoke(
        ToolCall("conn_a:send", {"payload": 2}),
        InvocationContext(
            "plugin",
            TaskContext("session", "turn", "task", "local_user"),
            ToolExecutionContext(agent_id="agent"),
        ),
    )
    assert model.success
    assert handler.await_args.args[1].invocation.trigger == "model"
    assert handler.await_args.args[1].connection.connection_id == "conn_a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,arguments,code",
    [
        ({"connection_id": "conn_b"}, {"payload": 1}, "INVOCATION_IDENTITY_INVALID"),
        ({"trigger": "schedule"}, {"payload": 1}, "TRIGGER_NOT_ALLOWED"),
        ({}, {"payload": True}, "INVALID_PARAMETERS"),
        ({}, {"payload": 1, "principal_id": "local_user"}, "INVALID_PARAMETERS"),
    ],
)
async def test_admission_rejects_before_handler(setup, mutation, arguments, code):
    registry, _, _, connections = setup
    handler = AsyncMock()
    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=handler)
    identity = build_host_invocation(connections["conn_a"], trigger="user").model_copy(
        update=mutation
    )
    result = await registry.invoke("conn_a", "send", arguments, identity=identity)
    assert result.error_code == code
    handler.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "bad_output", "exception"])
async def test_external_effect_uncertainty_blocks_replay(setup, mode):
    registry, _, _, connections = setup

    async def execute(*_):
        if mode == "timeout":
            await asyncio.sleep(10)
        if mode == "exception":
            raise RuntimeError("private provider error")
        return OperationResult(status="succeeded", value={"receipt": 42})

    handler = AsyncMock(side_effect=execute)
    registry.register(
        plugin_id="test",
        connection_id="conn_a",
        spec=spec(timeout_seconds=0.01),
        handler=handler,
    )
    identity = build_host_invocation(connections["conn_a"], trigger="user")
    result = await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    assert result.status == "uncertain"
    retry = await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    assert retry.error_code == "TOOL_EFFECT_UNCERTAIN"
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_cancellation_and_resources_are_not_reported_as_success(setup):
    registry, _, _, connections = setup
    started = asyncio.Event()

    async def execute(*_):
        started.set()
        await asyncio.Event().wait()

    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=execute)
    identity = build_host_invocation(connections["conn_a"], trigger="user")
    task = asyncio.create_task(registry.invoke("conn_a", "send", {"payload": 1}, identity=identity))
    await started.wait()
    task.cancel()
    assert (await task).status == "uncertain"
    assert (
        await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    ).error_code == "TOOL_EFFECT_UNCERTAIN"


@pytest.mark.asyncio
async def test_progress_and_resource_validation(setup):
    registry, _, _, connections = setup

    async def execute(_, context):
        await context.progress({"message": "halfway", "fraction": 0.5})
        return OperationResult(
            status="succeeded",
            value={"receipt": "done"},
            resources=[
                ResourceRef(
                    resource_id="r1",
                    connection_id="conn_b",
                    media_type="text/plain",
                    size_bytes=1,
                    version="v1",
                )
            ],
        )

    registry.register(
        plugin_id="test",
        connection_id="conn_a",
        spec=spec(effect="read_only", replay="read_only"),
        handler=execute,
    )
    result = await registry.invoke(
        "conn_a",
        "send",
        {"payload": 1},
        identity=build_host_invocation(connections["conn_a"], trigger="user"),
    )
    assert result.error_code == "INVALID_OPERATION_OUTPUT"
    registry._publish_progress.assert_awaited_once()
    assert registry._publish_progress.await_args.args[0].connection_id == "conn_a"


def test_duplicate_registration_and_stale_disposer(setup):
    registry, tools, _, _ = setup
    old = registry.register(
        plugin_id="test", connection_id="conn_a", spec=spec(), handler=AsyncMock()
    )
    with pytest.raises(ValueError):
        registry.register(
            plugin_id="test", connection_id="conn_a", spec=spec(), handler=AsyncMock()
        )
    old()
    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=AsyncMock())
    old()
    assert tools.get_tool("conn_a:send") is not None


@pytest.mark.asyncio
async def test_missing_authorizer_and_disabled_connection_fail_closed(setup):
    registry, _, _, connections = setup
    registry._authorize = None
    handler = AsyncMock()
    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=handler)
    identity = build_host_invocation(connections["conn_a"], trigger="user")
    assert (
        await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    ).error_code == "PERMISSION_DENIED"
    connections["conn_a"] = connections["conn_a"].model_copy(update={"enabled": False})
    assert (
        await registry.invoke("conn_a", "send", {"payload": 1}, identity=identity)
    ).error_code == "CONNECTION_DISABLED"
    handler.assert_not_awaited()


def test_installed_authorizer_live_identity_consent_and_scope():
    connection = PluginConnection(
        connection_id="conn_a", plugin_id="test", display_name="A", enabled=True
    )
    capability = SimpleNamespace(capability="network", scope=["example.test"], optional=False)
    package = SimpleNamespace(
        trusted=True,
        manifest=SimpleNamespace(
            source="user",
            execution_mode="restricted_process",
            capabilities=[capability],
            settings_actions=[],
            settings_resources=[],
        ),
    )
    config = SimpleNamespace(
        plugins=SimpleNamespace(
            packages={"test": SimpleNamespace(trusted=True, consented_capabilities=[capability])}
        )
    )
    store = SimpleNamespace(
        get=lambda _: connection,
        get_readiness=lambda _: [
            CapabilityReadiness(connection_id="conn_a", capability_id="connection", status="ready")
        ],
    )
    authorizer = InstalledOperationAuthorizer(
        get_package=lambda _: package,
        connection_store=store,
        get_connection_plugin=lambda _: object(),
        config_provider=lambda: config,
    )
    identity = build_host_invocation(connection, trigger="user")
    assert authorizer(identity, connection, spec(), {}) is False
    authorizer._supported_scopes = {"network": frozenset({"example.test"})}
    assert authorizer(identity, connection, spec(), {}) is True
    assert (
        authorizer(
            identity.model_copy(update={"principal_id": "attacker"}),
            connection,
            spec(),
            {},
        )
        is False
    )
    config.plugins.packages["test"].consented_capabilities = []
    assert authorizer(identity, connection, spec(), {}) is False


@pytest.mark.parametrize(
    "capability,scope",
    [
        ("network", ["https://example.test"]),
        ("filesystem_read", ["~/Documents"]),
        ("subprocess", ["native-helper"]),
    ],
)
def test_trusted_process_consent_does_not_claim_broker_confinement(capability, scope):
    connection = PluginConnection(
        connection_id="conn_a", plugin_id="test", display_name="A", enabled=True
    )
    request = SimpleNamespace(capability=capability, scope=scope, optional=False)
    package = SimpleNamespace(
        trusted=True,
        manifest=SimpleNamespace(
            source="user", execution_mode="trusted_process", capabilities=[request]
        ),
    )
    configured = SimpleNamespace(trusted=True, consented_capabilities=[request])
    config = SimpleNamespace(plugins=SimpleNamespace(packages={"test": configured}))
    store = SimpleNamespace(
        get=lambda _: connection,
        get_readiness=lambda _: [
            CapabilityReadiness(connection_id="conn_a", capability_id="connection", status="ready")
        ],
    )
    authorizer = InstalledOperationAuthorizer(
        get_package=lambda _: package,
        connection_store=store,
        get_connection_plugin=lambda _: object(),
        config_provider=lambda: config,
    )
    identity = build_host_invocation(connection, trigger="user")
    assert authorizer(identity, connection, spec(), {}) is True
    package.manifest.execution_mode = "restricted_process"
    assert authorizer(identity, connection, spec(), {}) is False
    package.manifest.execution_mode = "trusted_process"
    configured.trusted = False
    assert authorizer(identity, connection, spec(), {}) is False
    configured.trusted = True
    configured.consented_capabilities = []
    assert authorizer(identity, connection, spec(), {}) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("token_kind", ["code_agent", "runtime"])
async def test_cooperative_cancellation_and_progress_are_revoked(setup, token_kind):
    from magi.tools.code_agent.adapters.base import CancelToken
    from magi.control.cancel import EventCancelToken

    registry, _, _, connections = setup
    started = asyncio.Event()
    contexts = []

    async def handler(_, context):
        contexts.append(context)
        started.set()
        await asyncio.Event().wait()

    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=handler)
    token = CancelToken() if token_kind == "code_agent" else EventCancelToken()
    task = asyncio.create_task(
        registry.invoke(
            "conn_a",
            "send",
            {"payload": 1},
            identity=build_host_invocation(connections["conn_a"], trigger="user"),
            context=ToolExecutionContext(agent_id="test", cancellation=token),
        )
    )
    await started.wait()
    token.cancel()
    assert (await asyncio.wait_for(task, 1)).status == "uncertain"
    with pytest.raises(PermissionError):
        await contexts[0].progress({"message": "late"})


@pytest.mark.asyncio
async def test_serialized_model_names_resolve_the_exact_connection_and_expire(setup):
    import json
    import re
    from magi.agent.execution.function_calling.tools import build_tools_parameter
    from magi.control.cancel import null_cancel_token

    registry, tools, _, connections = setup
    calls = []

    async def handler(_, context):
        calls.append(context.connection.connection_id)
        return OperationResult(status="succeeded", value={"receipt": "done"})

    dispose = registry.register(
        plugin_id="test", connection_id="conn_a", spec=spec(), handler=handler
    )
    registry.register(plugin_id="test", connection_id="conn_b", spec=spec(), handler=handler)
    exported = json.loads(json.dumps(build_tools_parameter(tools, ["conn_a:send", "conn_b:send"])))
    aliases = {
        tools.resolve_tool_name(item["function"]["name"]): item["function"]["name"]
        for item in exported
    }
    assert len(set(aliases.values())) == 2
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) for name in aliases.values())
    assert aliases == {
        tools.resolve_tool_name(item["function"]["name"]): item["function"]["name"]
        for item in build_tools_parameter(tools, ["conn_b:send", "conn_a:send"])
    }
    response = {
        "tool_calls": [
            {
                "id": "call",
                "type": "function",
                "function": {"name": aliases["conn_b:send"], "arguments": '{"payload":1}'},
            }
        ]
    }
    function = response["tool_calls"][0]["function"]
    result = await ToolInvocationService(tools).invoke(
        ToolCall(function["name"], json.loads(function["arguments"])),
        InvocationContext(
            "plugin",
            TaskContext("session", "turn", "task", "local_user"),
            ToolExecutionContext(agent_id="agent", cancellation=null_cancel_token()),
        ),
    )
    assert result.success and calls == ["conn_b"]
    claude_names = {item["name"] for item in tools.export_to_claude_format()}
    assert set(aliases.values()) <= claude_names
    dispose()
    assert tools.get_tool(aliases["conn_a:send"]) is None
    assert aliases["conn_a:send"] not in tools._tool_aliases
    assert tools.get_tool(aliases["conn_b:send"]) is not None


def test_model_alias_cannot_shadow_builtin_registration(setup):
    import hashlib
    from magi_plugin_sdk.tools import Tool, ToolSchema

    registry, tools, _, _ = setup
    collision = "magi_" + hashlib.sha256(b"conn_a:send").hexdigest()[:59]

    class Builtin(Tool):
        def _init_schema(self):
            self.schema = ToolSchema(name=collision, description="Builtin", category="test")

        async def execute(self, parameters, context):
            raise AssertionError("Not executed")

    tools.register(Builtin)
    registry.register(plugin_id="test", connection_id="conn_a", spec=spec(), handler=AsyncMock())
    alias = tools.exported_tool_name("conn_a:send")
    assert alias != collision
    assert tools.resolve_tool_name(collision) == collision
    with pytest.raises(ValueError):
        tools.register(Builtin, registered_name=alias)
