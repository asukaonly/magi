"""Host callbacks must settle before an invocation or connection is released."""

import asyncio
import threading
import time
from pathlib import Path

import pytest

from magi_plugin_sdk.runtime import CapabilityGrant
from magi_plugin_sdk.tools import ToolExecutionContext
from magi.plugins.process_broker import CapabilityBroker
from magi.plugins.process_runtime import ProcessPluginProxy, PluginProcessError, ProcessLimits
from magi.plugins.process_runtime import PluginProcessTimeout
from test_process_runtime import PLUGIN, plugin_setup as plugin_setup


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "shutdown", "crash"])
async def test_host_side_effect_is_cancelled_and_cleanup_is_drained(plugin_setup, tmp_path, stop):
    manifest, connection, context = plugin_setup
    entered, cleaned = asyncio.Event(), asyncio.Event()
    marker = tmp_path / "late-side-effect"
    broker = CapabilityBroker(connection, (CapabilityGrant(
        grant_id="echo", connection_id=connection.connection_id,
        capability="test.echo", scopes=["allowed"],
    ),))

    async def echo(identity, resource, payload):
        entered.set()
        try:
            await asyncio.sleep(0.4)
            marker.write_text("must not execute after revocation")
        finally:
            await asyncio.sleep(0.03)
            cleaned.set()

    broker.register("test.echo", echo)
    proxy = ProcessPluginProxy(*plugin_setup, broker=broker, limits=ProcessLimits(drain_timeout=0.5))
    task = asyncio.create_task(proxy.get_tools()[0]().execute({}, ToolExecutionContext(agent_id="caller")))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        if stop == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif stop == "crash":
            with pytest.raises(PluginProcessError):
                await proxy.read_settings_resource_async("crash")
            await proxy.shutdown()
        else:
            await proxy.shutdown()
        assert cleaned.is_set(), "Shutdown/cancellation must await actual callback cleanup"
        assert not proxy._host_callbacks
        await asyncio.sleep(0.45)
        assert not marker.exists()
    finally:
        await asyncio.gather(task, return_exceptions=True)
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_failure_handler_excludes_intentional_shutdown_and_reports_late_binding(plugin_setup):
    proxy = ProcessPluginProxy(*plugin_setup)
    seen = []
    proxy.set_failure_handler(seen.append)
    await proxy.shutdown()

    assert seen == []
    proxy = ProcessPluginProxy(*plugin_setup)
    with pytest.raises(PluginProcessError):
        await proxy.read_settings_resource_async("crash")
    proxy.set_failure_handler(seen.append)
    assert len(seen) == 1
    proxy._terminate("Second failure")
    assert len(seen) == 1
    await proxy.shutdown()


@pytest.mark.asyncio
async def test_synchronous_credential_callback_finishes_before_cancellation_returns(plugin_setup):
    _manifest, _connection, context = plugin_setup
    entered, completed = threading.Event(), threading.Event()

    def delete(key):
        entered.set()
        time.sleep(0.15)
        context.credentials.values.pop(key, None)
        completed.set()

    context.credentials.delete = delete
    proxy = ProcessPluginProxy(*plugin_setup)
    task = asyncio.create_task(proxy.start_settings_action("credential", session_id="s"))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set()
    finally:
        await proxy.shutdown()


def test_sync_request_timeout_also_drains_credential_callbacks(plugin_setup):
    manifest, _connection, context = plugin_setup
    Path(manifest.plugin_dir, "plugin.py").write_text(PLUGIN + '''
    def read_settings_resource(self, resource_name):
        self.context.credentials.delete("boot")
        return None
''')
    completed = threading.Event()

    def delete(key):
        time.sleep(0.25)
        context.credentials.values.pop(key, None)
        completed.set()

    context.credentials.delete = delete
    proxy = ProcessPluginProxy(*plugin_setup, limits=ProcessLimits(request_timeout=0.1))
    try:
        with pytest.raises(PluginProcessTimeout):
            proxy.read_settings_resource("credential")
        assert completed.is_set()
    finally:
        proxy._terminate()
