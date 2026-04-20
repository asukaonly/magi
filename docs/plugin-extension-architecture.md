# Unified Plugin Extension Architecture

## Purpose

This document describes the current unified plugin runtime in Magi.

It is the implementation-facing guide for:

- maintainers evolving extension loading and registration
- contributors wiring new tools or timeline sensors
- frontend contributors building settings surfaces for extension-backed capabilities

The current system unifies `tool` and `sensor` extensions under one plugin package model.

## Design Goals

The plugin runtime exists to solve three problems:

- stop hardcoding extension registration paths separately for tools and sensors
- let built-in and external extensions use the same discovery and lifecycle model
- expose a declarative settings contract that the frontend can render without loading plugin-owned UI code

## Runtime Model

Each plugin package is a backend Python package that may contribute one or more capability types:

- tools
- sensors

A plugin package is discovered from disk, parsed from `plugin.toml`, loaded from a Python entry module, then registered into one or more runtime registries.

At runtime the flow is:

1. `PluginManager` scans plugin roots for `plugin.toml`
2. discovered packages are persisted into split plugin config files under `~/.magi/config/plugins/`
3. packages are disabled by default unless they are official built-in packages enabled by default config
4. enabled packages are instantiated through the shared `Plugin` base class
5. contributions are registered into dedicated registries:
   - `ToolRegistry`
   - `SensorRegistry`
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
- [chrome-history](/Users/asuka/code/magi/plugins/chrome-history/) — full-featured sensor with entity hints, batch policies, and metadata extraction

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

The base contract exposes two contribution hooks:

- `get_tools()`
- `get_sensors()`

A single plugin package may implement either or both.

The manager binds two pieces of runtime state before registration:

- parsed manifest
- persisted plugin settings

## Registries

The plugin manager is the package lifecycle owner, but it does not act as the execution surface itself.

Instead it registers contributions into dedicated registries.

## Plugin Ingress Events

Some plugin-backed capabilities depend on local host events that are produced outside the Python plugin package itself.

The current host-side ingress flow is:

1. a local producer such as the Tauri desktop shell appends an event into `runtime_trace.db.plugin_ingress_events`
2. the runtime worker claims pending ingress events through the shared `PluginIngressProcessor`
3. the processor routes each event to a plugin-owned handler by `(plugin_target, event_type)`
4. the handler reduces the raw ingress event into plugin-domain state or normal runtime outputs such as `L1` events

Important rule: `plugin_ingress_events` is an append-only fact log for observed local events. It is not a replacement for the runtime command queue and should not be used for API-to-runtime control flow.

### Tool Registry

Tools remain normal Magi tools.

The plugin runtime only changes how they are discovered and registered.

Built-in tools now come from the official `core-tools` plugin instead of import-time hardcoded registration.

### Sensor Registry

Sensors are registered into `SensorRegistry` with:

- sensor instance
- `SensorSpec`
- owning `plugin_id`

The most important current consumers are the generic sensor status/scheduler flow and downstream timeline ingestion.

Timeline no longer owns the settings surface or operational status API for sensors. The host resolves sensor sources from `SensorRegistry`, while timeline remains a downstream read model that consumes ingested sensor outputs.

Builtin timeline sensor packages that should be configurable in Settings are expected to stay plugin-enabled even when their own source-level `enabled` switch is off. In other words, package activation controls whether the plugin participates in runtime discovery, while source activation controls whether the sensor actually syncs.

The contracts live in:

- [sensors.py](/Users/asuka/code/magi/backend/src/magi/plugins/sensors.py)

## Sensor Memory Integration

### Data Flow

Sensor outputs flow through the memory system via the following chain:

```
SensorBase.build_output(item)     → SensorOutput (content, provenance)
SensorBase.extract_metadata(item) → SensorOutputMetadata (entity hints, tags, relations)
IngestionGateway.ingest()         → MemoryEvent with metadata_json
L1 EventStore                     → persisted fact event
L2 Pipeline                       → cognition (graph, entities, assertions)
```

### SensorOutput

`SensorOutput` is the domain-neutral output produced by all sensors:

- `source_type` / `source_item_id`: identity
- `title` / `summary` / `content_blocks`: content for display and L2 processing
- `tags` / `entities`: classification
- `provenance`: source-specific metadata (sensor_id, domain, visit_id, etc.)
- `domain_payload`: extra structured data for downstream consumers

### SensorOutputMetadata

`SensorOutputMetadata` is extracted separately from the raw source item and carries:

- `entities`: structured entity hints (list of dicts with `mention_text`, `entity_type`, `canonical_name_hint`)
- `tags`: classification tags
- `relation_candidates`: rule-based graph edge candidates

Entity hints are passed through the ingestion gateway as `structured_entity_hints` in `MemoryEvent.metadata_json`. In the L2 pipeline, these hints are injected into the Phase 1 LLM prompt as **context anchors** — they help the LLM resolve entities to consistent canonical names and types, but are NOT automatically materialized into the entity catalog. Only entities that the LLM independently extracts in Phase 1 output become persisted entities.

Relation candidates are persisted as rule-based graph edges (with `extraction_method="rule"`) without LLM involvement.

### Target Semantic Enrichment Contract

The long-term plugin-facing contract should evolve from “entity hints + ad hoc rule edges” into a source-owned semantic enrichment envelope.

Important boundary:

- plugins and sensors should expose structured facts through awareness-layer contracts
- they should not import or depend directly on `memory.l2` pipeline internals
- ingestion and `L2` remain the only owners of graph admission, conflict handling, and persistence

The target shape of `SensorOutputMetadata` is:

- `entities`
  Structured entity hints for canonicalization and resolution
- `fact_hints`
  Structured facts supplied by the source integration
- `tags`
  Classification labels
- `relation_candidates`
  Backward-compatibility field for older plugins; runtime may adapt these into `fact_hints`

Recommended `fact_hints` payload fields:

- `subject_ref`
- `subject_type`
- `predicate`
- `object_ref`
- `object_type`
- `fact_kind`
- optional `origin_mode`
- `confidence`
- `observed_at`
- optional `evidence_text`
- optional `attributes`

Recommended `origin_mode` values:

- `source_explicit`
- `source_structured`
- `heuristic`
- `llm_inferred`

When a fact depends on page or payload shape, plugins should put the strongest stable discriminator under `attributes`. For browser-style integrations, `attributes.page_kind` is the preferred field for distinguishing:

- creator / profile / channel pages
- content detail pages
- subscription or follow list pages

The intent is that plugins provide what they know with high confidence, while runtime layers decide whether that fact becomes:

- a persisted rule-backed graph candidate
- a structured hint only
- or a rejected candidate

#### Ownership Model

Deterministic extraction should be owned by the source or modality that best understands the raw payload:

- browser history integrations understand URL, host, page type, and account/profile pages
- calendar integrations understand organizer, attendees, and meeting locations
- photo and media integrations understand EXIF, album structure, capture time, and GPS
- map / POI integrations understand venue identities and normalized location metadata

This avoids pushing source-specific parsing into `L2` itself. `L2` should consume a normalized semantic contract, not a growing collection of source-private parsing rules.

#### Plugin-Facing Constraints

Plugins may emit facts for stable object topology or user interaction evidence, but they should be conservative about preference facts.

Recommended interpretation by `fact_kind`:

- `public_topology`
  Stable object-side structure such as platform presence or geographic containment
- `interaction_evidence`
  User-side evidence such as viewed, visited, used, or followed
- `stable_preference`
  Explicit preference only when the source itself is semantically strong enough to justify it

For passive sources such as browsing history, plugins should prefer:

- `VIEWED`
- `USES`
- `VISITED`
- `FOLLOWS` only when the page or payload clearly represents an account / profile / subscription relationship

Runtime admission may further tighten these facts by combining `fact_kind`, `predicate`, `origin_mode`, and source-specific attributes such as `page_kind`. Plugins should therefore emit the strongest available provenance rather than assuming every `fact_hint` will become a persisted graph edge.

They should not emit `LIKES` or `DISLIKES` unless the upstream source is explicit enough to justify a stable preference fact.

#### Internal-Only Graph Semantics

Some graph concepts are required for correct retrieval and constraint handling but should remain system-facing rather than LLM-facing.

Current target examples:

- internal type: `presence`
- internal predicates:
  - `PRESENCE_OF`
  - `ON_PLATFORM`
  - `LOCATED_IN`

Plugins may reference these via structured hints, but the runtime should continue treating them as internal graph semantics rather than free-form LLM-generated ontology.
In practice this means extraction profiles may allow them for structured hints while keeping them out of the default LLM-facing predicate / entity allowlists.

See also:

- [memory-system-design.md](/Users/asuka/code/magi/docs/memory-system-design.md)

### L2 Batch Policy

Sensors can influence L2 microbatch grouping by returning an `L2BatchPolicy` from `l2_batch_policy(output)`:

```python
@dataclass(slots=True)
class L2BatchPolicy:
    owner: str | None = None
    max_events: int | None = None
    max_estimated_tokens: int | None = None
    max_wait_seconds: int | None = None
```

- `owner`: stable key for durable microbatch grouping. Chrome history uses `chrome_history:{profile}:{domain}` to batch by site rather than mixing all browsing into one bucket.
- `max_events`: preferred batch size for this source (e.g., Chrome uses 20 instead of the global default 12).
- `max_estimated_tokens`: optional token cap per execution batch.
- `max_wait_seconds`: how long an underfilled bucket may wait before it becomes ready.

These values are advisory. L2 remains the final owner of batching decisions: it decides when a bucket is ready, how much work to claim under backpressure, and when a forced flush may bypass waiting.

The ingestion gateway propagates these hints into `MemoryEvent.metadata_json` as `l2_batch_owner`, `l2_batch_max_events`, `l2_batch_max_estimated_tokens`, and `l2_batch_max_wait_seconds`. The L2 pipeline reads them back to create appropriately scoped `L2PendingBatchBucket` instances.

### Extraction Profiles

Each event source is mapped to an `ExtractionProfile` that controls what the L2 LLM is allowed to produce:

```python
@dataclass(slots=True, frozen=True)
class ExtractionProfile:
    profile_id: str
    allowed_entity_types: frozenset[str]
    allowed_predicates: frozenset[str]
    allowed_assertion_families: frozenset[str]
    entity_type_aliases: dict[str, str]
    predicate_aliases: dict[str, str]
    subject_policy: DefaultSubjectPolicy
    allow_graph: bool
    allow_assertion: bool
    extraction_instructions: str | None
```

Key fields:

- `allowed_entity_types`: LLM-extracted entities with types outside this set are filtered out before catalog registration.
- `allowed_predicates`: LLM-extracted graph edges with predicates outside this set are dropped.
- `allow_assertion`: master switch for Theory of Mind assertion generation (disabled for Chrome history since browsing history does not reveal psychological states reliably).
- `extraction_instructions`: free-text instructions injected into the LLM Phase 1 prompt under a `## Source-Specific Instructions` section. This is the primary mechanism for plugins to customize LLM extraction behavior per source type.

Profile mapping uses `source_type` from the event. New source types fall back to the unrestricted `chat.user_message` default profile.

Current registered profiles include:

- `chat.user_message` — unrestricted default
- `chat.agent_response` — graph-only, no assertions
- `timeline.chrome_history` — selective entity types, no assertions, detailed extraction instructions
- `timeline.git_activity` — software/project focused
- `timeline.screen_time` — software/activity focused

### Entity Quality Controls in L2 Pipeline

The L2 pipeline applies several quality controls beyond extraction profiles:

- **Type filtering**: entities with types not in `allowed_entity_types` are rejected at registration time.
- **Alias validation**: `_is_valid_alias()` rejects generic platform names (like "抖音", "YouTube") as aliases for non-software entities, and filters out very short aliases for long canonical names.
- **Cross-type entity resolution**: when type-scoped alias resolution fails, the pipeline tries cross-type resolution against compatible type groups (e.g., `software`/`product`/`technology` are considered mergeable) to prevent type fragmentation.
- **Hint-as-context**: structured entity hints from sensors are injected into the LLM prompt but not auto-materialized, keeping the LLM as the quality gatekeeper for entity creation.

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

## Plugin Settings Resources

Some plugin-backed settings need dynamic runtime data that cannot be expressed as a fixed field option list.

Examples:

- calendar account / calendar-list selection after authorization
- repository pickers for git-backed sensors
- mailbox or album selection for source-specific sync scopes

For these cases, plugins may expose read-only settings resources through the backend plugin contract.

The host API remains generic. It does not add per-plugin endpoints.

The current shape is:

- plugin hook:
  - `get_settings_resources()`
  - `read_settings_resource(resource_name)`
- host API:
  - `GET /api/plugins/{plugin_id}/settings/resources/{resource_name}`

This keeps plugin-specific logic inside the plugin package while letting the host own routing, auth, and error handling.

## Host-Rendered Custom Settings Blocks

Plugins still do not ship frontend React code.

When a plugin needs richer UI than plain declarative fields, it may declare host-rendered settings blocks in contribution metadata.

Current direction:

- plugin declares a typed block spec such as `resource_picker`
- plugin binds that block to a settings resource name and a persisted config key
- the host frontend maps approved block types to built-in React components

This gives plugin-backed settings more expressive UI without turning the plugin system into a dynamic frontend bundle loader.

The first intended use case is calendar source selection:

- backend plugin resource returns grouped calendars
- host frontend renders a calendar-list picker
- selected ids are persisted into normal plugin settings

## Plugin Temporal Summary Features

Plugins may also contribute structured temporal-summary features to the host memory system.

This is intended for source-specific aggregation that would be awkward to infer only from raw L1 events.

Examples:

- browsing domain concentration and revisit patterns for browser history
- calendar density and recurring-event distribution for calendar sources
- repository focus shifts for git activity

The boundary is:

- plugins provide structured features and summary hints
- the host L3 pipeline remains the only component that produces final summary records

The current hook shape is:

- plugin hook:
  - `build_temporal_summary_features(source_type, events, summary_category, period_start, period_end)`
- host runtime:
  - loaded plugins are asked for features during temporal summary generation
  - returned feature payloads are attached to the temporal evidence pack
  - the generic L3 summarizer consumes those features alongside the normal event evidence

Plugins must not bypass the host L3 store by writing standalone summary records.

This keeps summary generation source-aware without splitting L3 into per-plugin summary pipelines.

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
- `GET /api/plugins/{plugin_id}/settings/resources/{resource_name}`

Timeline source status also now reflects plugin-backed sensor registration:

- [timeline.py](/Users/asuka/code/magi/backend/src/magi/api/routers/timeline.py)

## Official Built-In Plugins

Magi currently ships two general built-in plugin packages:

- `core-tools`
  registers built-in tools

- `photo-library`
  registers the local photo library timeline source

These packages are enabled by default through config defaults.

Magi also ships additional built-in timeline sensor packages. These packages are enabled by default so their settings remain discoverable, while their individual sources stay disabled until the user opts in:

- `chrome-history`
  registers the local Chrome history timeline source

- `calendar`
  registers calendar event ingestion on supported Apple platforms

- `git-activity`
  registers local git activity ingestion

- `screen-time`
  registers sampled frontmost-app usage ingestion on supported Apple platforms

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

- timeline event projections are derived from ingested sensor outputs
- sensor definitions and sensor settings cards are derived from `SensorRegistry`
- sensors may still declare `domain="timeline"` when their outputs should participate in timeline-oriented downstream projections
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
- [Sensor base contract](/Users/asuka/code/magi/backend/src/magi/awareness/sensor_base.py)
- [Sensor output models](/Users/asuka/code/magi/backend/src/magi/awareness/sensor_output.py)
- [Ingestion gateway](/Users/asuka/code/magi/backend/src/magi/awareness/ingestion_gateway.py)
- [Extraction profiles](/Users/asuka/code/magi/backend/src/magi/memory/l2/extraction_profiles.py)
- [L2 pipeline](/Users/asuka/code/magi/backend/src/magi/memory/l2/pipeline.py)

## Related Documents

- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
- [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md)
- [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md)
- [Memory System Design](/Users/asuka/code/magi/docs/memory-system-design.md)
