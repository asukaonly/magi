# Personal Knowledge Timeline Design

## Summary

Magi will gain a new long-term user understanding capability: `Personal Knowledge Timeline`.
This capability is not a separate runtime outside the current architecture. It is a new domain built on top of Magi's existing sensor hub, task-agent runtime, memory layers, and React shell.

Phase 1 focuses on four sources:
- chat conversation
- manual journal entries
- browser history
- local photo library

The goal is to let Magi build a trustworthy, explainable, user-centric timeline and user knowledge graph that can support future assistant behavior without forcing all data into one storage policy.

## Goals

- Build a unified timeline of user activity from multiple sources.
- Allow each source to choose between raw retention and analyze-only behavior.
- Upgrade L1 into a timeline-oriented fact layer that remains traceable to real source data.
- Replace the current L2 event-relation direction with a user-centric relationship graph.
- Add a dedicated timeline page that replaces the chat area instead of using a drawer or modal.
- Keep third-party integrations extensible through plugin-like sensor contracts.

## Non-Goals For Phase 1

- Social media ingestion
- Shopping platform ingestion
- Voice journal input
- Calendar view
- Graph-first visualization page
- Full historical backfill and rebuild tooling
- Agent-internal reasoning graph in L2

## Architecture

### Runtime Mapping

The new capability should fit the existing Magi runtime rather than create a parallel architecture.

- `Source Connectors` become specialized timeline sensors.
- `Timeline Ingestion Hub` becomes a new `TimelineTaskAgent`.
- `Retention & Asset Layer` stays outside the task agent as an independent service invoked by it.
- `Insight Pipeline` stays outside the task agent as an independent processing chain invoked by it.
- `Timeline UI` becomes a first-class routed page backed by timeline APIs.

### Responsibilities

#### Timeline Sensors

Timeline sensors detect changes from supported sources and emit normalized sensor events into the runtime.

Phase 1 sensors:
- chat sensor
- manual journal sensor
- browser history sensor
- photo library sensor

Sensors should not write directly to L1, L2, or storage backends. Their job is source discovery, source fetch, and event normalization.

#### TimelineTaskAgent

`TimelineTaskAgent` is the orchestrator for long-term user understanding. It should:

- receive timeline-related sensor facts
- deduplicate and enforce idempotency
- decide whether raw retention is required
- trigger retention handling
- trigger insight extraction
- coordinate writes into L1, L2, L3, and L4
- expose status that can be surfaced in settings and timeline UI

It should not become a god object. Source-specific logic, storage behavior, and relation extraction must remain delegated to smaller units.

#### Retention & Asset Layer

This layer executes per-source retention policy.

It is responsible for:
- saving retained assets into managed local storage
- maintaining references to external user-managed paths when direct access is configured
- storing page captures, extracted text, thumbnails, or asset metadata when applicable
- recording audit metadata about what was and was not retained

#### Insight Pipeline

This layer extracts structured knowledge from timeline events.

Phase 1 outputs:
- L1 timeline facts
- L2 user knowledge graph
- L3 embeddings
- L4 summaries

Future agent-internal graph work is explicitly deferred.

## Data Model

### TimelineEvent

All supported sources should normalize into a common `TimelineEvent` model.

Required fields:
- `event_id`: globally unique event id
- `source_type`: `chat` | `manual_journal` | `browser_history` | `photo_library`
- `source_item_id`: stable source-native identifier for incremental sync
- `occurred_at`: when the user activity happened
- `captured_at`: when Magi detected or ingested it
- `title`: short display label
- `summary`: human-readable description for timeline rendering
- `raw_payload_ref`: reference to retained content, external path, or null
- `retention_mode`: `retain_raw` | `analyze_only`
- `content_blocks`: normalized content blocks, Phase 1 supports `text` and `image`
- `entities`: extracted entity candidates
- `tags`: normalized labels for topic, source, activity, or context
- `privacy_labels`: sensitivity and policy metadata
- `processing_status`: per-stage processing state
- `provenance`: sensor id, sync batch id, rule decisions, and processing lineage

### L1

L1 should become the foundational timeline fact store.

L1 stores:
- normalized timeline facts
- references to retained raw content or external paths
- analyze-only summaries when raw content is not retained
- provenance and processing status

L1 should not be overloaded with binary asset bodies. Raw assets live in the retention layer and are referenced from L1.

### Retention Policy Model

Retention is determined in two layers:

- source default policy
- event-level resolved policy

This allows settings to stay understandable while preserving per-event outcomes.

Examples:
- browser history may default to `analyze_only`
- photo library may default to `retain_raw`
- a specific event may override the default because of a rule or user action

### L2

Phase 1 L2 is a `User Knowledge Graph`, not an event chain graph.

The graph is centered on `user:self` and expands to nodes such as:
- `person`
- `place`
- `organization`
- `brand`
- `product`
- `topic`
- `interest`
- `activity`
- `media_asset`

Allowed edge examples:
- `LIKES`
- `DISLIKES`
- `CARES_ABOUT`
- `INTERACTED_WITH`
- `VISITED`
- `PURCHASED`
- `VIEWED`
- `CREATED`
- `CAPTURED`
- `OWNS`
- `MENTIONED`
- `RELATED_TO`

### Edge Extraction Rules

Edge creation must be constrained by event type.

Rules:
- each source type has a default allowed edge whitelist
- the system normalizes extracted relation candidates into a finite edge set
- expert mode may adjust the whitelist in settings
- edges must keep evidence references to supporting L1 events

Examples:
- browser history may create `VIEWED`, `VISITED`, `CARES_ABOUT`, `LIKES`
- photo library may create `CAPTURED`, `RELATED_TO`, `INTERACTED_WITH`
- manual journal may create `LIKES`, `DISLIKES`, `CARES_ABOUT`, `MENTIONED`

Each L2 edge should carry:
- supporting event ids
- confidence
- first observed time
- latest observed time
- source-type distribution

### L3 and L4

Phase 1 preserves the conceptual role of these layers:

- L3 stores embeddings for timeline events and graph-related summaries
- L4 stores time-window and topic summaries, such as recent interests or repeated interactions

## Timeline Sensor Extension Contract

All third-party or local timeline integrations should implement a common timeline sensor contract.

Each sensor should declare:
- `sensor_id`
- `display_name`
- `source_type`
- `polling_mode`: `manual` | `interval` | `watch`
- `default_interval`
- `supports_retention_modes`
- `supports_content_blocks`
- `update_key_fields`
- `config_schema`
- `relation_edge_whitelist`
- `capabilities`

Each sensor should expose the following lifecycle methods:
- `discover_changes`
- `fetch_item`
- `build_timeline_event`
- `resolve_retention_assets`
- `extract_candidates`

### Update Detection

Update detection should be standardized with two concepts:

- `source_item_identity`: fields that mean "this is the same source object"
- `source_item_version_fingerprint`: fields that mean "this object has changed"

Examples:

- browser history
  - identity: `url + visit_time_bucket`
  - fingerprint: `title + visit_count + fetched_content_hash`

- photo library
  - identity: `asset_local_id`
  - fingerprint: `modified_at + analysis_scope + optional file hash`

### Browser History Policy

Phase 1 browser history behavior:
- always ingest URL, title, visit time, and visit count
- allow opt-in secondary content fetch for matched pages
- do not default to full-page capture

## UI and Product Experience

### Navigation

Add a top-level `Timeline` entry alongside personality, memory, and settings.
Selecting it should navigate to `/timeline` and replace the right-side chat content with a full page.

### Timeline Page

Phase 1 should provide:

- top controls for date range, source filters, and view mode
- a primary action for creating a manual entry
- a feed of timeline cards sorted by time
- inline card expansion for details
- a secondary context panel or section for summary signals

Each timeline card should be able to show:
- source and timestamp
- title and summary
- image previews where relevant
- retention state
- extracted entities and tags
- evidence and derived knowledge on expansion

### Manual Entry

Manual entry is part of the same timeline model, not a separate diary subsystem.

Phase 1 manual entry supports:
- text
- image attachment

Manual entries are normalized into `manual_journal` events and processed through the same retention and insight pipeline as passive sources.

### Settings

Add a `Timeline & Sources` configuration area.

Per-source settings should include:
- enabled state
- connection or permission status
- sync mode
- sync interval
- default retention mode
- storage path or external reference mode
- analysis scope
- update key configuration
- privacy filters
- secondary fetch enablement when supported
- edge whitelist adjustment in expert mode
- manual sync action
- last success and last error state

## Privacy and Trust

Phase 1 must prioritize user control and explainability.

Requirements:
- each source has an independent enable switch
- sensitive sources default to safer collection settings
- browser body fetching is opt-in
- photo library access can be scoped to a selected directory
- every event can show what was stored, where it lives, and what knowledge was derived
- future deletion flows must be able to remove both timeline facts and graph evidence

## Reliability and Error Handling

### Source-Level Failures

Examples:
- missing permissions
- unreadable browser history database
- missing photo directory
- unsupported image parsing

These failures should be isolated to the failing source and surfaced in settings.

### Event-Level Failures

Examples:
- retention failure
- extraction failure
- embedding failure

Events should support partial completion. Failure in one downstream stage should not discard the whole event.

### Idempotency

Requirements:
- repeated scans of the same source item must not create duplicate timeline events
- repeated reprocessing must not create duplicate graph edges
- evidence aggregation must stay stable across retries

### Recovery

Phase 1 should support:
- per-source manual resync
- per-event reanalysis

Phase 1 should not include a full rebuild console.

## Delivery Roadmap

### Phase 1A: Event Foundation

- define `TimelineEvent`
- introduce `TimelineTaskAgent`
- support chat and manual journal ingestion
- write L1 facts
- expose basic timeline APIs
- render timeline for chat and manual entries

### Phase 1B: External Source Ingestion

- add browser history and photo library sensors
- add incremental sync and update detection
- add per-source retention strategies
- surface source state in settings

### Phase 1C: User Graph

- implement entity extraction
- implement relation candidate extraction
- normalize into finite edge types
- write L2 user graph with evidence
- show graph-derived evidence in event details

### Phase 1D: Product Hardening

- add filtering, grouping, and inline detail polish
- add manual retry flows
- improve processing visibility
- validate idempotency and performance
- improve L3 and L4 support for timeline workflows

### Phase 2

- social media connectors
- shopping connectors
- stronger trend and behavior summaries
- data deletion and rebuild tools

### Phase 3

- separate L2 agent graph for task state, reasoning lineage, and tool-call ancestry
- establish controlled links between user timeline knowledge and agent-internal state

## Acceptance Criteria

- Timeline sources plug into the current sensor and task-agent runtime rather than a separate architecture.
- Phase 1 supports chat, manual journal, browser history, and photo library.
- Each source can independently choose raw retention or analyze-only mode.
- Timeline rendering is based on normalized L1 facts, not source-specific views.
- L2 only stores user-centric knowledge in Phase 1.
- Edge creation is constrained by event-type-specific whitelists.
- Timeline is exposed as a routed page with inline event expansion.
- Users can inspect why Magi inferred a relationship from concrete event evidence.
