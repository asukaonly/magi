"""Real-worker conformance for the external plugin boundary."""

import asyncio
from dataclasses import dataclass
import io
import os
import struct
import sys

import pytest

from magi_plugin_sdk.context import PluginContext
from magi_plugin_sdk.contracts import PluginManifest
from magi_plugin_sdk.runtime import CapabilityGrant, PluginConnection, SourceChangeBatch
from magi_plugin_sdk.sensors import SensorSyncContext
from magi_plugin_sdk.tools import ToolExecutionContext
from magi_plugin_sdk.transport import ProtocolError, decode, encode, pack, read_frame
from magi.plugins.process_broker import CapabilityBroker
from magi.plugins.process_confinement import ConfinementUnavailable, plan_confinement
from magi.plugins.process_runtime import (
    ProcessLimits,
    PluginProcessError,
    ProcessPluginProxy,
    PluginProcessTimeout,
)

PLUGIN = """
import asyncio, os, sys, time
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.sensors import SensorBase, SensorSpec
from magi_plugin_sdk.runtime import SourceChange, SourceChangeBatch
from magi_plugin_sdk.tools import Tool, ToolSchema, ToolResult
from magi_plugin_sdk.worker import get_host
os.environ["MAGI_TEST_CHILD_IMPORT"] = "only-child"
print("plugin stdout must not corrupt protocol")
os.write(1, b"native stdout must not corrupt protocol\\n")
class Source(SensorBase):
    source_type = "process_test"
    supports_pull_sync = True
    async def collect_items(self, context):
        return SourceChangeBatch(changes=[SourceChange(object_id="item", version="1", payload={"pid":os.getpid(), "connection_id":context.connection_id, "path":str(context.runtime_paths.plugin_cache_dir("another-package"))})], next_cursor="next")
    async def build_output(self, item):
        raise NotImplementedError("Fixture does not normalize")
class EchoTool(Tool):
    def _init_schema(self):
        self.schema=ToolSchema(name="process_echo", description="Echo", category="test", parameters=[])
    async def execute(self, parameters, context):
        value = await get_host().call("test.echo", parameters.get("resource", "allowed"), {"agent":context.agent_id})
        return ToolResult(success=True, data=value)
class TestPlugin(Plugin):
    def configure(self, **kwargs):
        super().configure(**kwargs)
        self.context.credentials.set("boot", "worker-value")
        self.boot_secret = self.context.credentials.get("boot")
    def get_sensors(self):
        return [("process_test", Source(), SensorSpec(sensor_id="process_test", display_name="Test", description="Test", domain="timeline"))]
    def get_tools(self):
        return [EchoTool]
    def read_settings_resource(self, resource_name):
        if resource_name == "crash": os._exit(17)
        if resource_name == "huge": return "x" * (5*1024*1024)
        if resource_name == "block": time.sleep(60)
        if resource_name == "dependency":
            import worker_private_dep
            return worker_private_dep.VALUE
        if resource_name == "host-import":
            try: import magi
            except ImportError: return False
            return True
        return {"pid":os.getpid(), "boot":self.boot_secret, "env":os.environ.get("MAGI_TEST_SECRET"), "paths":sys.path}
    async def start_settings_action(self, action_id, **kwargs):
        if action_id == "slow": await asyncio.sleep(60)
        if action_id == "ignore":
            try: await asyncio.sleep(60)
            except asyncio.CancelledError: await asyncio.sleep(60)
        if action_id == "credential":
            self.context.credentials.delete("boot")
            return {"value":self.context.credentials.get("boot")}
        return {"status":"succeeded"}
"""


class Credentials:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def plugin_setup(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "plugin.py").write_text(PLUGIN)
    deps = package / ".deps"
    deps.mkdir()
    (deps / "worker_private_dep.py").write_text('VALUE = "child-only dependency"')
    manifest = PluginManifest(
        id="process-test",
        name="Process test",
        version="0.2.0",
        entry_class="TestPlugin",
        plugin_dir=str(package),
        manifest_path=str(package / "plugin.toml"),
        execution_mode="trusted_process",
    )
    connection = PluginConnection(
        connection_id="connection-a",
        plugin_id=manifest.plugin_id,
        display_name="Test",
        enabled=True,
    )
    context = PluginContext(connection, tmp_path / "state", tmp_path / "resources", Credentials())
    return manifest, connection, context


@pytest.fixture
def proxy(plugin_setup, monkeypatch):
    monkeypatch.setenv("MAGI_TEST_SECRET", "must-not-leak")
    instance = ProcessPluginProxy(*plugin_setup)
    yield instance
    instance._terminate()


def test_typed_codec_roundtrip_and_no_arbitrary_classes():
    value = SourceChangeBatch(next_cursor="cursor")
    assert read_frame(io.BytesIO(pack({"value": value}))) == {"value": value}
    with pytest.raises(ProtocolError):
        decode({"type": "os.system", "value": "unsafe"})

    @dataclass
    class LocalType:
        secret: str

    with pytest.raises(ProtocolError):
        encode(LocalType("private"))
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(struct.pack("!I", 50_000_000)))
    with pytest.raises(ProtocolError):
        encode(float("nan"))


def test_real_child_imports_dependencies_and_scoped_boot_credentials(proxy):
    result = proxy.read_settings_resource("info")
    assert result["pid"] != os.getpid()
    assert result["boot"] == "worker-value"
    assert result["env"] is None
    assert os.environ.get("MAGI_TEST_CHILD_IMPORT") is None
    assert "worker_private_dep" not in sys.modules
    assert proxy.read_settings_resource("dependency") == "child-only dependency"
    assert proxy.read_settings_resource("host-import") is False
    assert proxy.context.credentials.get("boot") == "worker-value"
    assert proxy.diagnostics["healthy"] is True
    assert proxy.diagnostics["filesystem_confined"] is False


@pytest.mark.asyncio
async def test_sensor_and_settings_real_async_calls(proxy):
    _, sensor, _ = proxy.get_sensors()[0]
    assert sensor.connection == proxy.connection
    context = SensorSyncContext(
        connection_id=proxy.connection.connection_id,
        source_type="process_test",
        manual=True,
        last_cursor=None,
        last_success_at=None,
        limit=10,
        runtime_paths=object(),
    )
    result = await sensor.collect_items(context)
    assert isinstance(result, SourceChangeBatch)
    assert result.changes[0].payload["connection_id"] == proxy.connection.connection_id
    assert result.changes[0].payload["path"] == str(proxy.context.state_dir)
    assert await proxy.start_settings_action("credential", session_id="session") == {"value": None}
    await proxy.shutdown()
    assert proxy.diagnostics["exit_code"] is not None


@pytest.mark.asyncio
async def test_broker_preserves_host_identity_and_enforces_scope(plugin_setup):
    manifest, connection, context = plugin_setup
    grant = CapabilityGrant(
        grant_id="grant",
        connection_id=connection.connection_id,
        capability="test.echo",
        scopes=["allowed"],
    )
    broker = CapabilityBroker(connection, (grant,))
    seen = []

    async def echo(identity, resource, payload):
        seen.append(identity)
        return {"scope": resource, "principal": identity.principal_id, "payload": payload}

    broker.register("test.echo", echo)
    proxy = ProcessPluginProxy(manifest, connection, context, broker=broker)
    try:
        tool = proxy.get_tools()[0]()
        result = await tool.execute({}, ToolExecutionContext(agent_id="real-agent", task_id="task"))
        assert result.data["principal"] == "real-agent"
        assert seen[0].connection_id == connection.connection_id
        with pytest.raises(PluginProcessError, match="RemoteHostError"):
            await tool.execute(
                {"resource": "forbidden"}, ToolExecutionContext(agent_id="real-agent")
            )
        broker.revoke("grant")
        with pytest.raises(PluginProcessError):
            await tool.execute({}, ToolExecutionContext(agent_id="real-agent"))
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_crash_contained_and_rejects_new_work(proxy):
    with pytest.raises(PluginProcessError):
        await proxy.read_settings_resource_async("crash")
    assert not proxy.diagnostics["healthy"]
    with pytest.raises(PluginProcessError):
        proxy.read_settings_resource("info")


@pytest.mark.asyncio
async def test_timeout_kills_noncooperative_sync_work(plugin_setup):
    proxy = ProcessPluginProxy(
        *plugin_setup, limits=ProcessLimits(request_timeout=0.2, cancellation_grace=0.1)
    )
    try:
        with pytest.raises(PluginProcessTimeout):
            await proxy.read_settings_resource_async("block")
        await asyncio.sleep(0.3)
        assert not proxy.diagnostics["healthy"]
        assert proxy.diagnostics["exit_code"] is not None
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_oversized_response_is_contained(proxy):
    with pytest.raises(PluginProcessError, match="ProtocolError"):
        await proxy.read_settings_resource_async("huge")
    assert proxy.read_settings_resource("info")["pid"] != os.getpid()


def test_restricted_unsupported_platform_fails_closed(tmp_path):
    with pytest.raises(ConfinementUnavailable):
        plan_confinement(
            [sys.executable],
            mode="restricted_process",
            read_roots=(),
            state_dir=tmp_path / "state",
            resources_dir=tmp_path / "resources",
            platform="win32",
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt requires macOS")
def test_real_macos_restricted_worker(plugin_setup):
    manifest, connection, context = plugin_setup
    manifest = manifest.model_copy(update={"execution_mode": "restricted_process"})
    proxy = ProcessPluginProxy(manifest, connection, context)
    try:
        assert proxy.diagnostics["filesystem_confined"] is True
        assert proxy.diagnostics["network_confined"] is True
        assert proxy.read_settings_resource("info")["boot"] == "worker-value"
    finally:
        proxy._terminate()


@pytest.mark.asyncio
async def test_cooperative_cancellation_keeps_worker_healthy(proxy):
    task = asyncio.create_task(proxy.start_settings_action("slow", session_id="session"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(proxy.limits.cancellation_grace + 0.1)
    assert proxy.diagnostics["healthy"]
    assert proxy.diagnostics["pending"] == 0


@pytest.mark.asyncio
async def test_cancellation_ignoring_plugin_is_terminated(plugin_setup):
    proxy = ProcessPluginProxy(*plugin_setup, limits=ProcessLimits(cancellation_grace=0.1))
    task = asyncio.create_task(proxy.start_settings_action("ignore", session_id="session"))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.3)
    assert not proxy.diagnostics["healthy"]
    await proxy.shutdown()


@pytest.mark.asyncio
async def test_shutdown_drains_and_rejects_new_work(plugin_setup):
    proxy = ProcessPluginProxy(*plugin_setup, limits=ProcessLimits(drain_timeout=0.1))
    task = asyncio.create_task(proxy.start_settings_action("ignore", session_id="session"))
    await asyncio.sleep(0.02)
    shutdown = asyncio.create_task(proxy.shutdown())
    await asyncio.sleep(0)
    with pytest.raises(PluginProcessError, match="not accepting"):
        await proxy.read_settings_resource_async("info")
    await shutdown
    with pytest.raises(PluginProcessError):
        await task
    assert proxy.diagnostics["exit_code"] is not None


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt requires macOS")
def test_restricted_denies_file_symlink_network_and_subprocess(plugin_setup, tmp_path):
    manifest, connection, context = plugin_setup
    secret = tmp_path / "ungranted-secret"
    secret.write_text("secret")
    context.state_dir.mkdir()
    (context.state_dir / "escape").symlink_to(secret)
    source = (
        PLUGIN
        + """
    def read_settings_resource(self, resource_name):
        import socket, subprocess
        result = {}
        for key,path in [("outside", %r), ("symlink", str(self.context.state_dir / "escape"))]:
            try: open(path).read(); result[key]=True
            except PermissionError: result[key]=False
        try:
            with socket.socket() as sock: sock.connect(("127.0.0.1", 80))
            result["network"]=True
        except PermissionError: result["network"]=False
        try:
            subprocess.run(["/bin/sh", "-c", "exit 0"], check=True)
            result["subprocess"]=True
        except (PermissionError, subprocess.CalledProcessError): result["subprocess"]=False
        return result
"""
        % str(secret)
    )
    (tmp_path / "package" / "plugin.py").write_text(source)
    manifest = manifest.model_copy(update={"execution_mode": "restricted_process"})
    proxy = ProcessPluginProxy(manifest, connection, context)
    try:
        assert proxy.read_settings_resource("probe") == {
            "outside": False,
            "symlink": False,
            "network": False,
            "subprocess": False,
        }
    finally:
        proxy._terminate()


@pytest.mark.asyncio
async def test_operations_hooks_and_provider_streams_use_public_types(plugin_setup, tmp_path):
    from magi_plugin_sdk.hooks import HookContext, HookEventType, HookOutcome
    from magi_plugin_sdk.providers import (
        ModelRequest,
        ModelResult,
        ExternalAgentRequest,
        ExternalAgentResult,
    )
    from magi_plugin_sdk.runtime import InvocationIdentity

    manifest, connection, context = plugin_setup
    source = PLUGIN.replace(
        "class TestPlugin(Plugin):",
        """
from magi_plugin_sdk.hooks import HookDecision
from magi_plugin_sdk.providers import ModelEvent, ModelResult, ExternalAgentEvent, ExternalAgentResult
from magi_plugin_sdk.runtime import OperationSpec, OperationResult
class ModelProvider:
    async def invoke(self, request):
        return ModelResult(content=request.model)
    async def stream(self, request):
        try:
            yield ModelEvent(kind="text",delta="first")
            yield ModelEvent(kind="completed", result=ModelResult(content="complete"))
        finally:
            os.environ["STREAM_CLOSED"]="yes"
class ExternalProvider:
    async def invoke(self, request):
        return ExternalAgentResult(status="succeeded",summary=request.prompt)
    async def stream(self, request):
        yield ExternalAgentEvent(kind="stdout",payload={"text":"progress"})
        yield ExternalAgentEvent(kind="completed",result=ExternalAgentResult(status="succeeded"))
class WebProvider:
    def is_ready(self, config): return True
    async def execute(self, parameters, config): return {"query":parameters["query"]}
class TestPlugin(Plugin):
    def get_providers(self):
        return [("model","test-model",ModelProvider()),("external_agent","test-agent",ExternalProvider()),("web_search","test-web",WebProvider())]
    def get_operations(self):
        return [OperationSpec(operation_id="echo",description="Echo",input_schema={"type":"object"},output_schema={},triggers=["user"],effect="read_only",replay="read_only")]
    async def invoke_operation(self, operation_id, arguments, identity):
        return OperationResult(status="succeeded",value={"principal":identity.principal_id})
    def get_hooks(self):
        async def handler(context):
            return HookDecision.deny("Fixture denied " + context.tool_name)
        return [("PreToolUse",handler,None)]
""",
    )
    (tmp_path / "package" / "plugin.py").write_text(source)
    proxy = ProcessPluginProxy(manifest, connection, context)
    identity = InvocationIdentity(
        invocation_id="invocation",
        plugin_id=manifest.plugin_id,
        connection_id=connection.connection_id,
        principal_id="principal",
        trigger="user",
    )
    try:
        assert proxy.get_operations()[0].operation_id == "echo"
        result = await proxy.invoke_operation("echo", {}, identity)
        assert result.value == {"principal": "principal"}
        decision = await proxy.get_hooks()[0][1](
            HookContext(event_type=HookEventType.PRE_TOOL_USE, tool_name="test")
        )
        assert decision.outcome == HookOutcome.DENY
        providers = {kind: obj for kind, _, obj in proxy.get_providers()}
        model_request = ModelRequest(identity=identity, model="fixture", messages=[])
        assert isinstance(await providers["model"].invoke(model_request), ModelResult)
        stream = providers["model"].stream(model_request)
        assert (await anext(stream)).delta == "first"
        await stream.aclose()
        events = [event async for event in providers["model"].stream(model_request)]
        assert [event.kind for event in events] == ["text", "completed"]
        agent_request = ExternalAgentRequest(
            identity=identity, prompt="fixture", workspace=str(context.state_dir)
        )
        assert isinstance(
            await providers["external_agent"].invoke(agent_request), ExternalAgentResult
        )
        assert [
            event.kind async for event in providers["external_agent"].stream(agent_request)
        ] == ["stdout", "completed"]
        assert providers["web_search"].is_ready({})
        assert await providers["web_search"].execute({"query": "fixture"}, {}) == {
            "query": "fixture"
        }
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_channel_callbacks_and_clear_boundary_in_real_worker(plugin_setup, tmp_path):
    from magi_plugin_sdk.channels import ChannelTarget, ChannelInboundClearRequest
    from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt

    manifest, connection, context = plugin_setup
    source = PLUGIN.replace(
        "class TestPlugin(Plugin):",
        """
from contextlib import asynccontextmanager
from magi_plugin_sdk.channels import Channel, ChannelInboundClearStrategy, ChannelProviderTimeEvidence
from magi_plugin_sdk.delivery import DeliveryReceipt
class TestChannel(Channel):
    channel_type="fixture-channel"
    inbound_clear_strategy=ChannelInboundClearStrategy.PROVIDER_TIME
    def bind_message_dispatcher(self, dispatcher): self.dispatcher=dispatcher
    async def start(self):
        self.generation=await self.dispatcher.read_current_clear_generation()
    async def stop(self): pass
    async def send_message(self,target,content): pass
    async def send_typing_indicator(self,target): pass
    async def deliver(self,target,content):
        return DeliveryReceipt(channel_id=self.channel_type,external_message_id=str(self.generation),delivered_at_ms=1)
    @asynccontextmanager
    async def inbound_clear_boundary(self,request):
        self.generation=request.clear_generation
        yield
class TestPlugin(Plugin):
    def get_channel(self): return TestChannel()
""",
    )
    (tmp_path / "package" / "plugin.py").write_text(source)
    proxy = ProcessPluginProxy(manifest, connection, context)

    class Dispatcher:
        async def read_current_clear_generation(self):
            return 7

    class Mapper:
        async def lookup(self, channel_type, external_chat_id):
            from magi_plugin_sdk.channels import ChannelSessionMapping

            return ChannelSessionMapping(
                channel_type=channel_type,
                external_chat_id=external_chat_id,
                magi_session_id="own-session",
                magi_user_id="own-user",
            )

        async def lookup_by_session(self, session_id):
            from magi_plugin_sdk.channels import ChannelSessionMapping

            return ChannelSessionMapping(
                channel_type="foreign:fixture-channel",
                external_chat_id="other",
                magi_session_id=session_id,
                magi_user_id="foreign-user",
            )

    channel = proxy.get_channel()
    channel.bind_message_dispatcher(Dispatcher())
    channel.bind_session_mapper(Mapper())
    try:
        await channel.start()
        assert channel.channel_type == connection.connection_id + ":fixture-channel"
        mapped = await asyncio.to_thread(
            proxy._channel_callback,
            {
                "port": "session_mapper",
                "method": "lookup",
                "args": ("fixture-channel", "chat"),
                "kwargs": {},
            },
        )
        assert mapped.channel_type == "fixture-channel"
        assert proxy._channel_sessions["own-session"].channel_type == channel.channel_type
        from magi.plugins.process_broker import CapabilityDenied

        with pytest.raises(CapabilityDenied, match="another connection"):
            await asyncio.to_thread(
                proxy._channel_callback,
                {
                    "port": "session_mapper",
                    "method": "lookup_by_session",
                    "args": ("foreign-session",),
                    "kwargs": {},
                },
            )
        with pytest.raises(PermissionError, match="another connection"):
            await channel.deliver(
                ChannelTarget(channel_type="foreign:fixture-channel", external_chat_id="other"),
                DeliveryContent(text="blocked"),
            )
        receipt = await channel.deliver(
            ChannelTarget(channel_type=channel.channel_type, external_chat_id="chat"),
            DeliveryContent(text="hello"),
        )
        assert isinstance(receipt, DeliveryReceipt)
        assert receipt.external_message_id == "7"
        assert receipt.channel_id == channel.channel_type
        async with channel.inbound_clear_boundary(
            ChannelInboundClearRequest(channel_type=channel.channel_type, clear_generation=8)
        ):
            receipt = await channel.deliver(
                ChannelTarget(channel_type=channel.channel_type, external_chat_id="chat"),
                DeliveryContent(text="hello"),
            )
            assert receipt.external_message_id == "8"
        await channel.stop()
    finally:
        await proxy.shutdown()


def test_declared_library_resolution_excludes_sibling_packages(plugin_setup, tmp_path):
    manifest, connection, context = plugin_setup
    library = tmp_path / "libraries" / "selected_library"
    library.mkdir(parents=True)
    (library / "__init__.py").write_text('VALUE="selected"')
    sibling = library.parent / "unselected_library"
    sibling.mkdir()
    (sibling / "__init__.py").write_text('VALUE="forbidden"')
    source = (
        PLUGIN
        + """
    def read_settings_resource(self, name):
        import selected_library
        try: import unselected_library
        except ImportError: return selected_library.VALUE
        raise RuntimeError("Unselected library was imported")
"""
    )
    (tmp_path / "package" / "plugin.py").write_text(source)
    proxy = ProcessPluginProxy(manifest, connection, context, dependency_paths=[library])
    try:
        assert proxy.read_settings_resource("libraries") == "selected"
        assert "selected_library" not in sys.modules
    finally:
        proxy._terminate()


@pytest.mark.asyncio
async def test_tool_progress_callback_stays_bound_to_host_invocation(plugin_setup, tmp_path):
    manifest, connection, context = plugin_setup
    source = PLUGIN.replace(
        'value = await get_host().call("test.echo", parameters.get("resource", "allowed"), {"agent":context.agent_id})',
        'await context.progress({"step":"working"}); value = {"done":True}',
    )
    (tmp_path / "package" / "plugin.py").write_text(source)
    proxy = ProcessPluginProxy(manifest, connection, context)
    progress = []

    async def publish(value):
        progress.append(value)

    try:
        tool = proxy.get_tools()[0]()
        result = await tool.execute(
            {}, ToolExecutionContext(agent_id="principal", progress=publish)
        )
        assert result.success and progress == [{"step": "working"}]
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_resource_and_source_broker_enforce_connection_and_emit_host_identity(
    plugin_setup, tmp_path
):
    from magi.plugins.process_broker import bind_source_services, CapabilityDenied
    from magi.awareness.source_store import SourceStore
    from magi_plugin_sdk.runtime import InvocationIdentity, SourceChange

    manifest, connection, context = plugin_setup
    capabilities = {
        "resources.create": [connection.connection_id],
        "resources.read": [connection.connection_id],
        "source.emit": ["process_test"],
    }
    grants = tuple(
        CapabilityGrant(
            grant_id="grant-" + str(index),
            connection_id=connection.connection_id,
            capability=key,
            scopes=value,
        )
        for index, (key, value) in enumerate(capabilities.items())
    )
    broker = CapabilityBroker(connection, grants)
    store = SourceStore(tmp_path / "source-store.db")
    emitted = []

    async def emit(envelope):
        emitted.append(envelope)
        return object()

    bind_source_services(
        broker,
        get_connection=lambda _: connection,
        source_store=store,
        emit_change=emit,
        source_types=frozenset({"process_test"}),
    )
    identity = InvocationIdentity(
        invocation_id="invocation",
        plugin_id=manifest.plugin_id,
        connection_id=connection.connection_id,
        principal_id="principal",
        trigger="ingress",
    )
    ref = await broker.invoke(
        identity,
        "resources.create",
        connection.connection_id,
        {"content": b"source content", "media_type": "text/plain"},
    )
    assert (
        await broker.invoke(identity, "resources.read", connection.connection_id, ref)
        == b"source content"
    )
    change = SourceChange(object_id="object", version="version", resources=[ref])
    assert await broker.invoke(identity, "source.emit", "process_test", {"change": change}) == {
        "accepted": True
    }
    assert emitted[0]["connection_id"] == connection.connection_id
    with pytest.raises(CapabilityDenied):
        await broker.invoke(
            identity, "source.emit", "process_test", {"change": change, "connection_id": "another"}
        )
    with pytest.raises(CapabilityDenied):
        await broker.invoke(
            identity,
            "resources.read",
            connection.connection_id,
            ref.model_copy(update={"connection_id": "another"}),
        )


def test_venv_runtime_paths_work_without_site_startup(tmp_path):
    from magi.plugins.process_runtime import _interpreter_paths
    import subprocess

    executable = tmp_path / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(tmp_path / "venv")], check=True
    )
    paths = _interpreter_paths(str(executable))
    assert all(str(tmp_path / "venv") in path for path in paths["paths"])


@pytest.mark.asyncio
async def test_host_can_grant_after_catalog_but_not_duplicate_foreign_or_closed(plugin_setup):
    from magi.plugins.process_broker import CapabilityDenied
    from magi_plugin_sdk.runtime import InvocationIdentity

    _, connection, _ = plugin_setup
    broker = CapabilityBroker(connection)
    broker.register("source.emit", lambda identity, resource, payload: payload)
    identity = InvocationIdentity(
        invocation_id="invoke",
        plugin_id=connection.plugin_id,
        connection_id=connection.connection_id,
        principal_id="principal",
        trigger="system",
    )
    grant = CapabilityGrant(
        grant_id="later",
        connection_id=connection.connection_id,
        capability="source.emit",
        scopes=["owned-source"],
    )
    with pytest.raises(CapabilityDenied):
        await broker.invoke(identity, "source.emit", "owned-source", {})
    with pytest.raises(CapabilityDenied):
        broker.grant(grant.model_copy(update={"connection_id": "another"}))
    broker.grant(grant)
    assert await broker.invoke(identity, "source.emit", "owned-source", {"ok": True}) == {
        "ok": True
    }
    grant.scopes.append("injected-after-grant")
    with pytest.raises(CapabilityDenied):
        await broker.invoke(identity, "source.emit", "injected-after-grant", {})
    with pytest.raises(ValueError, match="already registered"):
        broker.grant(grant)
    broker.close()
    with pytest.raises(CapabilityDenied):
        broker.grant(grant.model_copy(update={"grant_id": "new"}))
