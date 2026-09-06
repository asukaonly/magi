from __future__ import annotations

from magi.events.plugin_ingress import PluginIngressEventHandler as BackendPluginIngressEventHandler
from magi.events.plugin_ingress import PluginIngressEventRecord as BackendPluginIngressEventRecord
from magi.events.plugin_ingress import PluginIngressHandlerRegistration as BackendPluginIngressHandlerRegistration
from magi.plugins import Plugin
from magi.runtime_trace import StoredPluginIngressEventRecord
from magi_plugin_sdk.ingress import PluginIngressEventHandler as SdkPluginIngressEventHandler
from magi_plugin_sdk.ingress import PluginIngressEventRecord as SdkPluginIngressEventRecord
from magi_plugin_sdk.ingress import PluginIngressHandlerRegistration as SdkPluginIngressHandlerRegistration


class StubIngressEvent:
    event_id = 1
    source_kind = "source"
    producer = "example_producer"
    plugin_target = "example_target"
    event_type = "example_event"
    occurred_at_ms = 1234567890
    payload_json = "{}"
    cursor_key = None
    status = "pending"
    claimed_by = None
    claimed_at_ms = None
    processed_at_ms = None
    last_error = None
    created_at_ms = 1234567890


class StubIngressHandler:
    async def handle_event(self, event: StubIngressEvent, payload: dict[str, object]) -> None:
        _ = event, payload


def test_backend_ingress_contracts_reexport_sdk_symbols() -> None:
    assert BackendPluginIngressEventHandler is SdkPluginIngressEventHandler
    assert BackendPluginIngressEventRecord is SdkPluginIngressEventRecord
    assert BackendPluginIngressHandlerRegistration is SdkPluginIngressHandlerRegistration


def test_runtime_trace_keeps_storage_record_alias() -> None:
    record = StoredPluginIngressEventRecord(
        event_id=1,
        source_kind="source",
        producer="example_producer",
        plugin_target="example_target",
        event_type="example_event",
        occurred_at_ms=1234567890,
    )

    assert record.payload_json == "{}"


def test_ingress_protocols_accept_structural_plugin_types() -> None:
    handler = StubIngressHandler()
    event = StubIngressEvent()

    assert isinstance(handler, SdkPluginIngressEventHandler)
    assert isinstance(event, SdkPluginIngressEventRecord)

    plugin = Plugin()
    assert plugin.get_plugin_ingress_registrations(runtime_paths=object()) == []

    registration = SdkPluginIngressHandlerRegistration(
        plugin_target="example_target",
        event_type="example_event",
        handler=handler,
    )
    assert registration.plugin_target == "example_target"