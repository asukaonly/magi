# Plugin Development Guide

## Purpose

This guide explains how to build a Magi plugin package with the current unified plugin runtime.

Use it when you want to:

- add a built-in extension under `plugins/`
- author an external plugin under `~/.magi/plugins/`
- contribute new tools, timeline sensors, or outbound actions

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
contribution_types = ["tool", "sensor", "action"]
```

You only need to declare the contribution types you actually expose.

## 2. Implement the plugin class

Every plugin must inherit:

- [Plugin](/Users/asuka/code/magi/backend/src/magi/plugins/base.py)

Example:

```python
from magi.plugins import Plugin


class ExamplePlugin(Plugin):
    def get_tools(self):
        return []

    def get_sensors(self):
        return []

    def get_actions(self):
        return []
```

The runtime will call `configure()` before registration, so `self.manifest` and `self.settings` are available inside your plugin instance.

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

- `Settings -> Extensions`

New external plugins are discovered disabled by default.

Plugin state is persisted in split config files:

- host scan paths stay in `~/.magi/config/agent.yaml`
- enable / trust / source metadata lives in `~/.magi/config/plugins/index.yaml`
- plugin-owned settings live in `~/.magi/config/plugins/<plugin_id>.yaml`

## Tool Plugins

Tool plugins return normal Magi tool classes from `get_tools()`.

Example:

```python
from magi.plugins import Plugin
from magi.tools.schema import Tool, ToolExecutionContext, ToolResult, ToolSchema


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

## Sensor Plugins

Sensors return tuples from `get_sensors()`:

- `sensor_id`
- sensor instance
- `SensorSpec`

Example:

```python
from magi.plugins import ExtensionFieldSpec, Plugin, SensorSpec


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

Sensors inheriting `SensorBase` have access to the following hooks that control memory routing and L2 cognition behavior:

**Core contract:**

- `build_output(item)`: convert a source item into a domain-neutral `SensorOutput` (required)
- `extract_metadata(item)`: extract `SensorOutputMetadata` containing entity hints, tags, and relation candidates
- `collect_items(context)`: pull-sync entry point; returns `SensorSyncResult` with items, cursor, and stats
- `fetch_item(item)`: optional pre-processing/enrichment before `build_output`

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

Each event source is mapped to an `ExtractionProfile` that controls L2 cognition behavior. Profiles define:

- `allowed_entity_types`: which entity types LLM may create (e.g., `software`, `media`, `person`)
- `allowed_predicates`: which predicates LLM may use (e.g., `USES`, `INTERESTED_IN`, `VIEWED`)
- `allowed_assertion_families`: which ToM assertion families are permitted (empty disables assertions)
- `allow_graph` / `allow_assertion`: master switches for graph and assertion writing
- `extraction_instructions`: free-text instructions injected into the LLM Phase 1 prompt

The extraction instructions are the primary mechanism for plugins to guide LLM behavior. They tell the LLM how to interpret source-specific content patterns, which entities to extract vs. skip, and how to choose predicates.

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

Profiles are currently registered in `extraction_profiles.py`. New source types fall back to the unrestricted `chat.user_message` default profile.

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
  plugin package level settings shown on the Extensions page

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
  tool, sensor, or action is visible in the correct runtime registry

- API or UI surface
  settings metadata is serialized correctly and appears in the expected frontend page

Useful existing references:

- Backend plugin tests under [backend/tests/plugins](/Users/asuka/code/magi/backend/tests/plugins)
- Backend plugin API tests under [backend/tests/api](/Users/asuka/code/magi/backend/tests/api)
- [settingsPage.test.tsx](/Users/asuka/code/magi/frontend/src/__tests__/settingsPage.test.tsx)

## Built-In Examples

Use these as the primary templates:

- [core-tools plugin](/Users/asuka/code/magi/plugins/core-tools/plugin.py)
- [chrome-history plugin](/Users/asuka/code/magi/plugins/chrome-history/) — full sensor with entity hints, L2 batch policy, and extraction metadata
- [core-actions plugin](/Users/asuka/code/magi/plugins/core-actions/plugin.py)

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

- [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md)
- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
