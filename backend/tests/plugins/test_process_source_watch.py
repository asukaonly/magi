"""Persistent source subscriptions carry revocable host-owned authority."""

import asyncio
from pathlib import Path

import pytest

from magi_plugin_sdk.runtime import CapabilityGrant
from magi_plugin_sdk.sources import SourceSyncContext
from magi.plugins.process_broker import CapabilityBroker, CapabilityDenied
from magi.plugins.process_runtime import ProcessPluginProxy, PluginProcessError
from test_process_runtime import PLUGIN, plugin_setup  # noqa: F401


WATCH = '''
async def watch(self, context, emitter):
    try:
        await asyncio.sleep(0.05)
        await emitter.emit(SourceChange(object_id="watch-1", version="1", payload={"value":1}))
        await asyncio.Event().wait()
    finally:
        (self.context.state_dir / "watch-stopped").write_text("stopped")
Source.supports_watch_mode = True
Source.watch = watch
'''


def watch_context(proxy):
    return SourceSyncContext(
        connection_id=proxy.connection_id, source_type="process_test", manual=False,
        last_cursor=None, last_success_at=None, limit=100, runtime_paths=object(),
    )


@pytest.mark.asyncio
async def test_watch_outlives_start_request_but_not_its_subscription(plugin_setup):
    manifest, connection, context = plugin_setup
    context.state_dir.mkdir()
    Path(manifest.plugin_dir, "plugin.py").write_text(PLUGIN + WATCH)
    emitted = asyncio.Event()
    observed = []
    broker = CapabilityBroker(connection, (CapabilityGrant(
        grant_id="source", connection_id=connection.connection_id,
        capability="source.emit", scopes=["process_test"],
    ),))

    async def emit(identity, resource, payload):
        observed.append((identity, resource, payload))
        emitted.set()
        return {"accepted": True}

    broker.register("source.emit", emit)
    proxy = ProcessPluginProxy(*plugin_setup, broker=broker)
    _, source, _ = proxy.get_sources()[0]
    try:
        await source.start_watch(watch_context(proxy))
        assert not proxy._pending
        old_lease = next(iter(proxy._source_leases))
        await asyncio.wait_for(emitted.wait(), 2)
        identity, resource, payload = observed[0]
        assert identity.connection_id == connection.connection_id
        assert identity.trigger == "system"
        assert resource == "process_test"
        assert payload["change"].object_id == "watch-1"
        await source.stop_watch()
        assert (context.state_dir / "watch-stopped").is_file()
        with pytest.raises(CapabilityDenied):
            proxy._source_callback(old_lease, {"method": "emit", "value": payload["change"]})
        await source.start_watch(watch_context(proxy))
        assert old_lease not in proxy._source_leases
        await proxy.shutdown()
        assert not proxy._host_callbacks
        assert not proxy._source_leases
    finally:
        await proxy.shutdown()


@pytest.mark.asyncio
async def test_watcher_failure_fails_connection(plugin_setup):
    manifest, connection, context = plugin_setup
    Path(manifest.plugin_dir, "plugin.py").write_text(PLUGIN + '''
async def watch(self, context, emitter):
    await asyncio.sleep(0.05)
    raise RuntimeError("watcher failed")
Source.supports_watch_mode = True
Source.watch = watch
''')
    proxy = ProcessPluginProxy(*plugin_setup)
    failed = asyncio.Event()
    loop = asyncio.get_running_loop()
    proxy.set_failure_handler(lambda reason: loop.call_soon_threadsafe(failed.set))
    try:
        await proxy.get_sources()[0][1].start_watch(watch_context(proxy))
        await asyncio.wait_for(failed.wait(), 2)
        assert not proxy.diagnostics["healthy"]
        with pytest.raises(PluginProcessError):
            await proxy.read_settings_resource_async("info")
    finally:
        await proxy.shutdown()
