# Timeline Projection Design

## Goal

Redefine `timeline` as a time-oriented projection of the memory system instead of a separate event-ingestion domain.

The new design removes the current semantic overlap where chat content and sensor data can appear both as memory facts and as timeline-specific records. `timeline` should become a derived read model built from existing memory layers, not an additional source of truth.

## Problem

The current implementation mixes two different meanings of timeline:

- a product page for viewing memory over time
- a dedicated ingestion path with its own event shape

That creates several issues:

- chat content is already stored in `L1`, but is conceptually duplicated when timeline tries to represent it as a separate stream
- timeline sensors write timeline-first records instead of writing canonical memory events
- memory and timeline semantics drift apart because timeline behaves like a parallel storage model
- future recall, summarization, and timeline rendering are harder to unify because they do not share one fact base

## Design Principle

`Memory` is the fact system. `Timeline` is the time projection of that system.

This means:

- `L1` remains the durable source of truth for raw long-term events
- `L3` remains the durable source of reflection-oriented summaries
- `timeline` owns no raw fact storage
- `timeline` may own cache tables, but only for derived projection items
- every timeline item must be reconstructible from `L1` and `L3`

## Scope

This design is intentionally clean-slate.

Included:

- new timeline semantic definition
- lazy-generated timeline projection architecture
- projection table boundaries
- initial input/output model
- future extension point for `L2.tom_trait_assertions`

Excluded:

- migration from the current timeline implementation
- backward compatibility
- UI redesign details
- background incremental projection refresh

## Target Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                        Product UI                           │
│                    Timeline Page / Filters                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    TimelineQueryService                     │
│  resolve window -> cache lookup -> build if cache missing   │
└─────────────────────────────────────────────────────────────┘
                              │
                cache hit      │      cache miss
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  TimelineProjectionStore                    │
│     stores derived timeline items keyed by query window     │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────┐
│                 TimelineProjectionBuilder                   │
│        loads L1 + L3 and assembles timeline items           │
└─────────────────────────────────────────────────────────────┘
                    ▲                              ▲
                    │                              │
┌──────────────────────────────┐    ┌─────────────────────────┐
│          L1 Events           │    │      L3 Summaries       │
│   canonical long-term facts  │    │ reflection / summaries  │
└──────────────────────────────┘    └─────────────────────────┘
```

## Semantic Rules

### Rule 1: Timeline is not an ingestion target

No producer should write raw facts "for timeline".

Chat, sensors, and external activities should write canonical memory events into `L1` using the normal memory contract. If timeline needs to display them, it reads them later through projection building.

### Rule 2: Timeline cache is a read model, not a fact store

Timeline-owned tables may exist, but they only store:

- derived display data
- source references
- generation metadata

They must never become upstream inputs for `L2`, `L3`, `L4`, or memory retrieval.

### Rule 3: Every timeline item must be traceable

Each projection item must preserve enough references to explain where it came from:

- one `primary_event_id` when applicable
- one or more `source_event_ids`
- one or more `source_summary_ids`

The UI may display a compact card, but the backend must preserve the evidence path.

### Rule 4: Chat is not copied into timeline

Chat is already part of memory through `L1` events.

Timeline may show chat-derived activity by reading those events in the requested time window, but it does not receive a second timeline-specific write.

## Initial Inputs

Initial projection inputs are limited to:

- `L1`
- `L3`

### Why `L1`

`L1` provides the concrete event-level time axis:

- user-authored events
- interaction events
- external activity events
- runtime events that remain intentionally retained

`L1` is the only correct event-time source for the first version of timeline.

### Why `L3`

`L3` provides compressed overview material:

- daily or weekly summaries
- higher-level reflection entries
- concise recall surfaces for long windows

This lets the timeline page present both detail and overview without inventing a second summarization model.

### Why not `L2` in v1

`L2` already contains time-related fields, but they describe cognition lifecycle rather than direct lived event time.

For example:

- `knowledge_graph.first_observed_at` and `last_observed_at` represent relationship observation history
- `tom_trait_assertions.first_inferred_at` and `last_validated_at` represent inference and validation timestamps
- `tom_snapshots.last_updated_at` represents snapshot materialization time

Those timestamps are valuable, but they should not define the main timeline axis in the first version.

## Future Input Extension

Later, `L2.tom_trait_assertions` may be added as a timeline input source for state-change storytelling.

Examples:

- stress increase over several days
- preference reinforcement
- contradiction or reversal of a prior interpretation
- gradual relation shift

However, `tom_trait_assertions` should not be rendered directly as raw rows. It should first go through a timeline-safe projection layer with:

- confidence thresholds
- temporal grouping
- wording normalization
- sensitivity filtering

`knowledge_graph` and `tom_snapshots` should not directly become timeline items.

## Projection Model

The first version should support two item types:

- `event`
- `summary`

`cluster` or other higher-order aggregate types can be added later after the page interaction model is clearer.

### Event item

An `event` item is directly anchored to one primary `L1` event and may optionally include nearby supporting events.

Use cases:

- show a specific browser activity
- show a specific user-authored note
- show a specific interaction moment

### Summary item

A `summary` item is anchored to one `L3` summary and represents a higher-level recap over a time range.

Use cases:

- day overview
- week overview
- dense periods where event-level display is too noisy

## Projection Table Contract

Suggested table: `timeline_projection_items`

```sql
CREATE TABLE timeline_projection_items (
    item_id TEXT PRIMARY KEY,
    window_key TEXT NOT NULL,
    filter_hash TEXT NOT NULL,
    item_type TEXT NOT NULL,              -- event, summary
    time_start REAL NOT NULL,
    time_end REAL NOT NULL,
    sort_time REAL NOT NULL,
    primary_event_id TEXT,
    primary_summary_id TEXT,
    source_event_ids TEXT NOT NULL,       -- JSON
    source_summary_ids TEXT NOT NULL,     -- JSON
    display_payload TEXT NOT NULL,        -- JSON
    projection_version INTEGER NOT NULL,
    generated_at REAL NOT NULL
);

CREATE INDEX idx_timeline_projection_window
ON timeline_projection_items(window_key, filter_hash, sort_time DESC);
```

### Field semantics

- `window_key`
  Identifies the requested logical window, such as day, week, or custom range bucket.

- `filter_hash`
  Separates cached projections built under different source or domain filters.

- `item_type`
  Distinguishes event-level and summary-level cards.

- `time_start` / `time_end`
  Preserve the actual time span represented by the item.

- `sort_time`
  Gives one normalized value for ordering mixed item types.

- `display_payload`
  Holds display-ready title, subtitle, snippets, tags, source badges, and lightweight counts.

- `projection_version`
  Allows safe invalidation when projection logic changes.

## Cache Strategy

The first version should use lazy generation with cache storage.

### Read flow

1. The page requests a time window.
2. `TimelineQueryService` computes `window_key`, `filter_hash`, and `projection_version`.
3. If cached items exist, return them.
4. Otherwise build items from `L1 + L3`, persist them, and return them.

### Invalidation strategy

Initial invalidation can stay simple:

- version bump invalidates old projection logic
- explicit rebuild endpoint can drop and regenerate a window
- optional TTL may be added later if needed

No background incremental pipeline is required in the initial phase.

## Query and Build Responsibilities

### TimelineQueryService

Responsibilities:

- accept time window and page filters
- normalize cache keys
- load cached items when available
- trigger projection building on cache miss

Non-responsibilities:

- raw memory writes
- summary generation
- memory-layer mutation

### TimelineProjectionBuilder

Responsibilities:

- query `L1` events for the requested window
- query `L3` summaries overlapping the requested window
- choose which items are rendered as `event`
- choose which items are rendered as `summary`
- assemble `display_payload`
- preserve source references

Non-responsibilities:

- UI grouping decisions that belong to the frontend
- writing back to memory layers

### TimelineProjectionStore

Responsibilities:

- persist and load cached projection items
- delete items for a window when invalidating
- stay fully rebuildable from source memory layers

## Page-Level Presentation Flexibility

The backend projection model should not hardcode the final page layout.

The UI may later choose to render the same projection items as:

- a flat reverse-chronological stream
- day-grouped sections
- summary-first with collapsible event details
- mixed event and summary cards

That is why the projection model must preserve event-level traceability even if the page later chooses a more aggregated presentation.

## Testing and Validation

The initial design should be validated with these scenarios:

1. Opening a timeline window with only `L1` events produces event items without any timeline-specific raw writes.
2. Opening a timeline window with matching `L3` summaries includes summary items in the correct time order.
3. Reopening the same window returns cached projection items instead of rebuilding.
4. Bumping `projection_version` forces a rebuild.
5. Chat events appear in timeline through `L1` retrieval only, with no duplicate timeline-side storage.
6. Sensor-originated events appear in timeline only if they were normalized into canonical memory events.

## Open Follow-Ups

These items are intentionally deferred:

- adding `cluster` projection items
- introducing incremental background projection refresh
- using `L2.tom_trait_assertions` as a timeline state-change source
- ranking rules for dense windows
- frontend grouping and card language refinement

## Recommended Next Step

After this spec, implementation should focus on a narrow first slice:

1. remove timeline-first raw storage assumptions from the new design path
2. add a projection store
3. add lazy query/build flow for one window type
4. support only `event` and `summary` item types backed by `L1 + L3`
