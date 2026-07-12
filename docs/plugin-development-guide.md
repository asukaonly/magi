# Plugin Development Guide

## Purpose

This guide explains how to build a Magi plugin package with the current unified plugin runtime.

Use it when you want to:

- add a built-in extension under `plugins/`
- author an external plugin under `~/.magi/plugins/`
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

Both import paths below resolve to the same classes at runtime:

```python
from magi_plugin_sdk import Plugin, SensorSpec   # recommended for external plugins
from magi.plugins import Plugin, SensorSpec      # also works (requires magi backend)
```

## Authoring Surface Status

The SDK is the long-term source of truth for plugin authoring, but the migration is still in progress.

Current status:

- declarative plugin contracts already live in `magi-plugin-sdk`
- tool authoring contracts already live in `magi-plugin-sdk.tools`
- sensor authoring contracts already live in `magi-plugin-sdk.sensors`
- channel authoring contracts already live in `magi-plugin-sdk.channels`
- ingress authoring contracts already live in `magi-plugin-sdk.ingress`
- the backend re-exports those contracts from `magi.plugins` for compatibility
- runtime registries, lifecycle modules, and persistence stores remain backend-owned

When writing new external plugins:

- prefer `magi_plugin_sdk` imports wherever available
- treat backend runtime imports as compatibility imports during the transition
- avoid depending on backend host internals such as registries, scheduler services, or persistence stores

## Legacy Import Migration Map

Use this table when moving an existing plugin off backend-owned imports.

| Legacy import / pattern | Preferred replacement |
| --- | --- |
| `from magi.plugins import Plugin, SensorSpec, ExtensionFieldSpec, ...` | `from magi_plugin_sdk import Plugin, SensorSpec, ExtensionFieldSpec, ...` |
| `from magi.awareness import SensorBase, SensorOutput, SensorSyncContext, ...` | `from magi_plugin_sdk.sensors import SensorBase, SensorOutput, SensorSyncContext, ...` |
| `from magi.channels.base import Channel` | `from magi_plugin_sdk.channels import Channel` |
| `from magi.channels.contracts import ChannelTarget, OutboundContent, ...` | `from magi_plugin_sdk.channels import ChannelTarget, OutboundContent, ...` |
| `from magi.channels.session_mapper import ChannelSessionMapper` for adapter typing | use injected `ChannelSessionMapperProtocol` instead of the backend concrete class |
| `from magi.api.services.message_dispatch_service import dispatch_user_message` inside a channel adapter | use injected `ChannelMessageDispatcherProtocol` and call `dispatcher.dispatch_user_message(...)` |
| `from magi.events.plugin_ingress import PluginIngressHandlerRegistration` | `from magi_plugin_sdk.ingress import PluginIngressHandlerRegistration` |
| `from magi.runtime_trace import PluginIngressEventRecord` | `from magi_plugin_sdk.ingress import PluginIngressEventRecord` |
| `from magi.core.logger import get_logger` | `from magi_plugin_sdk import get_logger` |

Compatibility paths still exist in the backend for the migration window, but new plugin code should treat the SDK column as canonical.

## Quick Start

A plugin package is a directory with:

- `plugin.toml`
- `plugin.py`

Minimal example:

```text
my-plugin/
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
description = "Sample Magi plugin package"
author = "Your Name"
entry_module = "plugin"
entry_class = "ExamplePlugin"
official = false
contribution_types = ["tool", "sensor"]
```

You only need to declare the contribution types you actually expose.

## 2. Implement the plugin class

Every plugin must inherit:

- [Plugin](../backend/src/magi/plugins/base.py)

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

The runtime will call `configure()` before registration, so `self.manifest` and `self.settings` are available inside your plugin instance.

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

For local development, external plugins usually belong under:

- `~/.magi/plugins/<your-plugin>/`

## 4. Rescan and enable it

Use the plugin management API:

- `POST /api/plugins/rescan`
- `POST /api/plugins/{plugin_id}/enable`

Or use the Settings page:

- `Settings -> Plugins`

New external plugins are discovered disabled by default.

Plugin state is persisted in split config files:

- host scan paths stay in `~/.magi/config/agent.yaml`
- enable / trust / source metadata lives in `~/.magi/config/plugins/index.yaml`
- plugin-owned settings live in `~/.magi/config/plugins/<plugin_id>.yaml`

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
- use the plugin only as the registration container
- if the tool needs settings, expose them through plugin contribution fields rather than custom frontend UI
- legacy backend imports from `magi.tools.schema` still work during migration, but new plugin code should target `magi_plugin_sdk.tools`
- for plugin-local logging, use `magi_plugin_sdk.get_logger` rather than `magi.core.logger`

## Channel Plugins

Channel plugins return a configured channel adapter from `get_channel()` and declarative settings fields from `get_channel_fields()`.

Example:

```python
from magi_plugin_sdk import ExtensionFieldSpec, Plugin
from magi_plugin_sdk.channels import (
    Channel,
    ChannelMessageDispatcherProtocol,
    ChannelSessionMapperProtocol,
    ChannelTarget,
    OutboundContent,
)


class ExampleChannel(Channel):
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
- keep transport-specific SDKs inside the plugin package so the core SDK stays lightweight
- route inbound messages through the injected dispatcher instead of importing `magi.api.services.message_dispatch_service` directly
- legacy imports from `magi.channels.base` and `magi.channels.contracts` still work during the migration window

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
- legacy imports from `magi.events.plugin_ingress` still work during the migration window
- older plugins that typed events as `magi.runtime_trace.PluginIngressEventRecord` still resolve, but new code should import the SDK protocol instead

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

### SensorBase Hooks

Sensors inheriting `SensorBase` from `magi_plugin_sdk.sensors` have access to the following hooks that control memory routing and L2 cognition behavior:

**Core contract:**

- `build_output(item)`: convert a source item into a domain-neutral `SensorOutput` (required)
- `extract_metadata(item)`: extract `SensorOutputMetadata` containing entity hints, tags, and relation candidates
- `collect_items(context)`: pull-sync entry point; returns `SensorSyncResult` with items, cursor, and stats
- `fetch_item(item)`: optional pre-processing/enrichment before `build_output`

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
  - `owner`: stable owner key for durable microbatch grouping (e.g., `chrome_history:Default:github.com`)
  - `catch_up_owner`: optional secondary owner key used only when backlog is large and L2 enters catch-up mode
  - `max_events`: preferred full-batch size for this source
  - `min_ready_events`: preferred smaller ready threshold for steady-state incremental sync
  - `max_estimated_tokens`: optional token cap for one execution batch
  - `max_wait_seconds`: how long an underfilled bucket may wait before it becomes ready

L2 remains the final owner of batching policy. Plugins suggest a tighter bucket key or preferred batch shape, but the runtime decides when a bucket is ready, how much work to claim under backpressure, and when a forced flush may bypass waiting.

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
- `assertion_mode`: `none`, `derived`, or `phase2_candidate`
- `extraction_instructions` / `phase1_instructions`: free-text instructions injected into the LLM Phase 1 prompt
- `phase2_instructions`: source-specific integration guidance injected into the Phase 2 prompt
- `derived_assertion_specs`: host-validated graph-derived assertion specs for accumulated source evidence

Phase 1 instructions guide entity and fact extraction. Phase 2 instructions explain which higher-order assertions are meaningful for the source and how to interpret domain evidence. Phase 2 cannot emit graph edges or choose evidence IDs, confidence, lifecycle, expiry, or persistence actions; it can only reference host-assigned Phase 1 claim IDs and exact existing record IDs. Plugins can also declare derived assertion specs when they know source-specific evidence patterns better than the host, but the host still validates assertion families, traits, lifecycle, and source-tier conflict rules.

Phase 2 also receives a host-built deterministic evidence packet when related context is available. The packet can include current candidate anchors, bounded L1 history matches, related graph evidence, and existing assertion state. This recall step is intentionally non-LLM; plugins influence it through source metadata, batch ownership, graph facts, and derived assertion specs rather than by running their own model pass.

Canonical assertion families are `stress`, `mood`, `engagement`, `trigger`, `relationship_shift`, `group_atmosphere`, `public_sentiment`, `identity_profile`, `communication_profile`, `preference_profile`, `routine_profile`, and `state_profile`. Use `preference_profile` for durable interests, affinities, tastes, and preferences. Use `routine_profile` for repeated behavior rhythms and habits. Do not use assertion family names as graph predicates or graph object refs.

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
                phase2_instructions="Do not infer user preferences from one-off page visits.",
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

Plugin state is persisted under:

- `plugins.packages.<plugin_id>.settings`

Enable and trust state are persisted under:

- `plugins.packages.<plugin_id>.enabled`
- `plugins.packages.<plugin_id>.trusted`

## Frontend Behavior

The frontend does not run plugin code.

Instead it:

- reads plugin packages from `/api/plugins`
- renders fields from `ExtensionFieldSpec`
- saves updates back through `/api/plugins/{plugin_id}/settings`

If your plugin declares fields correctly, it can appear in the settings UI without additional frontend code.

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
- returning entity hints with types not in the source's `ExtractionProfile.allowed_entity_types`
- using full page titles as canonical entity names instead of concise subject names

## Related Documents

- [Unified Plugin Architecture](./plugin-extension-architecture.md)
- [Project Overview](./project-overview.md)
