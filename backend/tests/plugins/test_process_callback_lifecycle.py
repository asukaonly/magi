"""Host callbacks must settle before an invocation or connection is released."""

import asyncio

import pytest

from magi_plugin_sdk.runtime import CapabilityGrant
from magi_plugin_sdk.tools import ToolExecutionContext
from magi.plugins.process_broker import CapabilityBroker
from magi.plugins.process_runtime import ProcessPluginProxy, PluginProcessError, ProcessLimits
from test_process_runtime import plugin_setup  # noqa: F401


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
