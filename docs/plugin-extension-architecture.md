# Unified Plugin Extension Architecture

## Purpose

This document describes the current unified plugin runtime in Magi.

It is the implementation-facing guide for:

- maintainers evolving plugin loading and registration
- contributors wiring new tools, timeline sensors, channels, or plugin ingress handlers
- frontend contributors building settings surfaces for plugin-backed capabilities

The manifest contract recognizes `tool`, `sensor`, `channel`, `skill`, and
`hook`. The shared plugin registrar currently consumes tools, sensors, channels,
and hooks. Skill loading remains separate and is not driven by a plugin's
`get_skills()` hook today.

## Design Goals

The plugin runtime exists to solve three problems:

- stop hardcoding registration paths separately for tools, sensors, channels, and ingress handlers
- let built-in and external plugins use the same discovery and lifecycle model
- expose a declarative settings contract that the frontend can render without loading plugin-owned UI code

## Runtime Model

Each plugin package is a backend Python package that may contribute one or more capability types:

- tools
- sensors
- channels
- skills
- hooks

Tools, sensors, channels, and hooks register through the shared plugin lifecycle.
Although `skill` is a recognized manifest value and the SDK exposes
`get_skills()`, `PluginManager` does not consume that hook today. A plugin may
also register host-routed ingress handlers through
`get_plugin_ingress_registrations()`; those handlers are backend-dispatched events,
not a separate `PluginContribution` type.

A plugin package is discovered from disk, parsed from `plugin.toml`, loaded from a Python entry module, then registered into one or more runtime registries.

At runtime the flow is:

1. `PluginInstallService` coordinates registry, upload, update, and uninstall requests before package scanning
2. `PluginManager` scans plugin roots for `plugin.toml`
3. discovered packages are persisted into split plugin config files under `~/.magi/config/plugins/`
4. packages are disabled by default unless they are official built-in packages enabled by default config
5. enabled packages are instantiated through the shared `Plugin` base class
6. `PluginContributionRegistrar` registers or records host-facing contributions:
   - `ToolRegistry`
   - `SensorRegistry`
   - hook registry
   - channel contribution metadata consumed by the channel lifecycle module
7. `PluginSettingsService` serves plugin-owned settings resources and settings actions
8. `PluginProjectionService` collects loaded plugin projection hooks for memory summaries and recall artifacts
9. plugin ingress handlers are collected by the plugin ingress processor
10. APIs and frontend settings surfaces read registry state and plugin package state rather than hardcoded lists

## Scan Paths

The plugin manager scans two roots:

- repository built-ins: `plugins/`
- user-installed plugins: `~/.magi/plugins/` (marketplace installs and manually placed plugins)

These roots are persisted in:

- [models.py](../backend/src/magi/config/models.py)

under:

- `plugins.scan_paths`

## Package Structure

A plugin package is a directory containing:

- `plugin.toml`
- a Python entry module, currently `plugin.py` by default

Official built-in examples live in:

- [core-tools](../plugins/core-tools/plugin.py)

External plugin examples live in the separate plugin repository (`github.com/asukaonly/magi-plugins`):

- `chrome-history/` — full-featured sensor with entity hints, batch policies, and metadata extraction
- `telegram/` — bidirectional channel adapter
- `screen_time/` — sensor plus plugin ingress handler pair backed by local host events

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
- `permissions.capabilities`
- `dependencies`
- `depends_on`
- `kind`

The typed contract lives in:

- [contracts.py](../backend/src/magi/plugins/contracts.py)

## Base Plugin Contract

Every plugin entry class must inherit:

- [Plugin](../backend/src/magi/plugins/base.py)

The base contract exposes the current authoring hooks consumed by the runtime:

- `get_tools()`
- `get_sensors()`
- `get_channel()`
- `get_channel_fields()`
- `get_plugin_ingress_registrations()`
- optional `build_recall_artifacts()` for source-owned answer-facing recall refs

A single plugin package may implement any combination of these.

The manager binds two pieces of runtime state before registration:

- parsed manifest
- persisted plugin settings

## Runtime Services

The plugin manager is the package lifecycle owner, but it does not act as the execution surface itself.

Instead, lifecycle work is split across runtime services:

- `PluginManager` owns package discovery, package state, enable/disable/reload coordination, and plugin instance lifetime
- `PluginInstallService` owns registry install, upload install, update, uninstall orchestration, dependency closure resolution, and install-time registry metadata persistence
- `PluginContributionRegistrar` owns host registry registration and unregistration for tools, sensors, channels, and hooks
- `PluginSettingsService` owns plugin settings resources and settings action sessions
- `PluginProjectionService` owns plugin-provided memory summary, extraction profile, and recall artifact projection
- dedicated runtime modules own execution after registration, such as tool execution, sensor sync, channel delivery, memory projection, and plugin ingress processing

## Marketplace Registry Distribution

The public marketplace registry is authored in the external `magi-plugins`
repository, but the runtime default reads the current `registry.json` directly
from GitHub:

- `https://raw.githubusercontent.com/asukaonly/magi-plugins/main/registry.json`

The mutable `main` index deliberately avoids a long-lived CDN cache so newly
published plugin metadata, including packaged icons, becomes visible within
the host's five-minute registry refresh window.

The host keeps a five-minute memory cache and a durable offline fallback, so
normal marketplace browsing does not issue one raw-file request per surface.
Operators can still override the URL with `plugins.registry_url` for internal
mirrors, staged registries, or future cache-invalidation-aware CDN endpoints.

First-context and empty-source recommendations reuse this same registry client
and cache rather than maintaining a separate catalog connection. When neither
the remote index nor the disk cache is available, the installable-source API
reports an installed-only catalog so product surfaces can keep local plugins
usable while explaining that the marketplace is temporarily unreachable.

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

#### Local File Reply Boundary

When a plugin wants the assistant to send back local files such as photos, keep the ownership split explicit:

- source plugins own domain resolution and selection
- the host runtime owns chat attachment import, persistence, and display

Current flow:

1. a source plugin returns compact `asset_refs` and records its source-owned resolver tool when later resolution is supported
2. a follow-up turn calls the recorded source resolver to obtain current local file paths or source evidence
3. the host-owned `prepare_chat_attachments` tool imports those files into managed chat attachment storage for the active turn
4. the assistant response persists `attachments` payloads and the frontend renders them like other chat history attachments

For follow-up turns, tool results may also return an `assistant_payload` object. The host runtime persists that object into the assistant message payload after sanitization. The current reusable host contract is:

- `asset_refs`

These references are intended for reply-turn reuse, not direct frontend file access. Source plugins may include candidate identifiers, event ids, source item ids, capture timestamps, and original names, but the host runtime should strip raw local file paths before reinjecting the payload into LLM context or reply-context summaries.

For historical recall, plugins may also optionally implement `build_recall_artifacts(source_type, events, query, query_mode)` so source-owned metadata can be projected into generic answer-facing `entity_refs` / `asset_refs` during `memory_query`. This hook enriches answer contracts only; persistence ownership remains with memory and chat.

Plugins return resource identities, never desktop session credentials, private
resource tickets, or directly renderable local file URLs. The host performs the
final import or private-resource ticket exchange and keeps those temporary
grants out of plugin state. Browser extensions and external collectors likewise
require a separately paired, revocable ingestion capability; they do not share
the Magi WebView credential.

This boundary keeps source-specific metadata layouts out of the chat domain and avoids treating raw local file paths as the long-lived chat protocol surface.

### Sensor Registry

Sensors are registered into `SensorRegistry` with:

- sensor instance
- `SensorSpec`
- owning `plugin_id`

The most important current consumers are the generic sensor status/scheduler flow and downstream timeline ingestion.

Timeline no longer owns the settings surface or operational status API for sensors. The host resolves sensor sources from `SensorRegistry`, while timeline remains a downstream read model that consumes ingested sensor outputs.

Builtin timeline sensor packages that should be configurable in Settings are expected to stay plugin-enabled even when their own source-level `enabled` switch is off. In other words, package activation controls whether the plugin participates in runtime discovery, while source activation controls whether the sensor actually syncs.

The contracts live in:

- [sensors.py](../backend/src/magi/plugins/sensors.py)

#### First-Context Activation Metadata

The onboarding first-context panel reuses the same activation flow as Settings, but
it may need a lighter initial sync than the long-term source defaults. Plugins can
declare a first-run item cap under
`activation_flow.first_context.max_items_per_sync` and other first-run-only
settings under `activation_flow.first_context.settings_overrides`. The host
frontend applies them only when the shared install/connect panel is opened from
first-context onboarding. The item cap defaults to 200 when a plugin omits it;
that value is a safety fallback rather than a plugin policy. Without other
overrides, the host preserves the user's submitted activation settings instead
of special-casing plugin ids.

Plugins that should be offered during onboarding opt in through
`suggestion_descriptor.surfaces.first_context`, which owns the order, rationale,
and scope shown there. Empty-source recommendations use the corresponding
`suggestion_descriptor.surfaces.empty_state` declaration. The host groups
siblings by suggestion category and does not own plugin-specific names, icons,
copy, or recommendation lists.

The first conversation prompt uses recent L1 evidence by event timestamp. Import
time is not a substitute for source time when the event already has a real
timestamp, so a newly imported historical photo or history item should not appear
as first-contact context solely because it was just backfilled.

#### One-Shot History Imports

Plain Markdown history import is host-owned because file selection, durable
per-file inclusion, preview, speaker identity, authorship confirmation,
progress, retry, deletion, first-contact use, and memory governance must behave
the same regardless of source format. The same host flow is available during
onboarding and later under Memory → Sources. It is not modeled as a sensor: an
import has a bounded input, an explicit user confirmation, and a completed
lifecycle rather than an ongoing polling schedule.

Future platform-specific import plugins should only adapt an export into the
host's normalized history records. They must not write memory directly, decide
which participant is the user, or own the preview and deletion experience. A
dedicated importer contribution contract is still future work; the current
runtime supports the host Markdown importer only.

### Channel Registry

Channels are bidirectional messaging adapters that connect Magi to external platforms (e.g. Telegram).

A plugin contributes a channel by implementing `get_channel()` and `get_channel_fields()` in its `Plugin` subclass. The channel lifecycle module discovers channel plugins from `PluginManager` and starts/stops them as part of the runtime lifecycle.

Channel contributions have their own settings surface in the frontend under "接入渠道 / Channels", following the same expandable sub-nav pattern as sensors.

## Sensor Memory Integration

### Data Flow

Sensor outputs flow through the memory system via the following chain:

```
SensorBase.build_output(item)     -> SensorOutput (activity, narration, provenance)
SensorBase.extract_metadata(item) -> SensorOutputMetadata (entity hints, tags, relations)
Host projection renderer          -> L1 content + timeline title/summary + embedding head
IngestionGateway.ingest()         -> MemoryEvent with metadata_json
L1 EventStore                     -> persisted fact event
L2 Pipeline                       -> cognition (graph, entities, assertions)
```

### SensorOutput

`SensorOutput` is the domain-neutral output produced by all sensors:

- `source_type` / `source_item_id`: identity
- `activity`: source-owned semantic truth (`source`, `action`, optional `object`, optional `qualifiers`)
- `narration`: source-owned factual narration (`body`, optional `title`)
- `content_blocks`: auxiliary content anchors for downstream processing
- `tags` / `entities`: classification
- `provenance`: source-specific metadata (sensor_id, domain, visit_id, etc.)
- `domain_payload`: extra structured data for downstream consumers

`domain_payload` may include source-level cognition hints such as `promotion_key`.
For high-volume passive sources, `promotion_key` should identify the stable
aggregation unit (for example, a browser domain) so L2 batching and derived
assertion rules can evaluate repeated evidence instead of one-off events.

`domain_payload.source_facets` is the preferred contract for source-owned
structured recall keys. It is a list of small field objects:

- `name`: stable facet name such as `photo.location_name`, `browser.domain`,
  `music.artist`, or `music.play_count`
- `text`: optional exact text value for lookup
- `numeric`: optional numeric value for counting or summing
- `timestamp`: optional source timestamp
- `json`: optional compact structured payload when text/numeric/timestamp are
  insufficient

Plugins should emit facets only for stable source facts that can be rebuilt from
the source item or plugin cache. The host owns the `L1` facet index and the
query-side expansion logic; plugins should not import memory internals or decide
whether a total-count claim is safe.

Important ownership split:

- plugins own `activity` and `narration`
- plugins may own stable source facets for exact recall expansion
- the host runtime owns final human-facing display text and retrieval-oriented embedding projections
- `L1` does not treat plugin-authored display strings as the source of truth for external activity

The host renders three projections from one `SensorOutput`:

- `L1 content`: canonical persisted event text
- `TimelineEvent.title` / `TimelineEvent.summary`: UI-facing timeline text
- `projection.embedding_head`: compact dense-retrieval hint stored in `MemoryEvent.metadata_json.projection`

The host persists only the minimum stable semantic envelope needed for later filtering and audit:

- `activity.source_code`
- `activity.action_code`
- optional `activity.object_code`
- optional `activity.qualifiers`
- `plugin_id` / `sensor_id`
- `projection.renderer_version`

Static alias lists or multi-language label tables should stay in plugin i18n resources or the SDK contract, not be duplicated into every `L1` event row.

### SensorOutputMetadata

`SensorOutputMetadata` is extracted separately from the raw source item and carries:

- `entities`: structured entity hints (list of dicts with `mention_text`, `entity_type`, `canonical_name_hint`)
- `tags`: classification/search labels, not fact evidence
- `fact_hints`: preferred source-owned structured facts for L2 cognition
- `relation_candidates`: legacy/timeline-compatible relation projections

Entity hints are passed through the ingestion gateway as `structured_entity_hints` in `MemoryEvent.metadata_json`. In the L2 pipeline, these hints are injected into the Phase 1 LLM prompt as **context anchors** — they help the LLM resolve entities to consistent canonical names and types, but are NOT automatically materialized into the entity catalog. Only entities that the LLM independently extracts in Phase 1 output become persisted entities.

`fact_hints` are the preferred L2 structured-fact path. They let the source describe high-confidence SPO-style facts while the host still owns evidence classification, profile allowlists, conflict handling, and persistence. Passive observations should normally emit interaction evidence (`VIEWED`, `LISTENED`, `USED`, `VISITED`) rather than direct preference claims.

`relation_candidates` remain for backward compatibility with older timeline/relation projections. New sensors should not use them as the primary L2 cognition path; migrate source facts to `fact_hints` so they pass through the same admission and evidence governance.

Tags are never a substitute for fact evidence. A tag, page category, or weak co-occurrence may help search or UI grouping, but it must not be promoted into a user preference unless the source has a stable, explainable signal such as an explicit favorite/subscription list, configuration export, or repeated interaction that is later aggregated by host-owned derived rules.

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
  Backward-compatibility field for older plugins and timeline projections; new L2 cognition work should use `fact_hints`

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

Plugins can also contribute `ExtractionProfileSpec.derived_assertion_specs` for host-owned graph-derived assertions. These specs do not let plugins write assertions directly. They declare how accumulated graph evidence can be aggregated later, and the host validates predicates, assertion families, trait namespaces, source types, source tiers, and conflict behavior before writing any assertion.

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

- [memory-system-design.md](./memory-system-design.md)

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

Conversation events with a session are grouped by session. Events without a session are grouped by
normalized source, optional plugin owner, and user together. A plugin owner therefore refines a
source batch; it never replaces source or user isolation. Every event in a flushed batch keeps its
own evidence policy and structured hints, even when multiple events share one owner bucket.

The ingestion gateway propagates these hints into `MemoryEvent.metadata_json` as `l2_batch_owner`, `l2_batch_max_events`, `l2_batch_max_estimated_tokens`, and `l2_batch_max_wait_seconds`. The L2 pipeline reads them back to create appropriately scoped `L2PendingBatchBucket` instances.

### Extraction Profiles

Each event source is mapped to an `ExtractionProfile` that controls what the L2 LLM is allowed to produce:

```python
@dataclass(slots=True, frozen=True)
class ExtractionProfile:
    profile_id: str
    source_types: frozenset[str]
    allowed_entity_types: frozenset[str]
    allowed_predicates: frozenset[str]
    structured_allowed_entity_types: frozenset[str] | None
    structured_allowed_predicates: frozenset[str] | None
    allowed_assertion_families: frozenset[str]
    allowed_assertion_traits: frozenset[str] | None
    entity_type_aliases: dict[str, str]
    predicate_aliases: dict[str, str]
    subject_policy: DefaultSubjectPolicy
    allow_graph: bool
    allow_assertion: bool
    assertion_mode: str
    extraction_instructions: str | None
    phase1_instructions: str | None
    phase2_instructions: str | None
    derived_assertion_specs: tuple[dict[str, Any], ...]
```

Key fields:

- `allowed_entity_types`: LLM-extracted entities with types outside this set are filtered out before catalog registration.
- `allowed_predicates`: LLM-extracted graph edges with predicates outside this set are dropped.
- `structured_allowed_*`: allowlists for source-owned structured hints; these can be broader or narrower than LLM-facing extraction allowlists.
- `allow_assertion`: master switch for assertion writes from this profile.
- `assertion_mode`: `none` rejects assertions, `derived` allows only host-owned graph-derived assertion rules, and `phase2_candidate` allows Phase 2 LLM candidates subject to policy/family/trait gates.
- `allowed_assertion_families`: canonical assertion families this source may emit or derive. Current families are `stress`, `mood`, `engagement`, `trigger`, `relationship_shift`, `group_atmosphere`, `public_sentiment`, `identity_profile`, `communication_profile`, `preference_profile`, `routine_profile`, and `state_profile`.
- `allowed_assertion_traits`: optional exact or namespace allowlist (`music.*`) for assertion trait names.
- `source_types`: normalized event sources routed to this profile.
- `phase1_instructions` / `extraction_instructions`: free-text instructions injected into the LLM Phase 1 prompt under a `## Source-Specific Instructions` section.
- `phase2_instructions`: source-specific semantic guidance injected into the Phase 2 prompt. It may guide higher-order assertion meaning, but cannot alter graph writes, evidence binding, confidence, lifecycle, expiry, or conflict actions.
- `derived_assertion_specs`: plugin-declared graph-derived assertion specs. The host compiles these into validated rules and runs them in the L2 derive schedule; plugins never bypass assertion lifecycle, source-tier, or conflict protection.

Assertion families and assertion trait/schema identifiers are assertion-only. They must not be emitted as graph predicates, graph object refs, or concept nodes; graph admission validates this boundary before persistence. `preference_profile` covers durable interests, affinities, tastes, and preferences; `routine_profile` covers repeated behavior rhythms and habits. Family policy is host-owned and determines Phase 2 guidance, default lifecycle/decay, snapshot placement, and value-localization expectations. Trust and conflict decisions remain source-tier governed, so plugin-derived inference cannot overwrite user-authored assertions.

Profile mapping uses the normalized event source. Source-specific profiles are contributed by loaded plugins through `Plugin.get_extraction_profiles()` using the SDK `ExtractionProfileSpec` contract. The host owns ontology, schema validation, prompt assembly, and final write guards. Profile IDs use the `source.*` namespace for external/source-specific events so they are not confused with the product Timeline surface. New source types fall back to the unrestricted `chat.user_message` default profile.

Current host-owned profiles include:

- `chat.user_message` - unrestricted default

Plugin-contributed profiles include examples such as:

- `source.chrome_history` - selective entity types, no assertions, detailed extraction instructions
- `source.git_activity` - software/project focused
- `source.screen_time` - software/activity focused

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
- `path_kind` (`file` or `directory`) for a scalar `path` field that should use
  a native picker; array-valued path fields continue to use the multi-directory
  picker
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

- [plugins.ts](../frontend/src/api/modules/plugins.ts)
- [PluginSettingsFields.tsx](../frontend/src/components/settings/PluginSettingsFields.tsx)

## Plugin Settings Resources

Some plugin-backed settings need dynamic runtime data that cannot be expressed as a fixed field option list.

Examples:

- calendar account / calendar-list selection after authorization
- repository pickers for git-backed sensors
- mailbox or album selection for source-specific sync scopes

For these cases, plugins may expose read-only settings resources through the backend plugin contract.

The host API remains generic. It does not add per-plugin endpoints.
The API delegates settings reads and settings action sessions to `PluginSettingsService`;
it does not inspect loaded plugin instances directly.

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

## Plugin Settings Actions

Some plugin-backed setup flows require an imperative step rather than a static
field or read-only resource. Examples include QR-code login, OAuth device-code
authorization, or a provider-specific connection test.

These flows use plugin settings actions. The host API and UI remain generic:

- plugin hook:
  - `get_settings_actions()` declares host-rendered actions
  - `start_settings_action(action_id, session_id, field_values)` starts a session
  - `poll_settings_action(action_id, session_id, field_values)` polls a session
  - `cancel_settings_action(action_id, session_id)` cancels a session
- host API:
  - `POST /api/plugins/{plugin_id}/settings/actions/{action_id}/start`
  - `POST /api/plugins/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/poll`
  - `POST /api/plugins/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/cancel`

The plugin owns protocol details and temporary provider state. The host owns
session ids, routing, status polling, generic QR-code rendering, and optional
persistence of plugin-returned `settings_updates` when the action spec sets
`persist_settings_on_success=True`.

Core Magi code must not add provider-specific routes such as a Weixin login
endpoint. A Weixin plugin declares a QR-code settings action; another provider
can reuse the same host surface with its own plugin implementation.

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
  - `build_temporal_summary_features(source_type, events, summary_category, period_start, period_end, budget=None)`
- host runtime:
  - loaded plugins are asked for features during temporal summary generation
  - the host may pass only a bounded event pool, not every L1 event in the window
  - `budget` is a `TemporalSummaryFeatureBudget` reporting source-level total, available, selected, omitted, and policy information
  - returned feature payloads are attached to the temporal evidence pack
  - the generic L3 summarizer consumes those features alongside the normal event evidence

Recommended return shape is either a plain dictionary or `TemporalSummarySourceFeatures` from the SDK contract:

```python
def build_temporal_summary_features(
    self,
    *,
    source_type: str,
    events: list[dict[str, object]],
    summary_category: str,
    period_start: float,
    period_end: float,
    budget: TemporalSummaryFeatureBudget | None = None,
) -> TemporalSummarySourceFeatures | dict[str, object] | None:
    ...
```

Feature payloads should include source-local facts such as `summary_lines`, `top_entities`, `top_tags`, `time_buckets`, `representative_event_ids`, `total_event_count`, `covered_event_count`, `omitted_event_count`, and `coverage_ratio`. They should not include unbounded raw records or imply that the plugin saw every event when the budget says the host compacted the window.

The public SDK types live in:

- [contracts.py](../sdk/src/magi_plugin_sdk/contracts.py)

Plugins must not bypass the host L3 store by writing standalone summary records.

This keeps summary generation source-aware without splitting L3 into per-plugin summary pipelines.

## Plugin Display Metadata

Plugin manifests own their visual identity through one of two icon declarations:

- `asset:assets/icon.svg` for a brand or product image packaged with the plugin
- `lucide:<icon-name>` for a generic icon from the host's bundled Lucide library

Registry generation validates packaged SVG, PNG, or WebP files, enforces a
64 KiB size limit, and embeds the safe image as `icon_data` so marketplace and
consent surfaces can display it before installation. Installed-plugin,
suggestion, and sensor APIs resolve the same file from the installed package.
The frontend renders validated image data or looks up any named Lucide icon;
it does not contain plugin-specific brand mappings.

SVG assets must be self-contained. The registry and runtime reject scripts,
embedded content, event handlers, external references, entities, and URL-based
styles. Asset paths must stay inside the plugin package and cannot be symlinks.

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
- per-channel settings

Frontend surfaces:

- [Settings.tsx](../frontend/src/pages/Settings.tsx)
- [PluginsSection.tsx](../frontend/src/components/settings/PluginsSection.tsx)
- [TimelineSourcesSection.tsx](../frontend/src/components/settings/TimelineSourcesSection.tsx)
- [ChannelsSection.tsx](../frontend/src/components/settings/ChannelsSection.tsx)

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
  - `packages.<plugin_id>.official`
  - `packages.<plugin_id>.consented_capabilities`
- `~/.magi/config/plugins/<plugin_id>.yaml`
  - plugin-owned `settings`

This keeps host runtime configuration separate from plugin lifecycle state and reduces churn in the main config file as plugin surfaces grow.

## API Surface

The unified plugin management API lives in:

- [plugins.py](../backend/src/magi/api/routers/plugins.py)

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

- [timeline.py](../backend/src/magi/api/routers/timeline.py)

## Built-In And Example Plugins

The current repository includes the built-in `core-tools` plugin package.

Most sensor and channel examples currently live in the separate `magi-plugins`
repository and are installed as external plugins during development or marketplace flows.

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

## Actions Surface Status

There is no dedicated action contribution surface in the current frontend or backend
plugin runtime.

In the current codebase:

- `ContributionType` contains `tool`, `sensor`, `channel`, `skill`, and `hook`
- `PluginManager` registers tools, sensors, channels, and hooks; its `get_skills()` hook is not wired into runtime loading
- the frontend settings UI exposes plugin-backed sections for installed plugins, timeline sources, and channels only
- there is no `get_actions()` hook or `ActionRegistry` implementation under `backend/src/magi/`

Treat action support in older documents as future-facing design, not current runtime behavior.

## Plugin Marketplace

External plugins are hosted in the `magi-plugins` repository (`github.com/asukaonly/magi-plugins`).

### Registry

The marketplace index is a `registry.json` file at the repository root containing an array of `PluginRegistryEntry` objects:

- `plugin_id` - unique identifier matching the plugin's `plugin.toml`
- `name` - display name
- `version` - semver string
- `path` - subdirectory path within the repository
- `description` - short description
- `author` - plugin author
- `icon` - packaged asset reference or generic Lucide icon declaration
- `icon_data` - registry-generated, validated image data for packaged icons
- `official` - whether the plugin is maintained by the Magi team
- `contribution_types` - array of declared contribution types supported by the current contracts (`sensor`, `channel`, `tool`, `skill`, `hook`)
- `capabilities` - user-visible access declarations copied from the plugin manifest
- `kind` and `depends_on` - package-library and plugin dependency metadata when present
- `platforms` - array of supported platforms (`macos`, `windows`, `linux`)

### Registry Authority And Install Consent

Marketplace trust is not self-declared by a plugin package.

- the external registry derives `official` from the maintainer-controlled
  `official-plugins.json` allowlist
- an external plugin's `official = true` manifest value is ignored unless its
  plugin id is in that allowlist
- built-in packages may use their bundled manifest value; uploaded packages are
  always treated as non-official
- registry installs persist the registry-derived value, and installed-plugin
  responses read that persisted value rather than trusting a local manifest

Plugins declare user-visible access under
`[[plugin.permissions.capabilities]]`. The external registry validates each
capability against the shared known set and copies the declaration into
`registry.json`. The product shows these declarations before install. Updates
prompt again only when a new capability, a new scope, or a broader scope exceeds
the user's stored consent. Uploaded packages are inspected before installation
so the same review applies to sideloads.

Capability declarations are disclosure and review metadata. They do not provide
an operating-system sandbox, so runtime enforcement still depends on the host's
existing permission and trust boundaries.

### Dependency Integrity

A plugin that declares Python dependencies must ship a generated
`requirements.lock` containing exact versions and hashes. The installer uses
that lock with hash verification and refuses ordinary installation when the
lock is missing. `MAGI_ALLOW_UNLOCKED_PLUGIN_DEPS=1` exists only as an explicit
developer-mode escape hatch and must not be treated as a normal distribution
path.

The companion plugin repository regenerates lockfiles and `registry.json`
together. Its CI checks both outputs for drift, so a manifest or dependency
change is not complete until the generated artifacts are committed with it.

### Installation Flow

1. The frontend starts an install, update, or upload job through the plugin API and polls the returned `job_id`
2. The backend job reports `status`, `stage`, `progress_pct`, installer messages, and bounded install logs while work continues in the background
3. `PluginInstallService` owns the install or update workflow and delegates registry reads/downloads to `RegistryClient`
4. For registry installs, `RegistryClient.fetch_index()` fetches `registry.json` from the remote
   repository, persists the last successful index under the local plugin cache, and falls back to
   that cached index if the remote registry is temporarily unavailable
5. `RegistryClient.clone_plugin()` downloads the GitHub repository tarball, with short-lived in-memory caching for repeat install requests
6. The requested plugin subdirectory is extracted from the tarball into a temporary directory
7. `PluginManager.install_plugin_from_directory()` copies the plugin into `~/.magi/plugins/<plugin_id>/`
8. Python dependencies declared by the plugin are installed from its hash-verified `requirements.lock` into the plugin-local `.deps/` directory; pip output is attached to the install job logs. Source/dev runs use the active backend Python. Packaged desktop runs pass `Contents/Resources/plugin-python/.../python` through `MAGI_PLUGIN_PYTHON`; the packaged `magi-backend` sidecar is never used as a pip executable.
9. The plugin is discovered on next scan and can be enabled from the settings UI

Packaged desktop builds stage two generated runtime resources under `frontend/src-tauri/`: `sidecar-dist/` for the backend sidecar and `plugin-python/` for plugin dependency installation. Release CI runs `scripts/prepare-plugin-python-runtime.py` to download a python-build-standalone runtime for the target platform, writes it to `MAGI_PLUGIN_PYTHON_SOURCE`, and requires that source during sidecar staging. Local development builds may omit the variable and use a local venv fallback. macOS signing scripts sign Mach-O files in both runtime resource roots before notarization.

### Frontend

The marketplace UI lives in the Plugins settings section under "插件市场 / Marketplace". It shows available plugins with manifest or registry icons, install/uninstall actions, version info, platform compatibility badges, and install progress with job logs. The onboarding sensor-selection step uses the same install job API for selected sensor plugins.

## Known Boundaries

The current plugin runtime is intentionally scoped.

It does not yet support:

- plugin-owned frontend bundles
- hot code sandboxing or permission isolation beyond trust/enable state
- plugin-defined `action` contribution registration
- arbitrary awareness-module sensor registration through the old awareness abstractions

The current system is a local backend Python extension model.

## Related Files

- [Plugin manager](../backend/src/magi/plugins/manager.py)
- [Plugin runtime exports](../backend/src/magi/plugins/__init__.py)
- [Registry client](../backend/src/magi/plugins/registry_client.py)
- [Config models](../backend/src/magi/config/models.py)
- [Plugins API](../backend/src/magi/api/routers/plugins.py)
- [Timeline API](../backend/src/magi/api/routers/timeline.py)
- [Sensor base contract](../backend/src/magi/awareness/sensor_base.py)
- [Sensor output models](../backend/src/magi/awareness/sensor_output.py)
- [Ingestion gateway](../backend/src/magi/awareness/ingestion_gateway.py)
- [Extraction profiles](../backend/src/magi/memory/l2/extraction_profiles.py)
- [L2 pipeline](../backend/src/magi/memory/l2/pipeline/)

## Related Documents

- [Project Overview](./project-overview.md)
- [Product Configuration Guide](./product-configuration-guide.md)
- [Plugin Development Guide](./plugin-development-guide.md)
- [Memory System Design](./memory-system-design.md)
