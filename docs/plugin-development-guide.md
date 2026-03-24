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
- set `metadata.source_type` because timeline routing uses it
- provide a `default_settings` object when the contribution needs stable defaults
- store settings under a stable subtree such as `sensors.<source_name>.*`

## Action Plugins

Actions inherit `BaseAction` and return instances from `get_actions()`.

Example:

```python
from magi.plugins import ActionExecutionContext, ActionSpec, BaseAction, Plugin


class NotifyAction(BaseAction):
    def build_spec(self) -> ActionSpec:
        return ActionSpec(
            action_id="notify-user",
            display_name="Notify User",
            description="Send an in-app notification.",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Notification body"},
                },
                "required": ["message"],
            },
            tool_adapter_name="notify-user",
        )

    async def execute(self, parameters: dict, context: ActionExecutionContext) -> dict:
        return {"status": "sent", "message": parameters["message"]}


class ExamplePlugin(Plugin):
    def get_actions(self):
        return [NotifyAction()]
```

Guidelines:

- actions model outbound system behavior
- do not treat actions as tools by default
- use `tool_adapter_name` only when the action should also be callable through agent tool invocation

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

- use stable dot-notated keys such as `sensors.browser_history.fetch_page_content`
- group fields with `section`
- choose the correct `surface`
- order fields explicitly with `order`

Typical surfaces:

- `extensions`
  plugin package level settings shown on the Extensions page

- `timeline`
  sensor settings shown in Timeline & Sources

- `actions`
  action settings shown on the Actions page

- `tools`
  reserved for tool-facing settings surfaces

Example field list:

```python
from magi.plugins import ExtensionFieldOption, ExtensionFieldSpec

fields = [
    ExtensionFieldSpec(
        key="email.default_sender",
        type="input",
        label="Default Sender",
        description="Default sender address for email actions.",
        default="",
        section="email",
        surface="actions",
        order=10,
    ),
    ExtensionFieldSpec(
        key="email.provider_mode",
        type="select",
        label="Delivery Mode",
        default="simulated",
        options=[
            ExtensionFieldOption(label="Simulated", value="simulated"),
        ],
        section="email",
        surface="actions",
        order=20,
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
- [core-timeline plugin](/Users/asuka/code/magi/plugins/core-timeline/plugin.py)
- [core-actions plugin](/Users/asuka/code/magi/plugins/core-actions/plugin.py)

## Common Mistakes

- forgetting to include `plugin.toml`
- returning raw dictionaries instead of typed specs
- using unstable setting keys that change between reloads
- exposing timeline sensors without `metadata.source_type`
- trying to ship plugin-owned frontend code instead of field metadata
- assuming new external plugins auto-enable after discovery

## Related Documents

- [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md)
- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
