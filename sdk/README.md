# magi-plugin-sdk

Lightweight SDK for building [Magi](https://github.com/asukaonly/magi) plugins.

Install this package when developing external plugins — it contains only the
plugin contracts (`Plugin`, `SensorSpec`, `ExtensionFieldSpec`, …) and has a
single dependency: `pydantic`.  You do **not** need the full Magi backend.

## Installation

```bash
pip install magi-plugin-sdk
```

## Quick start

```python
# plugin.py
from magi_plugin_sdk import ExtensionFieldSpec, Plugin, SensorSpec, get_logger


logger = get_logger(__name__)


class MyPlugin(Plugin):
    def get_tools(self):
        return [MyTool]

    def get_sensors(self):
        from .sensor import MySensor
        return [MySensor()]
```

```toml
# plugin.toml
[plugin]
id = "my-plugin"
name = "My Plugin"
version = "0.1.0"
entry_module = "plugin"
entry_class = "MyPlugin"
contribution_types = ["tool", "sensor"]
```

## Import compatibility

When the full Magi backend is installed, `magi.plugins` re-exports everything
from this SDK.  Both import paths resolve to the **same classes**:

```python
from magi_plugin_sdk import Plugin     # recommended for external plugins
from magi.plugins import Plugin        # also works (requires magi backend)
```

For existing plugins migrating off backend internals, use these replacements:

| Legacy import / pattern | Preferred replacement |
| --- | --- |
| `magi.core.logger.get_logger` | `magi_plugin_sdk.get_logger` |
| `magi.runtime_trace.PluginIngressEventRecord` | `magi_plugin_sdk.ingress.PluginIngressEventRecord` |
| `magi.api.services.message_dispatch_service.dispatch_user_message` in channel adapters | injected `ChannelMessageDispatcherProtocol.dispatch_user_message(...)` |
| `magi.channels.session_mapper.ChannelSessionMapper` for adapter typing | injected `ChannelSessionMapperProtocol` |

## Public API

| Symbol | Description |
|--------|-------------|
| `Plugin` | Base class for all plugin packages |
| `SensorSpec` | Declarative metadata for a sensor contribution |
| `SensorBase` | Base class for sensor implementations |
| `SensorSyncContext` | Pull-sync context passed to sensors |
| `SensorSyncResult` | Pull-sync result returned by sensors |
| `ExtensionFieldSpec` | Declarative settings field |
| `ExtensionFieldOption` | Option entry for select-type fields |
| `ActivationFlowSpec` | First-enable wizard spec |
| `Channel` | Base class for channel adapters |
| `ChannelInboundClearStrategy` | Required channel admission strategy declaration |
| `ChannelProviderTimeEvidence` | Provider-issued event-time admission proof |
| `ChannelCursorClearProof` | Durable cursor-generation admission proof |
| `ChannelInboundClearRequest` | Host request passed to external channel clear hooks |
| `ChannelInboundContext` | Host-issued context reused for every inbound mutation |
| `ChannelTarget` | Normalized outbound channel target |
| `OutboundContent` | Normalized outbound message payload |
| `ChannelSessionMapperProtocol` | Injected channel session-mapping host contract |
| `ChannelMessageDispatcherProtocol` | Injected inbound message dispatch host contract |
| `ChannelMessageDispatchOutcome` | Result returned by the host dispatcher |
| `PluginIngressHandlerRegistration` | Static ingress routing registration |
| `PluginIngressEventRecord` | Host-provided ingress event envelope protocol |
| `SettingsUIBlockSpec` | Custom settings block spec |
| `PluginSettingsResourceSpec` | Read-only settings resource |
| `PluginSettingsResourcePayload` | Resolved resource payload |
| `PluginSettingsActionSpec` | Host-rendered settings action spec |
| `PluginSettingsActionResult` | Settings action session result |
| `ContributionType` | Enum: `tool`, `sensor`, `channel` |
| `PluginManifest` | Parsed `plugin.toml` manifest model |
| `PluginContribution` | Runtime contribution descriptor |
| `PluginPackageState` | Runtime state for a plugin package |
| `PluginI18n` | Per-plugin translation helper |
| `get_current_language` | Read the active context language |
| `set_current_language` | Set the active context language |
| `get_logger` | Lightweight stdlib logger helper for plugin code |
| `configure_basic_logging` | Install a minimal default logging config when needed |

## Destructive-clear-safe channel ingress

Every registered channel must explicitly declare one inbound clear strategy:

- `INTERNAL` for host-owned channels that do not accept external inbound work
- `PROVIDER_TIME` when the platform supplies a trustworthy event occurrence time
- `DURABLE_CURSOR` for polling streams that can replay backlog without such a time

Before any session mapping, command, attachment, or chat dispatch, call
`capture_inbound_context` with the channel type, a stable upstream stream ID,
and exactly one evidence object. A provider timestamp must come from the
provider; local receipt or polling time is not valid evidence. Pass the returned
context unchanged through every host call for that event.

Every external channel must implement `inbound_clear_boundary`. Entering the
context is local-only: pause ingress, clear buffered events and transport
message maps, and durably record the requested host generation. It must never
wait for the provider network and must be idempotent because the host invokes it
during an active clear and may invoke it again before startup.

Provider-time channels can resume after context exit; events without a valid
provider time are terminally rejected. Cursor channels persist the generation
as pending and remain paused. They reconcile the remote cursor asynchronously,
then mark the generation applied and only then resume polling and use it in
`ChannelCursorClearProof`. `dispatcher.read_current_clear_generation()` lets a
plugin finish missed local preparation before it starts any ingress loop.

See `docs/plugin-development-guide.md` in the main repo for the full guide.
