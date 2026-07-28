# Timeline Domain Architecture

## Purpose

This document describes the timeline domain (L13) — a reactive read-model layer that projects sensor outputs into scale-aware temporal views for the frontend.

Read together with [Layered Agent Architecture](./layered-agent-architecture.md), [Unified Plugin Architecture](./plugin-extension-architecture.md), and [Memory System Design](./memory-system-design.md).

## Scope

The timeline domain is a downstream consumer of sensor ingestion. It does not own ingestion, scheduling, or durable memory retention. Those responsibilities belong to `awareness/` (L10), `scheduler/` (L1), and `memory/` (L7) respectively.

Timeline owns:

- the `TimelineEvent` read model and its persistence
- scale-aware viewport assembly (hour, day, week, month)
- transient event clustering and episode-backed cluster fallback
- state band derivation (valence, stress, engagement) from L2/L3 data
- insight extraction (relation candidates → L2 knowledge graph)
- context bundle assembly for UI detail panels
- natural language query interpretation for timeline filtering
- retention metadata tagging

Timeline does not own:

- sensor scheduling or execution (L1/L10)
- durable memory storage or recall (L7)
- chat transcript truth (L14 `chat/`)

## Data Flow

```
Sensor plugin
  → SensorIngestionGateway (L10, publishes SensorEventEmitted)
  → TimelineSubscriber
  → timeline-owned SensorEventEmitted projection
  → TimelineEvent (L13 read model)
  → TimelineService.upsert_event()
      ├─ TimelineInsightPipeline (relation → L2 graph)
      └─ Timeline read model persistence
```

The frontend reads the timeline through viewport and context-bundle APIs:

```
GET /timeline/viewport
  → TimelineViewportBuilder
      ├─ TimelineQueryInterpreter (natural language → constraints)
      ├─ TimelineClusterBuilder (gap + thematic grouping)
      └─ TimelineStateBandBuilder (mood/stress/engagement from L2+L3)
  → viewport response

GET /timeline/context/{anchor_id}
  → TimelineContextBundleBuilder
  → cross-layer detail payload (L1 events, L2 evidence, L3 reflections, L4 procedures, chat excerpts)
```

## Core Data Models

### TimelineEvent

The canonical timeline fact. Created by the host projection pipeline from `SensorOutput` truth:

- `event_id`, `source_type`, `source_item_id`
- `occurred_at`, `captured_at` — when the event happened vs. when it was captured
- `title`, `summary` — display text
- `retention_mode` — `retain_raw`, `analyze_only`, or `compressible`
- `content_blocks` — list of `{kind, value, mime_type}`
- `entities`, `tags`, `privacy_labels` — semantic annotations
- `raw_payload_ref` — reference to the original sensor payload
- `processing_status`, `provenance` — metadata and audit trail

`TimelineEvent` is L13-internal. Sensors produce `SensorOutput` truth (L10), the
host renders display text, and the timeline layer owns the final
`SensorEventEmitted` → `TimelineEvent` projection. Awareness does not construct
timeline read-model records. When timeline reads events that already live in
memory, it uses the neutral `activity_snapshot` metadata block rather than a
timeline-owned structure persisted by memory.

The host projection layer also enforces each sensor output's
`timeline_presentation` policy. Default `full` events keep the historical
behavior: the primary timeline summary mirrors the host-rendered event content.
`compact` and `evidence_only` events use a short title/summary for the primary
timeline while preserving the complete narration/content as L1 evidence for
search, recall, context bundles, and detail drawers. This keeps raw evidence
sources such as OCR screenshots or logs useful without turning the main timeline
into a dump of intermediate text.

### Viewport Response

Assembled by `TimelineViewportBuilder`. Contains:

- `viewport` — metadata: scale, start, end, focus, query, timezone
- `summary` — cluster count, event count, dominant modes
- `overview` — user-facing title, summary, key takeaways, and confidence
- `state_summary` — aggregated mood, stress, engagement, and notable changes
- `state_bands` — valence/stress/engagement bands with confidence
- `state_markers` — detected state shift points
- `source_mix` — source contribution aggregate for UI distribution panels
- `theme_cards` — prioritized review cards with source counts and evidence anchors
- `clusters` — grouped event blocks (transient or episode-backed)
- `reflections` — L3 temporal summaries (month scale)
- `raw_events` — individual events (hour scale)

Viewport requests accept a `locale` parameter. Timeline-owned display strings
such as overview titles, fallback summaries, source labels, state labels, and
rule-generated takeaways must honor that locale. Generated memory artifacts
loaded from L3, such as historical reflection content, remain in the language in
which they were originally generated and require regeneration to change language.
New L3 summary generation prompts should honor the active language context so
freshly generated reflections align with the user's selected language while
preserving source names, ids, URLs, file paths, and quoted evidence text.
Diary-style timeline narratives should behave as private timeline editing rather
than poetic journaling: they should foreground what happened, what made the
period distinctive, and what interpretation is directly supported by evidence.
Decorative sensory detail and reusable literary phrasing should be avoided
unless the underlying evidence supports it.

The frontend should request calendar-aligned complete periods by default rather
than rolling windows. Month, week, day, and hour views open on the latest complete
period and let the user jump to a specific earlier period; adjacent navigation
steps by the active scale and should not advance beyond the latest complete
period.

### Cluster Block

Produced by `TimelineClusterBuilder`:

- `block_id`, `time_start`, `time_end`, `duration_seconds`
- `label`, `summary`, `dominant_mode`
- `source_types`, `event_count`, `keywords`
- `state_snapshot` — optional valence/stress/engagement at cluster time
- `episode_id`, `user_label`, `user_note` — present when backed by a durable L2 episode
- `experience_id`, `experience_title` — present only when the cluster's episode or
  representative events are members of an active L2 experience
- `experience_chapter_id`, `experience_chapter_title` — present only when the same
  cluster also matches that experience's existing durable chapter structure

### State Band

Produced by `TimelineStateBandBuilder`:

- `band_id`, `time_start`, `time_end`
- `valence`, `stress_level`, `engagement`, `confidence`
- `label`

State bands are derived from L2 assertions (mood, stress_level, engagement), L2 snapshots, and L3 sentiment summaries. They are not stored facts — they are computed per viewport request.

### Context Bundle

Assembled by `TimelineContextBundleBuilder` for UI detail panels:

- `anchor` — the event or cluster being inspected
- `l1_events` — L1 event previews for the anchor period
- `l2_state_evidence` — assertions and graph edges
- `l3_reflections` — relevant reflections
- `l4_related_procedures` — procedural memory matches
- `chat_excerpts` — related chat turns

## Review Surface Product Contract

The timeline page is a personal review workspace, not a raw memory-debug panel.
Each viewport should help the user answer four questions:

- What happened during this time window?
- Which activities, state changes, or themes matter most?
- Which items are worth opening for evidence?
- Why did Magi make this interpretation, and can the user trust it?

The page must therefore separate user-facing interpretation from intermediate
memory artifacts. Raw L1 events, L2 assertions, L3 summaries, and L4 procedures
remain available as evidence, but the primary viewport should present a clear
overview first, then prioritized review units, then drill-down evidence.
For high-volume evidence sources, the primary viewport must prefer the compact
timeline summary produced by the host projection and reserve the full captured
text for evidence/detail contexts.

When the user confirms, rejects, or corrects a derived interpretation from the evidence
drawer, timeline should route that action back to the owning memory layer rather
than storing a timeline-local override. L2 assertion confirmation uses the
confirmation-only feedback API; rejection and editing use the governed correction
API so validation state, replacement assertions, and future snapshots stay aligned
with the user's correction.
Episode-backed review periods expose durable user label, note, and pin metadata
from L2 episodes; transient clusters remain read-only until they are promoted to
durable episodes.
Timeline may decorate day clusters with existing L2 experience and
chapter references for navigation and presentation. This decoration is read-only:
it does not promote an episode, create an experience, or infer a chapter. A
cluster linked to an experience without a matching durable chapter must remain an
experience fragment rather than being presented as a chapter.
The day viewport uses a scene-first reading surface: one period headline and
prose lead into chronological scene blocks, while source facts remain behind a
collapsed evidence drawer. It must distinguish a durable experience chapter, an
experience member without a chapter, and an independent fragment. Empty days
keep the same reading surface and expose the manual-entry action instead of
falling back to a dead-end placeholder. Manual notes remain user-authored
records; adding one does not create or promote an experience.
Hiding an episode-backed review period invalidates the L2 episode only; timeline
must not delete member L1 source events unless a separate explicit forget action
requests source deletion.

Detailed execution plans, delivery sequencing, and temporary UI workups for the
review surface belong in `docs/dev/` rather than this root architecture
document.

## Module Responsibilities

### `adapter.py` — TimelineAdapter

Stores pre-rendered `TimelineEvent` objects. Called post-ingestion by the timeline handler after the host projection layer has rendered title/summary from `SensorOutput.activity`, `SensorOutput.narration`, and `SensorOutput.timeline_presentation`. Does not re-ingest into memory.

### `service.py` — TimelineService

Service facade coordinating the domain:

- `upsert_event()` — processes event, runs insight pipeline, persists
- `get_viewport()` — assembles scale-aware viewport response
- `get_context_bundle()` — assembles cross-layer detail payload

### `viewport_builder.py` — TimelineViewportBuilder

Loads events from L1, summaries from L3, assertions/episodes from L2. Applies scale-specific clustering gaps:

| Scale | Clustering gap | Typical window |
|-------|---------------|----------------|
| hour  | 60 seconds    | 1 hour         |
| day   | 5 minutes     | 24 hours       |
| week  | 1 hour        | 7 days         |
| month | 4 hours       | 30 days        |

For day and week scales, durable L2 episodes are preferred over transient clusters when available. Uncovered events fall back to gap-based transient clustering.

`TimelineViewportBuilder` owns viewport orchestration only. Presentation-specific
derivations live in smaller timeline-owned helpers: `viewport_clusters.py`
enriches cluster display fields, `viewport_overview.py` builds the overview
card, `viewport_state_summary.py` builds the compact state summary, and
`viewport_i18n.py` centralizes viewport localization helpers.

### `cluster_builder.py` — TimelineClusterBuilder

Groups events into activity blocks using gap-based splitting and thematic matching (shared entities/tags). Supports two modes:

- transient clustering for events not covered by durable episodes
- episode-backed clusters that reuse L2 episode boundaries

### `state_band_builder.py` — TimelineStateBandBuilder

Synthesizes emotional state from L2 and L3 data. Tone-to-valence mapping:

- positive: 0.75, warm: 0.65, steady: 0.35, neutral: 0.0
- cool: −0.25, low: −0.45, tense: −0.5, anxious: −0.6

Detects state transitions where stress changes ≥ 0.25 and emits shift markers.

### `query_interpreter.py` — TimelineQueryInterpreter

Parses natural language queries into structured constraints:

- time hints: "last week", "today", "yesterday"
- mood hints: warm, tense, low, anxious
- activity hints: game, coding, chat

Returns `TimelineQueryInterpretation` with residual terms and search filters.

### `insight_pipeline.py` — TimelineInsightPipeline

Extracts user graph relations from timeline events. Normalizes to a whitelisted relation set (LIKES, DISLIKES, CARES_ABOUT, INTERACTED_WITH, VISITED, PURCHASED, VIEWED, CREATED, CAPTURED, OWNS, MENTIONED, RELATED_TO). Writes edges to L2 knowledge graph with evidence provenance.

### `context_bundle_builder.py` — TimelineContextBundleBuilder

Assembles rich detail payloads anchored by event or cluster. Pulls data across L1, L2, L3, L4, and chat. Episode-backed anchors fetch all member events and relationships.

### `retention.py`

Tags timeline events with retention metadata for downstream compaction or archival policies.

### `lifecycle.py`

Bootstrap lifecycle module for timeline domain initialization.

## API Surface

```
GET  /timeline/viewport
     ?scale=month|week|day|hour
     &start=<unix_ts>&end=<unix_ts>
     &query=<natural_language>
     &timezone=<tz>&focus=<unix_ts>
     → TimelineViewportResponse

GET  /timeline/context/{anchor_id}
     → TimelineContextBundle (or 404)

GET  /timeline/digests
     ?limit=1-100&category=hour|day|week|month
     → TimelineDigestSummary[]

POST /timeline/digests/generate
     {category: "hour|day|week|month"}
     → triggers L3 temporal summary generation
```

## Frontend Components

The timeline page renders a scale-specific review surface. The target
component roles are:

| Scale | Components |
|-------|-----------|
| month | TimelineWindowOverview + TimelineStateSummary + MonthThemeLane + SourceMixPanel |
| week  | TimelineWindowOverview + TimelineStateSummary + WeekRhythmLane |
| day   | TimelineWindowOverview + TimelineStateSummary + DaySegmentLane |
| hour  | HourEvidenceLane + SourceFilterBar |

Key components:

- `TimelineViewport` — master scale dispatcher
- `TimelineToolbar` — scale/search/navigation controls
- `TimelineWindowOverview` — user-facing summary and key takeaways for the selected window
- `TimelineStateSummary` — aggregated mood, stress, engagement, and notable state changes
- `MonthThemeLane` — prioritized monthly themes derived from reflections, clusters, and sources
- `WeekRhythmLane` — day-grouped weekly rhythm and key periods
- `DaySegmentLane` — episode-backed or time-of-day activity blocks
- `HourEvidenceLane` — raw evidence list with timestamps and source labels
- `SourceMixPanel` — compact source contribution summary
- `TimelineContextDrawer` — right-side evidence and reasoning panel backed by context bundles

Existing component names may be reused during implementation, but their output
must follow the product hierarchy above. The main viewport must not render one
row per state band as primary content. Digest generation remains a separate
capability and should not be treated as a prerequisite for the core review
surface.

## Dependency Rules

Timeline (L13) may depend on:

- memory (L7) for L1 events, L2 assertions/episodes/edges, L3 summaries, L4 procedures
- awareness (L10) for `SensorOutput` contracts (input only)
- config (L2) for runtime settings
- core (L1) for infrastructure

Timeline must not depend on:

- agent runtime (L12)
- external services (L14)
- transport (L15)

Sensors (L10) must not depend on timeline. Sensor ingestion publishes neutral
events; timeline subscribers own the sensor → timeline read-model projection.
