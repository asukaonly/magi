# Plugin Development Guide

## Purpose

This guide explains how to build a Magi plugin package with the current unified plugin runtime.

Use it when you want to:

- add a built-in extension under `plugins/`
- author an external plugin in a separate development scan directory
- contribute new tools, timeline sensors, or channels

## Prerequisites — Plugin SDK

All plugin contracts (`Plugin`, `SensorSpec`, `ExtensionFieldSpec`, …) live in the
**`magi-plugin-sdk`** package (`sdk/` in this repository).  Install it before
developing plugins:

```bash
# External plugin author — install from PyPI
pip install magi-plugin-sdk

# Working inside this monorepo — install in editable mode
pip install -e sdk/
```

`magi-plugin-sdk` depends only on `pydantic`.  You do **not** need the full Magi
backend runtime just to write or type-check a plugin.

For plugin-local logging, prefer the SDK helper instead of backend logging utilities:

```python
from magi_plugin_sdk import get_logger


logger = get_logger(__name__)
```

This keeps plugin code portable when only `magi-plugin-sdk` is installed.

Use only `magi_plugin_sdk` in an external plugin. The host backend is not
installed in the plugin worker and is not an authoring dependency. The current
contract is SDK `0.2.0`, protocol `2`; there is no compatibility window.

## Authoring Surface

The SDK owns public models for tools, source changes, resources, channels,
hooks, skills, operations and providers. Host registries, database stores,
scheduling, final memory writes and frontend components remain private.
Unsupported declaration fields fail validation, including nested schemas.

Every connection has a separate plugin instance. The host calls
`configure(manifest=..., connection=..., context=...)` before use. Read settings
from `self.settings`, identity from `self.connection`, credentials from
`self.context.credentials`, private progress from `self.context.state_dir`, and
retained content from `self.context.resources_dir`. Do not derive paths from
HOME or a package name. Never read another connection's directory.

The install manifest must describe `settings_fields`, `activation_flow`,
`settings_actions`, `settings_resources` and `settings_ui_blocks` before code
runs. Keep schema declarations consistent with the implementation. A setup
action or resource must explicitly set `requires_enabled=false` to be available
on a disabled connection after package consent. This permits OAuth/QR setup
without starting collection or messaging.

## Quick Start

A plugin package is a directory with:

- `plugin.toml`
- `plugin.py`

Minimal example:

```text
my-plugin/
├── assets/
│   └── icon.svg
├── plugin.toml
└── plugin.py
```

## 1. Create `plugin.toml`

Example:

```toml
[plugin]
id = "example-plugin"
name = "Example Plugin"
version = "0.1.0"
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
description = "Sample Magi plugin package"
author = "Your Name"
icon = "lucide:package"
entry_module = "plugin"
entry_class = "ExamplePlugin"
official = false
contribution_types = ["tool", "sensor"]
```

Declare exactly the contribution types you actually expose. A mismatch is a
registration error. `trusted_process` requires explicit trust in native Python
code; it is not an operating-system sandbox. Restricted execution currently
requires verified macOS confinement and fails on unsupported platforms.

Use `history_importer` for a one-shot parser of a declared platform export. Do
not model a bounded archive as a sensor merely to reuse polling infrastructure;
an importer has user-selected input and a completed lifecycle, while a sensor
owns ongoing collection state.

### Plugin icons

Choose one of two icon forms:

- use `icon = "lucide:<icon-name>"` for a generic symbol bundled by the host
- use `icon = "asset:assets/icon.svg"` for a brand or product icon shipped with
  the plugin

Brand icons belong in the plugin package. This lets marketplace listings,
installation prompts, installed-plugin pages, and sensor rows use the same
image without adding brand-specific code to the host.

Packaged icons may be SVG, PNG, or WebP and must be no larger than 64 KiB. SVG
icons must be self-contained: scripts, embedded remote content, event handlers,
external links, and styles that load URLs are rejected during registry
generation and again when the host discovers the installed plugin. The desktop
also revalidates registry-embedded icon data before exposing it to the UI:
base64, size, image signatures, and SVG safety must all pass. Non-asset
fallbacks must use a short lowercase `lucide:<name>` identifier; invalid values
are dropped.

## 2. Implement the plugin class

Every plugin must inherit:

- [Plugin](../sdk/src/magi_plugin_sdk/base.py)

Example:

```python
from magi_plugin_sdk import Plugin


class ExamplePlugin(Plugin):
    def get_tools(self):
        return []

    def get_sensors(self):
        return []

    def get_settings_resources(self):
        return []
```

The runtime binds `self.manifest`, `self.connection`, `self.context` and a copy
of connection settings before registration. A package may have many instances.

### User-content clear contract

Every plugin and every `SensorBase` contribution inherits an async
`clear_user_content(context)` hook. The default implementation is an idempotent
no-op and is suitable only when that object retains no user content of its own.

Override the hook when the plugin or sensor keeps any local copy of raw source
items, prompts, queries, fetched bodies, generated results, derived indexes,
temporary files, pending batches, or background-run state. The host invokes both
the plugin-level and sensor-level hooks during **Clear all data**, including for
installed plugins that are currently disabled, so each hook must delete only
the files and records that object owns. A disabled plugin is instantiated only
for deletion and then shut down; it is not enabled and none of its contributions
are registered. If it contributes a channel, the host also enters that
channel's existing local-only `inbound_clear_boundary`; channel plugins must
keep that boundary idempotent and independent of provider availability.

```python
from magi_plugin_sdk import Plugin, UserContentClearContext


class ExamplePlugin(Plugin):
    async def clear_user_content(self, context: UserContentClearContext) -> None:
        cache_dir = context.runtime_paths.plugin_cache_dir(context.plugin_id)
        # Delete only this plugin's retained user-content files here.
```

The contract is deliberately narrow:

- deletion is local-only; the hook must never call a provider, revoke a remote
  account, or delete source data from the user's device or online service
- preserve the installed package, plugin configuration, credentials, connected
  account state, permissions, and source cursor/watermark
- treat `context.plugin_settings` as a recursively read-only snapshot captured
  before deletion; use it only to locate plugin-owned content
- make the hook safe to run more than once for the same generation, because a
  process interruption or one failing peer causes the whole generation to be
  replayed at the next safe opportunity
- stop or join plugin-owned background writers before returning; no task may
  recreate deleted content after the hook completes

The request's clear generation comes from the host's shared full-clear record.
Plugins must not create, persist, or compare a separate generation counter.

The `Plugin` base class also exposes safe no-op defaults for host-consumed optional hooks such as:

- `get_channel()`
- `get_channel_fields()`
- `get_settings_resources()`
- `read_settings_resource()`
- `get_settings_actions()`
- `start_settings_action()` / `poll_settings_action()` / `cancel_settings_action()`
- `build_temporal_summary_features()`
- `get_plugin_ingress_registrations()`

Only implement the hooks your package actually contributes.

## 3. Install the plugin in a scan path

Supported roots:

- built-in repository plugins: `plugins/`
- user plugins: `~/.magi/plugins/`

For local development, use an additional configured scan root outside the
managed install directory. An explicit local-directory install may also copy a
package into the managed root while recording it as a development package. Do
not manually place an unrecorded package under `~/.magi/plugins/`.

The managed user root has a strict layout: one direct child directory named
exactly after the plugin id, containing `plugin.toml` directly. Root-level
manifests, extra nesting, mismatched directory names, and symlinked package
directories are not treated as managed installs. Additional development scan
roots may be configured, but packages found there are source packages rather
than host-owned installs: Magi may load or disable them, but uninstall will not
delete their files. Remove the scan path or delete those files yourself.

## 4. Create And Enable A Connection

Rescan installed packages with `POST /api/plugins/rescan`. Create one account
with `POST /api/plugins/{plugin_id}/connections`, supplying `display_name`,
settings and write-only credentials. Run any declared setup actions on that
connection, then enable with `PATCH .../connections/{connection_id}` using its
current `expected_revision`.

The Settings page renders the same connection flow from the manifest. Package
installation and integrity records remain in host config; account settings and
credentials live under the selected runtime root's `plugin-connections/`.

### Package an archive for file installation

Use `.zip`, `.tar.gz`, or `.tgz`. The archive must have exactly one of these
shapes:

```text
plugin.toml
plugin.py
assets/...
```

or:

```text
my-plugin/
├── plugin.toml
├── plugin.py
└── assets/...
```

Do not add a second manifest, sibling files beside the single top-level plugin
directory, nested wrapper directories, links, device files, or other special
entries. File installation rejects ambiguous layouts and unsafe archive paths
before writing the package into the user plugin directory. Keep `plugin.toml`
at or below 256 KiB.

Keep `plugin.id` and every `depends_on` value between 1 and 64 characters and
use only lowercase ASCII letters, digits, `-`, and `_`. `entry_module` and
`entry_class` must each be one Python identifier, not a path or dotted import.
Do not use `index`, Windows device names such as `con`, `aux`, `nul`, or `prn`,
or numbered `com1`–`com9` and `lpt1`–`lpt9` names as a plugin id.

The desktop uploads a file-install package once, shows its declared access, and
then confirms that exact checked copy. Installation does not enable it. The
user must perform a separate enable action before its code runs, and it never
inherits settings from an older package record. File installation also refuses
to replace an installed or host-reserved package with the same id; updates must
use the managed update flow.

The same no-overwrite rule applies to local-directory installation.
Marketplace updates are source-bound: the current registry URL and repository
must exactly match the source that originally installed the package. To move a
plugin between registries, uninstall it first and then perform a fresh install.
An external package with the same id cannot inherit settings, access consent,
trust, or official status from another source.

`depends_on` is available only to marketplace-managed package graphs. Uploaded
archives and local-directory installs must keep it empty because those flows do
not provide one reviewed registry snapshot for every referenced package.
Sideloaded plugins must therefore be self-contained at the Magi package layer.
Use `dependencies` plus the generated `requirements.lock` for ordinary Python
libraries. A future multi-package sideload format would need to review and
install the complete graph atomically rather than weakening this rule.

## Declaring Access And Safe Dependencies

Every plugin should disclose the system and data access it needs. Declare one
entry per access type in `plugin.toml`:

```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"
scope = ["~/Documents"]
optional = false
reason_i18n = { en = "Read documents selected by the user", "zh-CN" = "读取用户选择的文档" }
```

Supported capability names are:

- `screen_recording`
- `accessibility`
- `calendar`
- `photos`
- `contacts`
- `system_media`
- `filesystem_read`
- `filesystem_write`
- `network`
- `subprocess`

Use `scope` to narrow file roots, network hosts, or executable names. Use
`optional = true` only when the plugin still works without that access. Keep the
English and Simplified Chinese reasons aligned because users see them before
installation.

These declarations are disclosure and review metadata, not a sandbox. They must
match what the plugin actually does. The companion plugin registry rejects
unknown capability names.

Official status is maintainer-owned. Setting `official = true` in an external
plugin manifest does not grant an official badge; the companion registry derives
that value from its reviewed `official-plugins.json` allowlist. The desktop
honors that unsigned result only for the canonical Magi registry URL and
canonical repository URL. Custom registries and mirrors are always
non-official.

For Magi package sharing, declare reusable code as a registry entry with
`kind = "library"` and reference its `plugin_id` through `depends_on`. A
user-selected entry must remain `kind = "plugin"`; every transitive dependency
must be a library, and libraries may depend only on other libraries. Cycles are
rejected. Keep each `depends_on` list at or below 8 entries and the complete
target closure at or below 16 packages.

The host binds every library to the approved registry snapshot and the
canonical digest of its complete contents. Do not assume an unrelated package
already present under the same id will be reused: its registry source,
repository, package digest, and nested dependency digests must all match.
Package tooling must calculate this digest through
`magi_plugin_sdk.package_identity`, which is the shared authority for framing,
profiles, streamed file records, and portable paths. Executable permission is
carried as `PackageFile.executable` publication metadata but deliberately does
not create a second content identity; published-version history separately
locks the sorted executable paths.
After dependency installation, the host also seals the complete local result,
including `.deps`, and verifies that local seal before code execution. Shared
libraries are removed
automatically only after their final installed consumer is removed.

When `dependencies` is non-empty, the distributed plugin must include a
generated `requirements.lock` with exact versions and hashes. In the companion
`magi-plugins` repository, refresh generated artifacts after every distributed
file change:

```bash
bash scripts/refresh.sh <plugin-directory>
```

Commit the refreshed lockfile, package digest history, and `registry.json` with
the package change. Do not hand-edit generated files. Once a plugin id and
version have been published, changing any packaged file without increasing the
version is rejected. Versions must use canonical numeric `MAJOR.MINOR.PATCH`
form; aliases, prerelease labels, and build suffixes are not accepted. A plugin
with dependencies but no lockfile is rejected
during normal installation. Each lock entry must be an ordinary
package name pinned to one exact version with SHA-256 hashes. Direct URLs,
local paths, editable installs, package-manager directives, version ranges,
and source-only distributions are rejected. Runtime installation accepts
prebuilt wheels only. Keep the manifest at or below 128 dependency declarations
and the generated lockfile at or below 1 MiB and 1,024 entries. Installation
also enforces a combined 256 MiB and 50,000-entry limit across its temporary
workspace and the plugin-local dependency directory. Installer output is
truncated to a bounded diagnostic tail, so lock generation and validation
must not depend on parsing unbounded install logs. A marketplace install also
shares a 512 MiB and 100,000-entry budget across every extracted package source
and dependency-install output in the complete package closure.

## Tool Plugins

Tool plugins return normal Magi tool classes from `get_tools()`.

Example:

```python
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.tools import Tool, ToolExecutionContext, ToolResult, ToolSchema


class HelloTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="hello-tool",
            description="Return a greeting.",
            category="utility",
            effect_replay_policy="read_only",
            parameters=[],
        )

    async def execute(self, parameters: dict, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(success=True, data={"message": "hello"})


class ExamplePlugin(Plugin):
    def get_tools(self):
        return [HelloTool]
```

Guidelines:

- treat tool implementations exactly like other Magi tools
- declare `effect_replay_policy` accurately. Use `read_only` only when repeated
  execution cannot mutate local or remote state; use `idempotent` when the
  operation itself is repeat-safe; use `idempotent_with_key` together with
  `effect_idempotency_key_parameter` when a provider key makes it repeat-safe;
  use `non_idempotent` when it must never replay automatically; and use
  `reconcilable` when external state can be checked before a later explicit
  retry. The default `unknown` is intentionally fail-closed after an ambiguous
  attempt
- when returning a failure before the tool body has produced any effect, set
  `ToolResult.metadata["effect_state"] = "none"`. When a remote effect is known
  committed even though the overall result is a failure, set it to
  `"committed"`. Omit the field when the outcome is ambiguous
- use the plugin only as the registration container
- if the tool needs settings, expose them through plugin contribution fields rather than custom frontend UI
- if a long-lived tool instance keeps user queries, prompts, fetched content,
  results, or background-run state, override `clear_user_content()` and erase
  that state there while preserving configuration and credentials. Normal
  `execute()` calls are sealed and drained before this hook runs, so tools must
  not launch untracked work that can write retained content after execution
  returns
- import tool contracts from `magi_plugin_sdk.tools`; external unknown effect/replay declarations are rejected before registration
- for plugin-local logging, use `magi_plugin_sdk.get_logger` rather than `magi.core.logger`

## Channel Plugins

Channel plugins return a configured channel adapter from `get_channel()` and declarative settings fields from `get_channel_fields()`.

Example:

```python
from contextlib import asynccontextmanager

from magi_plugin_sdk import ExtensionFieldSpec, Plugin
from magi_plugin_sdk.channels import (
    Channel,
    ChannelInboundClearStrategy,
    ChannelInboundClearRequest,
    ChannelMessageDispatcherProtocol,
    ChannelSessionMapperProtocol,
    ChannelTarget,
    OutboundContent,
)


class ExampleChannel(Channel):
    inbound_clear_strategy = ChannelInboundClearStrategy.PROVIDER_TIME

    def __init__(self) -> None:
        self._session_mapper: ChannelSessionMapperProtocol | None = None
        self._message_dispatcher: ChannelMessageDispatcherProtocol | None = None

    @property
    def channel_type(self) -> str:
        return "example"

    def bind_session_mapper(self, session_mapper: ChannelSessionMapperProtocol) -> None:
        self._session_mapper = session_mapper

    def bind_message_dispatcher(self, dispatcher: ChannelMessageDispatcherProtocol) -> None:
        self._message_dispatcher = dispatcher

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_message(self, target: ChannelTarget, content: OutboundContent) -> None:
        _ = target, content

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        _ = target

    @asynccontextmanager
    async def inbound_clear_boundary(self, request: ChannelInboundClearRequest):
        # This example keeps no local inbound cache. Real channels pause local
        # ingress and clear local transport state here, without network I/O.
        _ = request
        yield


class ExamplePlugin(Plugin):
    def get_channel(self) -> Channel | None:
        return ExampleChannel()

    def get_channel_fields(self) -> list[ExtensionFieldSpec]:
        return [
            ExtensionFieldSpec(
                key="channels.example.enabled",
                type="switch",
                label="Enabled",
                default=True,
                surface="extensions",
            )
        ]
```

Guidelines:

- prefer `magi_plugin_sdk.channels` for `Channel`, `ChannelTarget`, and related DTOs
- treat the injected session mapper as a host-provided dependency and type it as `ChannelSessionMapperProtocol`
- treat the injected inbound dispatcher as a host-provided dependency and type it as `ChannelMessageDispatcherProtocol`
- declare exactly one `ChannelInboundClearStrategy` on every channel. Use `INTERNAL` only for host-owned channels, `PROVIDER_TIME` only when the provider supplies a trustworthy event time, and `DURABLE_CURSOR` for polling streams that can replay backlog without such a time
- capture a host inbound context before creating mappings, handling commands, storing attachments, or dispatching chat. Capture requires the channel type, a stable account/polling-stream ID, and exactly one `ChannelProviderTimeEvidence` or `ChannelCursorClearProof`; pass the returned context unchanged to every host call for that event
- never substitute local poll, receipt, parsing, or queue time for provider occurrence time
- every external channel must implement `inbound_clear_boundary(request)`. Entering it must use local state only: pause ingress, clear buffered events plus transport context/message maps, and durably record `request.clear_generation`. It must never contact or wait for the provider, must be idempotent, and must keep ingress paused until at least context exit
- provider-time channels may resume after context exit; if a provider event omits or supplies an invalid occurrence time, reject it terminally instead of substituting local time
- durable-cursor channels must persist a local pending generation during the hook and remain paused after exit. Advance the provider-native cursor asynchronously when the provider is available, then atomically mark that generation applied; only the applied generation may be sent as `ChannelCursorClearProof`
- before starting any external ingress loop, compare local clear state with `await dispatcher.read_current_clear_generation()` and finish missed local preparation. A cursor poller must start provider reconciliation in the background rather than block channel or application startup while offline
- for inbound messages, pass stable transport identifiers in metadata as `external_chat_id` and `external_message_id`; also pass `account_id` when one channel type can have multiple connected accounts. The host uses these fields to make transport retries idempotent even when the adapter does not provide `client_turn_id`. If the transport has no reliable per-message identifier, omit `external_message_id` rather than inventing one.
- an adapter-provided `client_turn_id` remains authoritative and must be stable, unique within the adapter's external message scope, and safe for storage (`A-Z`, `a-z`, `0-9`, `_`, `-`, at most 128 characters)
- stable message identity deduplicates retries that reach the current host
  conversation state; it is not a remote-history watermark. A full local clear
  deliberately removes channel mappings and delivery ledgers, so an old
  platform item delivered to Magi for the first time after that clear is
  indistinguishable from a new item by stable ID alone
- polling and backfill channels must persist their provider-native cursor and
  the matching host clear generation atomically; stable message IDs alone do
  not prove that remote backlog was crossed
- keep transport-specific SDKs inside the plugin package so the core SDK stays lightweight
- route inbound messages through the injected dispatcher instead of importing `magi.api.services.message_dispatch_service` directly
- channel contracts are imported only from `magi_plugin_sdk.channels`

## Plugin Settings Actions

Use settings actions when setup requires an imperative provider interaction that
plain fields cannot model, such as QR-code login, device-code authorization, or
connection testing.

Example:

```python
from magi_plugin_sdk import Plugin, PluginSettingsActionResult, PluginSettingsActionSpec


class ExamplePlugin(Plugin):
    def get_settings_actions(self) -> list[PluginSettingsActionSpec]:
        return [
            PluginSettingsActionSpec(
                action_id="qr_login",
                label="Scan Login",
                button_label="Start Login",
                presentation="qr_code",
                contribution_type="channel",
                persist_settings_on_success=True,
            )
        ]

    async def start_settings_action(self, action_id, *, session_id, field_values=None):
        if action_id != "qr_login":
            raise KeyError(action_id)
        return PluginSettingsActionResult(
            status="pending",
            message="Scan the QR code.",
            data={"qr_code_url": "data:image/png;base64,..."},
        )

    async def poll_settings_action(self, action_id, *, session_id, field_values=None):
        if action_id != "qr_login":
            raise KeyError(action_id)
        return PluginSettingsActionResult(
            status="succeeded",
            message="Connected.",
            settings_updates={"account_id": "example"},
        )
```

Guidelines:

- keep provider-specific protocol details inside the plugin package
- use `presentation="qr_code"` only when the returned `data` contains a QR image or URL
- return `status="pending"` for sessions that need frontend polling
- return only safe settings in `settings_updates`; do not echo secrets to the frontend
- set `persist_settings_on_success=True` when the host should save returned settings automatically

## Ingress Plugins

Ingress plugins register host-routed event handlers through `get_plugin_ingress_registrations()`.

Example:

```python
from magi_plugin_sdk import Plugin
from magi_plugin_sdk.ingress import (
    PluginIngressEventRecord,
    PluginIngressHandlerRegistration,
)
from magi_plugin_sdk.sensors import PluginRuntimePaths


class ExampleIngressHandler:
    def __init__(self, *, runtime_paths: PluginRuntimePaths) -> None:
        self._runtime_paths = runtime_paths

    async def handle_event(
        self,
        event: PluginIngressEventRecord,
        payload: dict[str, object],
    ) -> None:
        _ = event, payload, self._runtime_paths


class ExamplePlugin(Plugin):
    def get_plugin_ingress_registrations(
        self,
        *,
        runtime_paths: PluginRuntimePaths,
    ) -> list[PluginIngressHandlerRegistration]:
        return [
            PluginIngressHandlerRegistration(
                plugin_target="example",
                event_type="example_event",
                handler=ExampleIngressHandler(runtime_paths=runtime_paths),
            )
        ]
```

Guidelines:

- prefer `magi_plugin_sdk.ingress` for handler registrations and ingress event typing
- type `runtime_paths` as `PluginRuntimePaths`; current external ingress usage only needs `plugin_cache_dir(...)`
- keep event handlers host-agnostic; queue claiming, dispatch, and persistence stay in backend runtime modules
- ingress contracts are imported only from `magi_plugin_sdk.ingress`
- event typing uses `magi_plugin_sdk.ingress.PluginIngressEventRecord`; backend imports are not part of the external SDK

## History Importer Plugins

History importers return tuples from `get_history_importers()`:

- `importer_id`
- an async parser implementing `HistoryImporter`
- `HistoryImporterSpec`

The parser receives only host-validated user-selected paths and returns
`HistoryImportParseResult`. One archive may produce many independently selectable
`HistoryImportSource` values. `source_id`, `session_key`, and `message_key` must be
stable across later exports containing the same conversation; display names,
archive filenames, byte fingerprints, and list positions are not sufficient
message identities. Use `parent_message_key` when the export declares reply or
branch structure. Preserve missing/approximate time through
`timestamp_confidence` instead of manufacturing an exact timestamp.

The record timestamp contract is strict:

- `exact` and `inferred` both require `occurred_at`; use `inferred` when the
  export supplies a deterministic approximate time rather than an exact instant
- `source_order` and `unknown` require `occurred_at=None`; ordering metadata is
  not itself a timestamp
- the host may assign an internal ordering anchor to an untimed record, but it
  preserves the declared confidence and product surfaces must not render that
  anchor, or an `inferred` timestamp, as exact history

Participant identity is source-scoped by default. The host converts every
adapter `speaker_id` into an opaque participant ID that also includes the source
identity, so a local member ID reused by unrelated conversations cannot merge
people. Set `participant_identity_scope="export"` only when the declared export
format guarantees that one raw speaker ID has the same meaning across every
source in the selected export. Adapters must never use host-reserved participant
IDs such as `__document_author__`; platform sources are always persisted with
their explicit source kind rather than inferred from a speaker value.

The host owns the picker, preview, participant-to-user mapping, idempotency,
progress, retry, deletion, and memory writes. An importer must never write host
memory, choose the user's identity from a role label, or use an LLM to infer
speakers, ordering, timestamps, or missing messages. Unsupported content should
produce warnings and fail closed when structural identity is unavailable.

`display_name` and `description` are required fallback strings. Put translated
variants in `display_name_i18n` and `description_i18n` using bounded BCP 47-style
locale keys such as `en` and `zh-CN`. The host selects from these maps at render
time, so changing the application language does not require reloading the plugin.

The parser must return within the host deadline and keep its output inside the
SDK collection and text limits. It should bound warnings while parsing instead
of accumulating an unbounded list. The host runs every parser in a worker thread
(with a private event loop for an async parser) and admits at most two at once.
The deadline includes waiting for a worker slot; timing out does not forcibly
terminate Python code, and the occupied slot is not reused until `parse`
actually returns. The host verifies the selected files before and after `parse`,
so an importer must treat them as read-only and must not rewrite, extract beside,
or otherwise mutate the selected archive.

For an already imported session, a later export may reuse the existing stable
message-key prefix and append new messages. It must not insert, remove, or
reorder messages inside that prefix. Such a structurally revised export is a
replacement snapshot: the user must delete the earlier import before importing
the complete replacement.

Example:

```python
from pathlib import Path

from magi_plugin_sdk import (
    HistoryImporterSpec,
    HistoryImportParseResult,
    Plugin,
)


class ExampleArchiveImporter:
    async def parse(self, paths: list[Path]) -> HistoryImportParseResult:
        return parse_declared_export(paths)


class ExamplePlugin(Plugin):
    def get_history_importers(self):
        spec = HistoryImporterSpec(
            importer_id="example_export",
            display_name="Example history",
            display_name_i18n={"zh-CN": "示例历史"},
            description="Import an official account export.",
            description_i18n={"zh-CN": "导入官方账户导出文件。"},
            accepted_extensions=["zip", "json"],
            format_version="example-export-v1",
            export_help_url="https://example.com/export-help",
        )
        return [(spec.importer_id, ExampleArchiveImporter(), spec)]
```

## Sensor Plugins

Sensors return tuples from `get_sensors()`:

- `sensor_id`
- sensor instance
- `SensorSpec`

Example:

```python
from magi_plugin_sdk import ExtensionFieldSpec, Plugin, SensorSpec


class ExampleTimelineSensor:
    source_type = "example_source"

    def normalize(self, item):
        ...


class ExamplePlugin(Plugin):
    def get_sensors(self):
        sensor = ExampleTimelineSensor()
        spec = SensorSpec(
            sensor_id="timeline.example_source",
            display_name="Example Source",
            description="Example timeline sensor",
            domain="timeline",
            surface="timeline",
            sync_mode="interval",
            fields=[
                ExtensionFieldSpec(
                    key="sensors.example_source.enabled",
                    type="switch",
                    label="Enabled",
                    default=True,
                    surface="timeline",
                ),
            ],
            metadata={
                "source_type": "example_source",
                "default_settings": {
                    "enabled": True,
                    "sync_mode": "interval",
                },
            },
        )
        return [("timeline.example_source", sensor, spec)]
```

Guidelines:

- use `domain="timeline"` when you want the sensor to appear as a timeline source
- set `metadata.source_type` because sensor routing and scheduling use it
- provide a `default_settings` object when the contribution needs stable defaults
- store settings under a stable subtree such as `sensors.<source_name>.*`
- keep the sensor contribution visible when the source-level `enabled` setting is false; disabled sources should stay configurable in Settings, with runtime sync gated by the saved setting instead of disappearing from discovery
- when first enablement needs an OS permission prompt, expose an `activation_flow` and set `authorize_on_confirm=True`; the host will call the sensor authorization endpoint before flipping the source to enabled
- when a source needs lighter first-run behavior for onboarding, declare `activation_flow.first_context.max_items_per_sync` for its initial read cap and use `settings_overrides` for other settings that apply only in the first-context panel; the host uses 200 only as a safety fallback when the cap is absent
- opt into first-context or empty-source recommendations through `suggestion_descriptor.surfaces.first_context` or `suggestion_descriptor.surfaces.empty_state`; the plugin owns its name, icon, copy, scope, and order, so do not rely on the host frontend hardcoding the plugin id

### SensorBase Hooks

Sensors inheriting `SensorBase` from `magi_plugin_sdk.sensors` have access to the following hooks that control memory routing and L2 cognition behavior:

**Core contract:**

- `build_output(item)`: convert a source item into a domain-neutral `SensorOutput` (required)
- `extract_metadata(item)`: extract `SensorOutputMetadata` containing entity hints, tags, and relation candidates
- `collect_items(context)`: returns `SourceChangeBatch` with immutable object revisions, explicit upsert/delete changes, next cursor, watermark and stats. Use `build_change_batch()` when deriving revisions from normalized payloads; never reuse a revision for changed content.
- `fetch_item(item)`: optional pre-processing/enrichment before `build_output`
- `clear_user_content(context)`: remove sensor-owned local raw, derived, pending,
  and temporary content while preserving settings, credentials, connected
  accounts, and source progress. For plugin-managed state files, use
  `magi_plugin_sdk.fs.read_managed_text()`,
  `magi_plugin_sdk.fs.atomic_write_managed_text()`, and
  `magi_plugin_sdk.fs.remove_managed_file()` so clear hooks replace or remove
  links themselves instead of following them into user-owned files.

`SensorOutput` is now a source-truth contract, not a final display-string contract.

Required truth fields inside `SensorOutput`:

- `activity.source` / `activity.action`: stable semantic facets with `code` and `i18n_key`
- optional `activity.object`: optional semantic object facet when it materially changes retrieval or display
- optional `activity.qualifiers`: stable low-cardinality qualifiers such as capture mode or session type
- `narration.body`: factual event narration without host-owned source/action prefix
- optional `narration.title`: short source-owned headline that the host may reuse in timeline titles
- optional `timeline_presentation`: display policy for the primary timeline surface

Important ownership rule:

- plugins own `activity` and `narration` truth
- the host runtime owns final `L1` text, timeline title/summary, and embedding projection
- plugins should not pre-compose final `{source} {action} ...` display strings inside `narration.body`

`timeline_presentation` lets high-volume evidence sources keep the raw evidence
available without flooding the primary timeline:

- `full` (default): timeline summary and L1 content both use the host-rendered full narration
- `compact`: timeline summary uses the provided short `title` or `summary`; L1 content keeps the full narration
- `evidence_only`: same compact primary display, intended for raw evidence such as OCR, transcripts, or logs that should remain searchable and openable but not inline-expanded in the main timeline

For example, a screenshot sensor should put OCR/AX text in `narration.body` and
`content_blocks`, then set `timeline_presentation=TimelinePresentation(mode="evidence_only", title="App: Window")`.
The timeline will show the short app/window label, while search/detail paths can
still use the complete captured text.

Typical authoring pattern:

```python
return self._build_output(
    source_item_id="track:123",
    activity=self._build_activity(
        source=self._build_activity_facet(
            code="netease_music",
            i18n_key="activity.source.netease_music",
            fallback="NetEase Music",
            embedding_fallback="网易云音乐",
        ),
        action=self._build_activity_facet(
            code="listen_music",
            i18n_key="activity.action.listen_music",
            fallback="Listening",
            embedding_fallback="听歌",
        ),
    ),
    narration=self._build_narration(
        title="Track Name - Artist",
        body="在网易云音乐听了《Track Name》，播放了 3 分钟",
    ),
    occurred_at=occurred_at,
)
```

Use `fallback` for resilient display when a translation file is missing. Use `embedding_fallback` sparingly for a short dense-retrieval head; do not dump large alias lists or schema text into the event body.

**Dedup helpers:**

- `source_item_identity(item)`: producer-side stable item identity for dedup
- `source_item_version_fingerprint(item)`: content fingerprint to detect changes in already-seen items
- `idempotency_key(output)`: business-level idempotency key written to L1

**L2 cognition hooks:**

- `l2_batch_policy(output)`: return an `L2BatchPolicy` describing batching preferences:
  - `owner`: stable owner key for durable projection-job grouping (e.g., `chrome_history:Default:github.com`)
  - `catch_up_owner`: optional secondary owner key used only when backlog is large and L2 enters catch-up mode
  - `max_events`: preferred full-batch size for this source
  - `min_ready_events`: preferred smaller ready threshold for steady-state incremental sync
  - `max_estimated_tokens`: optional token cap for one execution batch
  - `max_wait_seconds`: how long an underfilled bucket may wait before it becomes ready

L2 remains the final owner of batching policy. Plugins suggest a tighter grouping
key or preferred execution shape, but the runtime first claims durable projection
rows and then decides how leased work is grouped under backpressure. This hook
cannot enqueue raw events or create an in-memory ingestion path.

For high-volume sources such as browser history, a practical pattern is:

- `owner`: semantic primary bucket such as `profile + domain`
- `catch_up_owner`: lower-fidelity shard used only for large backlog replay
- `max_events`: large target batch size for catch-up throughput
- `min_ready_events`: smaller steady-state threshold so routine incremental sync does not wait for the full catch-up size

### Entity Hints and Relation Candidates

`extract_metadata()` returns `SensorOutputMetadata` with three fields:

- `entities`: structured entity hints (list of dicts with `mention_text`, `entity_type`, `canonical_name_hint`)
- `tags`: classification tags for the event
- `relation_candidates`: rule-based graph edge candidates (e.g., `user:self VIEWED site:github.com`)

Entity hints are injected into the L2 Phase 1 LLM prompt as **context anchors** — they help the LLM resolve entities to consistent canonical names. Hints are NOT automatically materialized into the entity catalog; only entities that the LLM independently confirms in Phase 1 output are persisted.

Relation candidates are persisted as rule-based graph edges without LLM involvement.

### L2 Extraction Profiles

Each event source is mapped to an `ExtractionProfile` that controls L2 cognition behavior. Source-specific profile IDs use the `source.*` namespace so they remain distinct from the product Timeline surface. Profiles define:

- `source_types`: which normalized event source values use this profile
- `allowed_entity_types`: which entity types LLM may create (e.g., `software`, `media`, `person`)
- `allowed_predicates`: which predicates LLM may use (e.g., `USES`, `INTERESTED_IN`, `VIEWED`)
- `allowed_assertion_families`: which ToM assertion families are permitted (empty disables assertions)
- `allow_graph` / `allow_assertion`: master switches for graph and assertion writing
- `extraction_instructions` / `phase1_instructions`: free-text instructions injected into the LLM Phase 1 prompt
- `summary_instructions`: optional wording guidance for claim-bound Phase 2 summaries
- `derived_assertion_specs`: host-validated graph-derived assertion specs for accumulated source evidence

Phase 1 instructions guide entity and grounded Claim extraction. The host then owns semantic routing and every Assertion field, including family, trait, slot, target, value, evidence, confidence, promotion horizon, lifecycle, and governance action. Phase 2 is optional and may return only concise summaries bound to host-assigned Claim IDs. Empty or invalid summaries do not change materialization. Plugins can declare derived assertion specs when they know source-specific accumulated evidence patterns, but the host still validates assertion families, traits, lifecycle, and source-tier governance.

Canonical assertion families are `stress`, `mood`, `engagement`, `trigger`, `relationship_shift`, `group_atmosphere`, `public_sentiment`, `identity_profile`, `communication_profile`, `preference_profile`, `interest_profile`, `project_profile`, `goal_profile`, `routine_profile`, and `state_profile`. Use `preference_profile` only for grounded likes and dislikes, `interest_profile` for grounded attention or interest without affinity, `project_profile` for active project work, `goal_profile` for concrete intentions, and `routine_profile` for repeated behavior rhythms and habits. Do not use assertion family names as graph predicates or graph object refs.

Plugins contribute source profiles with `get_extraction_profiles()`:

```python
from magi_plugin_sdk import ExtractionProfileSpec, Plugin


class ChromeHistoryPlugin(Plugin):
    def get_extraction_profiles(self) -> list[ExtractionProfileSpec]:
        return [
            ExtractionProfileSpec(
                profile_id="source.chrome_history",
                source_types=["chrome_history"],
                allowed_entity_types=["software", "media", "person", "topic"],
                allowed_predicates=["USES", "INTERESTED_IN", "VIEWED"],
                allow_graph=True,
                allow_assertion=False,
                extraction_instructions="Treat browser history as observed page titles, not user-authored text.",
                summary_instructions="Keep summaries factual and preserve the source language.",
            )
        ]
```

Example (Chrome history):

```python
extraction_instructions=(
    "These events are browser history page titles, NOT user-authored messages.\n"
    "Predicate guidance:\n"
    "- USES: for tool/platform usage (GitHub, ChatGPT)\n"
    "- INTERESTED_IN: for repeatedly browsed topics\n"
    "- VIEWED: for individual content consumption\n"
    "Entity rules:\n"
    "- Be SELECTIVE: only extract entities that reveal user interests or tool usage\n"
    "- MERGE related content: multiple pages about the same topic → one entity\n"
    "- SKIP noise: error messages, email addresses, UI element names\n"
)
```

Example (graph-derived profile assertion rule):

```python
derived_assertion_specs=[
    {
        "rule_id": "chrome_history.content_interest",
        "source_predicates": ["INTERESTED_IN"],
        "source_types": ["chrome_history"],
        "object_types": ["topic", "media", "person", "group", "organization", "product", "technology"],
        "trait_family": "preference_profile",
        "trait_name_template": "interest.{object_slug}",
        "min_observations": 3,
        "min_distinct_days": 2,
        "source_domains": ["external_activity"],
        "value_strategy": "canonical_name",
    }
]
```

The host validates plugin-declared entity types, predicates, assertion families, and structured-hint allowlists against the backend L2 ontology before using a profile. Host-owned chat profiles remain in `backend/configs/l2_extraction_profiles.yaml`; source-specific profiles belong with the plugin that owns the source semantics. New source types fall back to the unrestricted `chat.user_message` default profile.

## Declaring Settings Fields

Frontend settings are generated from `ExtensionFieldSpec`.

Supported field types:

- `switch`
- `select`
- `input`
- `number`
- `secret`
- `path`
- `tags`

Important conventions:

- use stable dot-notated keys such as `sensors.photo_library.source_path`
- for a scalar `path` field, set `path_kind="directory"` or
  `path_kind="file"` so the host renders the matching native picker; keep an
  array default for fields that accept multiple directories
- group fields with `section`
- choose the correct `surface`
- order fields explicitly with `order`

Typical surfaces:

- `extensions`
    plugin package level settings shown on the Plugins page

- `timeline`
  sensor settings shown in Timeline & Sources

- `tools`
  reserved for tool-facing settings surfaces

Example field list:

```python
from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec

fields = [
    ExtensionFieldSpec(
        key="sensors.example_source.sync_mode",
        type="select",
        label="Sync Mode",
        description="How synchronization is performed.",
        default="manual",
        options=[
            ExtensionFieldOption(label="Manual", value="manual"),
            ExtensionFieldOption(label="Interval", value="interval"),
        ],
        section="sync",
        surface="timeline",
        order=10,
    ),
]
```

## Reading Persisted Settings

Plugin settings are injected into `self.settings`.

Recommended pattern:

- choose one stable subtree per capability family
- merge persisted values over code defaults
- do not assume missing keys exist

Example:

```python
defaults = {"enabled": True, "sync_mode": "interval"}
current = dict(defaults)
current.update(self.settings.get("sensors", {}).get("example_source", {}))
```

## Where Settings Persist

Each connection owns settings, opaque credential references, an enabled flag,
readiness and an optimistic revision. The host stores these privately under
`runtime_dir/plugin-connections/`. Resources and retained content are separate
from private account/cursor state. A local content clear preserves source
progress and imported host memory; disconnecting removes connection state and
credentials after runtime shutdown. Global forgetting is a separate host flow.

## Frontend Behavior

Magi renders manifest field, action and resource schemas. It never loads
plugin-owned frontend code. Numeric fields use `minimum`/`maximum`; credentials
are write-only and never appear as masked round-trip setting values. A saved
required credential can be explicitly removed, disabling the connection in the
same revision-checked update. Configure multiple accounts independently.


## Testing Recommendations

When adding a new plugin or contribution, validate at three levels when relevant:

- plugin manager behavior
  discovery, enable, disable, reload

- registry integration
  tool or sensor is visible in the correct runtime registry

- API or UI surface
  settings metadata is serialized correctly and appears in the expected frontend page

Useful existing references:

- Backend plugin tests under [backend/tests/plugins](../backend/tests/plugins)
- Backend plugin API tests under [backend/tests/api](../backend/tests/api)
- [settingsPage.test.tsx](../frontend/src/__tests__/settingsPage.test.tsx)

Validate companion packages against the real host registrars from a paired
checkout after the companion's SDK-only dependencies are installed:

```bash
python scripts/check-plugin-runtime.py \
  --plugins-repo ../magi-plugins \
  --python ../magi-plugins/.venv/bin/python \
  --report /tmp/plugin-runtime.json
```

The check starts two separate workers per executable package, validates actual
contribution registration and tool policies, and verifies independent cleanup.
It never invokes collection, channel startup, tools or settings actions. Worker
dependencies must be installed explicitly; the script does not fall back to an
unrelated system Python. Use `--package <id>` for a focused rerun.

## Built-In Examples

Use these as the primary templates:

- [core-tools plugin](../plugins/core-tools/plugin.py)
- `chrome-history` plugin in the companion `magi-plugins` repository under `plugins/chrome-history/` - full sensor with entity hints, L2 batch policy, and extraction metadata

## Common Mistakes

- forgetting to include `plugin.toml`
- returning raw dictionaries instead of typed specs
- using unstable setting keys that change between reloads
- exposing timeline sensors without `metadata.source_type`
- trying to ship plugin-owned frontend code instead of field metadata
- assuming new external plugins auto-enable after discovery
- relying on `official = true` in an external manifest instead of the registry allowlist
- declaring dependencies without regenerating and committing `requirements.lock`
- omitting or understating user-visible capability declarations
- returning entity hints with types not in the source's `ExtractionProfile.allowed_entity_types`
- using full page titles as canonical entity names instead of concise subject names

## Related Documents

- [Unified Plugin Architecture](./plugin-extension-architecture.md)
- [Project Overview](./project-overview.md)
