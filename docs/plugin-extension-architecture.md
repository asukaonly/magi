# Unified Plugin Extension Architecture

## Purpose

This document describes the current unified plugin runtime in Magi.

It is the implementation-facing guide for:

- maintainers evolving extension loading and registration
- contributors wiring new tools, timeline sensors, or outbound actions
- frontend contributors building settings surfaces for extension-backed capabilities

The current system unifies `tool`, `sensor`, and `action` extensions under one plugin package model.

## Design Goals

The plugin runtime exists to solve three problems:

- stop hardcoding extension registration paths separately for tools, sensors, and actions
- let built-in and external extensions use the same discovery and lifecycle model
- expose a declarative settings contract that the frontend can render without loading plugin-owned UI code

## Runtime Model

Each plugin package is a backend Python package that may contribute one or more capability types:

- tools
- sensors
- actions

A plugin package is discovered from disk, parsed from `plugin.toml`, loaded from a Python entry module, then registered into one or more runtime registries.

At runtime the flow is:

1. `PluginManager` scans plugin roots for `plugin.toml`
2. discovered packages are persisted into split plugin config files under `~/.magi/config/plugins/`
3. packages are disabled by default unless they are official built-in packages enabled by default config
4. enabled packages are instantiated through the shared `Plugin` base class
5. contributions are registered into dedicated registries:
   - `ToolRegistry`
   - `SensorRegistry`
   - `ActionRegistry`
6. APIs and frontend settings surfaces read registry state and plugin package state rather than hardcoded lists

## Scan Paths

The plugin manager scans two roots:

- repository built-ins: `plugins/`
- user-installed plugins: `~/.magi/plugins/`

These roots are persisted in:

- [models.py](/Users/asuka/code/magi/backend/src/magi/config/models.py)

under:

- `plugins.scan_paths`

## Package Structure

A plugin package is a directory containing:

- `plugin.toml`
- a Python entry module, currently `plugin.py` by default

Official built-in examples live in:

- [core-tools](/Users/asuka/code/magi/plugins/core-tools/plugin.py)
- [photo-library](/Users/asuka/code/magi/plugins/photo-library/plugin.py)
- [core-actions](/Users/asuka/code/magi/plugins/core-actions/plugin.py)

## Manifest Contract

The manifest is parsed into `PluginManifest`.

Important fields:

- `id`
- `name`
- `version`
- `description`
- `author`
- `entry_module`
- `entry_class`
- `official`
- `contribution_types`

The typed contract lives in:

- [contracts.py](/Users/asuka/code/magi/backend/src/magi/plugins/contracts.py)

## Base Plugin Contract

Every plugin entry class must inherit:

- [Plugin](/Users/asuka/code/magi/backend/src/magi/plugins/base.py)

The base contract exposes three contribution hooks:

- `get_tools()`
- `get_sensors()`
- `get_actions()`

A single plugin package may implement any combination of these.

The manager binds two pieces of runtime state before registration:

- parsed manifest
- persisted plugin settings

## Registries

The plugin manager is the package lifecycle owner, but it does not act as the execution surface itself.

Instead it registers contributions into dedicated registries.

### Tool Registry

Tools remain normal Magi tools.

The plugin runtime only changes how they are discovered and registered.

Built-in tools now come from the official `core-tools` plugin instead of import-time hardcoded registration.

### Sensor Registry

Sensors are registered into `SensorRegistry` with:

- sensor instance
- `SensorSpec`
- owning `plugin_id`

The most important current consumer is timeline ingestion.

Timeline no longer owns a fixed list of built-in sources in the settings surface or status API. It resolves timeline-capable sensors from `SensorRegistry`.

Builtin timeline sensor packages that should be configurable in Settings are expected to stay plugin-enabled even when their own source-level `enabled` switch is off. In other words, package activation controls whether the plugin participates in runtime discovery, while source activation controls whether the sensor actually syncs.

The contracts live in:

- [sensors.py](/Users/asuka/code/magi/backend/src/magi/plugins/sensors.py)

### Action Registry

Actions are first-class outbound capabilities used for system-side behavior such as user notifications or email.

They remain distinct from tools.

An action may optionally declare a tool adapter name, which lets the plugin runtime expose that action through `ToolRegistry` as an agent-callable tool without collapsing the two concepts into one.

The contracts live in:

- [actions.py](/Users/asuka/code/magi/backend/src/magi/plugins/actions.py)

## Declarative Settings Contract

Frontend settings do not load plugin-owned React code.

Instead, plugins expose `ExtensionFieldSpec` metadata, which describes a field declaratively.

Supported field types today:

- `switch`
- `select`
- `input`
- `number`
- `secret`
- `path`
- `tags`

Important field attributes:

- `key`
- `type`
- `label`
- `description`
- `default`
- `required`
- `options`
- `section`
- `surface`
- `order`
- `placeholder`

The frontend consumes these fields through:

- [plugins.ts](/Users/asuka/code/magi/frontend/src/api/modules/plugins.ts)
- [PluginSettingsFields.tsx](/Users/asuka/code/magi/frontend/src/components/settings/PluginSettingsFields.tsx)

## Settings Surfaces

The current settings UI is intentionally split between global config and plugin-owned config.

### Global config remains in `configApi`

Examples:

- LLM settings
- memory layer toggles

### Plugin-backed settings now use `pluginsApi`

Examples:

- per-plugin enable / disable / reload
- per-sensor source settings
- action-specific settings

Frontend surfaces:

- [Settings.tsx](/Users/asuka/code/magi/frontend/src/pages/Settings.tsx)
- [ExtensionsSection.tsx](/Users/asuka/code/magi/frontend/src/components/settings/ExtensionsSection.tsx)
- [TimelineSourcesSection.tsx](/Users/asuka/code/magi/frontend/src/components/settings/TimelineSourcesSection.tsx)
- [ActionsSection.tsx](/Users/asuka/code/magi/frontend/src/components/settings/ActionsSection.tsx)

## Configuration Persistence

Plugin configuration is split across host config and plugin-specific files.

The persisted shape is:

- `~/.magi/config/agent.yaml`
  - `plugins.scan_paths`
- `~/.magi/config/plugins/index.yaml`
  - `packages.<plugin_id>.enabled`
  - `packages.<plugin_id>.trusted`
  - `packages.<plugin_id>.source`
  - `packages.<plugin_id>.manifest_path`
- `~/.magi/config/plugins/<plugin_id>.yaml`
  - plugin-owned `settings`

This keeps host runtime configuration separate from plugin lifecycle state and reduces churn in the main config file as plugin surfaces grow.

## API Surface

The unified plugin management API lives in:

- [plugins.py](/Users/asuka/code/magi/backend/src/magi/api/routers/plugins.py)

Current endpoints:

- `GET /api/plugins`
- `POST /api/plugins/rescan`
- `POST /api/plugins/{plugin_id}/enable`
- `POST /api/plugins/{plugin_id}/disable`
- `POST /api/plugins/{plugin_id}/reload`
- `GET /api/plugins/{plugin_id}/settings`
- `PUT /api/plugins/{plugin_id}/settings`

Timeline source status also now reflects plugin-backed sensor registration:

- [timeline.py](/Users/asuka/code/magi/backend/src/magi/api/routers/timeline.py)

## Official Built-In Plugins

Magi currently ships three general built-in plugin packages:

- `core-tools`
  registers built-in tools

- `photo-library`
  registers the local photo library timeline source

- `core-actions`
  registers built-in outbound actions such as send-email

These packages are enabled by default through config defaults.

Magi also ships additional built-in timeline sensor packages. These packages are enabled by default so their settings remain discoverable, while their individual sources stay disabled until the user opts in:

- `chrome-history`
  registers the local Chrome history timeline source

- `apple-health`
  registers Apple Health ingestion on supported Apple platforms

- `calendar`
  registers calendar event ingestion on supported Apple platforms

- `git-activity`
  registers local git activity ingestion

- `screen-time`
  registers Screen Time ingestion on supported Apple platforms

- `terminal-history`
  registers local terminal history ingestion

## Operational Rules

Current behavior rules:

- newly discovered external plugins default to `enabled=false`
- external plugins must become trusted before loading
- built-in official plugins may default to enabled and trusted
- disabling a plugin unregisters its contributions from all registries
- reloading a plugin unloads and re-registers all of its current contributions

## Timeline Integration

The plugin runtime directly affects timeline behavior.

Current rules:

- timeline source definitions are derived from `SensorRegistry`
- only sensors declaring `metadata.domain == "timeline"` are treated as timeline sources
- the timeline settings page renders source cards from plugin metadata rather than a fixed frontend enum
- per-source settings are persisted through plugin package settings instead of `config.timeline.sources`

Global timeline switches still remain in the root config because they control timeline behavior at the domain level rather than at one plugin contribution.

## Action Integration

Actions are now visible in the settings page as a dedicated surface.

Current rules:

- actions remain separate from tools at the model level
- an action may optionally expose a tool adapter name
- the runtime will register that adapter into `ToolRegistry`
- the settings page still treats the action as an action contribution, not as a tool definition

## Known Boundaries

The current plugin runtime is intentionally scoped.

It does not yet support:

- plugin-owned frontend bundles
- hot code sandboxing or permission isolation beyond trust/enable state
- arbitrary awareness-module sensor registration through the old awareness abstractions
- remote plugin marketplaces or package installation flows

The current system is a local backend Python extension model.

## Related Files

- [Plugin manager](/Users/asuka/code/magi/backend/src/magi/plugins/manager.py)
- [Plugin runtime exports](/Users/asuka/code/magi/backend/src/magi/plugins/__init__.py)
- [Config models](/Users/asuka/code/magi/backend/src/magi/config/models.py)
- [Plugins API](/Users/asuka/code/magi/backend/src/magi/api/routers/plugins.py)
- [Timeline API](/Users/asuka/code/magi/backend/src/magi/api/routers/timeline.py)

## Related Documents

- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
- [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md)
- [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md)
