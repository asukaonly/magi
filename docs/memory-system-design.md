# Memory System Design

## Purpose

This document is the long-term source-of-truth for Magi's memory system. It answers two categories of questions:

- **For product stakeholders**: What does Magi remember, what does it not, and where does each type of data live?
- **For developers**: What contracts govern layering, ingestion, retrieval, identity, idempotency, and downstream cognition?

Related root documents:

- [Project Overview](./project-overview.md)
- [Layered Agent Architecture](./layered-agent-architecture.md)
- [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
- [Unified Plugin Architecture](./plugin-extension-architecture.md)

If this document conflicts with the above, they should be revised together. This document refines the memory subsystem; it does not redefine project-level boundaries.

---

## What the Memory System Solves

Magi's memory system organizes local conversations, external activities, and selected runtime results into retrievable, compressible, long-term memory — while keeping chat truth, runtime traces, and plugin intermediate state cleanly separated.

It is responsible for:

- Maintaining short-term working context for the current session
- Projecting selected facts into durable event memory
- Extracting structured cognition from retained events
- Compressing long histories into reviewable summaries and insights
- Distilling reusable execution experience

It is **not** responsible for:

- Serving as the source of truth for complete chat transcripts
- Serving as the source of truth for runtime spans, tool traces, or execution telemetry
- Permanently storing every raw producer payload
- Rendering persona-voiced chat UI cards; memory may provide traceable snippets,
  but chat/persona layers decide how those snippets are presented in a turn

Magi's memory model is layered by **information lifecycle**, not by functional plugin:

- `L0` — Working memory
- `L1` — Normalized event facts
- `L2` — Structured cognition (with three product subdomains: semantic, state, episodic)
- `L3` — Reflection and summaries
- `L4` — Procedural memory

---

## Mental Model

The memory system forms a stable data evolution chain:

```text
Source signal
  -> Normalized event contract
  -> Routing and retention policy
  -> L0 and/or L1
  -> Optional L2 cognition
  -> Optional L3 reflection
  -> Optional L4 experience distillation
```

Examples:

- A user chat message is first a fact in `chat.db`, then part of it may be projected as an `L1` memory fact.
- A Chrome browsing burst is aggregated into an `L1` event, which may later feed `L2` relation extraction and `L3` temporal summaries.
- A worker heartbeat is runtime telemetry and should not enter long-term user memory.
- A task completion result may be worth retaining in memory, but the detailed execution trace stays in the runtime trace store.

The memory system sits between "raw data sources" and "higher-level reasoning". It is not the raw data source itself.

Sensor ingestion follows the same ownership rule. `awareness/` publishes the
neutral `SensorEventEmitted` envelope; `memory/` owns the conversion from that
envelope into a `MemoryEvent`. Timeline read-model projection is owned by
`timeline/`. This keeps sensor capture separate from memory retention and
timeline presentation.

---

## Runtime Boundaries and Data Stores

Magi explicitly separates chat truth, runtime observations, and persistent memory into different stores.

### Chat Truth

- `~/.magi/data/chat/chat.db`

Holds:

- `chat_sessions`
- `chat_turns`
- `chat_messages`

Read here when you need complete chat transcripts, turn presentation state, or chat-domain read models.

### Runtime Observations

- `~/.magi/runtime/runtime_trace.db`

Holds:

- Turn summaries
- Tool calls
- LLM metrics
- Spans
- Live notifications
- Append-only plugin ingress events

Read here when you need execution replay, debugging, traces, or raw plugin ingress events.

Important rule: runtime observations can feed lightweight prompt-time continuity summaries, but those summaries are lossy and session-scoped. They do not promote execution telemetry into durable memory and do not replace trace inspection tools.

### Persistent Memory

- `~/.magi/data/memory/l1_events.db`
- `~/.magi/data/memory/memory.db`

Holds:

- `L1` fact events stored in `l1_events.db`
- `L0`, `L2`, `L3`, `L4` stored in `memory.db`

Read here when you need historical recall, structured cognition, summaries, long-term insights, or procedural experience.

### Rebuildable Cache

- `~/.magi/cache/plugins/<plugin_id>/`
- `~/.magi/workspaces/<workspace_id>/cache/`
- `<workspace>/.magi/cache/`

Holds plugin-owned rebuildable intermediate state:

- In-progress sensor aggregation state
- Flush checkpoints
- Plugin-local computation caches
- Workspace-scoped code indexes and retrieval caches

**Cache is not memory truth.**

Workspace overlays may also hold project instructions, rules, skills, and gitignored runtime checkpoints under `<workspace>/.magi/`. These files are project context or recoverable execution state. They must not be treated as durable memory unless a memory projection pipeline explicitly promotes selected facts into `L1`.

---

## Layer Overview

### L0 — Working Memory

`L0` is the short-term working context for the current session or task.

It holds:

- Current session state
- Current goal stack
- Currently active entities
- Temporary strategy and execution context

Key properties:

- Centered on the current execution, not long-term recall
- Primarily in-memory, with checkpoints for recovery
- Changes frequently
- Can be partially restored from durable state after restart

`L0` should only hold what the current turn genuinely needs, not everything the system has ever seen.

Examples:

- Active goals for the current session
- Entities the current conversation revolves around
- Temporary tactical decisions for a single turn

### L1 — Normalized Event Facts

`L1` is the durable fact layer and the factual foundation of the entire memory system.

It stores normalized events that are stable enough to participate in downstream processes:

- Recall
- Search
- Cognition
- Reflection
- Audit and debugging of memory projection pipelines

If a fact will later affect the system's understanding, review, or reasoning, it typically enters `L1` first.

Key properties:

- Durable fact events
- Unified source-normalized contract
- Explicit domain / retention / cognition policies
- Supports vector retrieval and keyword retrieval
- Preserves source-side identity and business idempotency
- Maintains rebuildable source-facet indexes for exact structured recall over
  source-owned fields such as photo locations/counts, browser domains/visit
  counts, and music tracks/artists/play counts
- Vector index uses `event` as the parent object and `chunk` as the retrieval unit: long texts are split into overlapping chunks for vector indexing, then collapsed back to the parent event during retrieval
- `L1` / `L3` / `L4` hybrid retrieval passes through a unified reranker stage after RRF; heuristic reranking is always active
- An optional local cross-encoder reranker can add semantic relevance scoring on top of the heuristic stage
- The cross-encoder reranker is driven by `agent.memory.reranker.cross_encoder` and loads a managed ONNX model by `managed_model_id`; if it is disabled or the model files are unavailable, retrieval falls back to heuristic reranking without interruption

Examples:

- User-authored content
- Chat projection memory facts
- Chrome history bursts
- Hourly app usage summaries

Counter-examples:

- Complete chat transcript truth
- Heartbeat noise
- Step-by-step execution traces
- Exact tool arguments, latencies, and raw tool outputs from a specific turn

#### Evidence Interpretation and Retrieval Authority

`L1` raw events and retrieval authority are separate concerns. The raw event row records what happened; evidence interpretation records how that event is allowed to participate in fact recall, episode recall, audit views, and downstream cognition.

Evidence interpretation is shared memory governance, not an `L2`-only helper:

- Classification answers what the evidence is: user assertion, user question, user request, assistant freeform answer, assistant quote, tool result, external observation, runtime signal, or other explicit class.
- Policy answers what the evidence can do: enter fact-like retrieval, remain episode/audit-only, write L2 graph/assertions, affect snapshots, count as new evidence, or require a source backlink.
- The baseline durable annotation is event-level. Span-level retrieval atoms are optional derived projections for mixed or long events once they are justified by measured retrieval pollution, not the default raw-memory shape.
- If span-level atoms are introduced, they must hydrate back to the parent `fact_events` row and be protected by immutable source text or content-hash validation.

Fact-like retrieval must constrain the searchable evidence pool before ranking and topK selection. It must not depend on broad L1 recall followed by answer-projection filtering as the primary defense. Assistant memory answers, user recall questions, runtime artifacts, and ungrounded assistant text can remain retrievable in conversation, episode, audit, or debug contexts, but they are not authoritative evidence for new user facts.

Raw `fact_events` content is not rewritten to fix retrieval behavior. Classifier, policy, embedding profile, and index changes mark derived evidence/index records stale and trigger rebuilds; they do not mutate the original L1 fact.

Source-facet indexes are `L1` retrieval infrastructure, not `L2` cognition.
They preserve source-owned exact fields needed for coverage-sensitive queries
where top-K text/vector recall is insufficient, for example "how many photos at
this place", "how many visits to this domain", or "how many plays by this
artist". Plugins may provide these fields through `domain_payload.source_facets`;
`L1` may also rebuild facets from older persisted metadata when the source facts
are still present. A structured recall result may claim total coverage only
inside the explicit source/facet/time/user scope used to query that index.

Prompt continuity note:

- The chat runtime may carry a compact `Recent Tool State` summary across nearby turns so the LLM can reuse recent tool outcomes or handles without replaying full tool transcripts.
- This summary is not itself an `L1` fact, `L2` cognition artifact, or durable memory record.
- If the user asks for exact execution details, the system should read `runtime_trace.db` through trace read APIs or the builtin `trace_query` tool instead of searching memory layers.

### L2 — Structured Cognition

`L2` stores structured understanding derived from `L1` events. It is organized into three product subdomains:

- **Semantic memory** — Durable entities, relations, preferences, long-term structure
- **State memory** — Latest truth, current status, versioned facts with supersession
- **Episodic memory** — Bounded historical experiences derived from L1 events

Together, these subdomains let Magi answer "who am I / what am I doing / what happened" with evidence, and feed the timeline, profile, and proactive features from one consistent memory substrate.

L2 holds:

- Entity mentions and canonical entities
- Knowledge graph edges (with `fact_kind`, temporal validity, privacy scope)
- Entity facets (sidecar structured attributes)
- ToM trait assertions (versioned, with lifecycle states and supersession)
- ToM snapshots (periodically refreshed entity portraits)
- Episodes (bounded activity and theme segments formed from L1 events)
- Experiences (product-grade, evidence-backed narrative memories promoted from episodes and events)
- Durable projection job queue

Sensor-derived relation candidates reach the L2 knowledge graph through the awareness-owned knowledge graph write queue. That queue is the backpressure boundary for bursty sensor catch-up runs: it batches edge writes before calling the unified memory facade, while the memory layer remains the owner of graph schema, conflict resolution, evidence merging, and embedding status updates.

Implementation boundary: `L2CognitionStore` remains the public storage facade
and transaction coordinator in `memory/l2/store.py`, while its mixins are grouped
by L2 domain rather than by generic helper status: `storage/`, `graph/`,
`assertions/`, `entities/`, `episodes/`, `projection/`, `extraction/`,
`retrieval/`, and `governance/`. Entity-domain code lives under
`memory/l2/entities/`: `catalog/` owns canonical entities and aliases,
`maintenance/` owns offline cleanup, `models.py` owns entity contracts, and
`facets.py` owns sidecar entity attributes.

For user-authored chat, durable self-descriptive profile facts such as identity,
birthday, preferred language, and addressing preferences should land in L2
semantic/state assertions, not in bootstrap-only state. Explicit identity facts
use `identity_profile` assertions such as `identity.real_name`,
`identity.birth_date`, `identity.birth_year`, and `identity.age.stated`.
Communication preferences use `communication_profile` assertions such as
`communication.address.preferred`, `communication.address.disallowed`, and
`communication.response_style.preferred`.
Phase 1 extraction may use profile-signal predicates such as `REAL_NAME`,
`BIRTH_DATE`, `BIRTH_YEAR`, `STATED_AGE`, `PREFERRED_FORM_OF_ADDRESS`,
`DISALLOWED_FORM_OF_ADDRESS`, and
`PREFERRED_COMMUNICATION_STYLE` to keep those facts explicit for Phase 2, but
these predicates are not graph relations and must never be persisted as knowledge
graph edges.
Profile-signal claims must be grounded in current user-authored text before they
can produce profile assertions; assistant persona text, recalled history, and
one-off task phrasing are not sufficient evidence for durable identity or
communication-profile fields.
Post-turn observers may submit explicit profile candidates from chat, but they
must not write portrait projections directly. The host validates that the
candidate is grounded in the user's own text, persists it as an L2 assertion
candidate, and lets normal assertion state, conflict handling, review, and
portrait projection decide how it appears to the user.

Post-turn observers may also submit explicit task-handling preferences when the
user states how future work should be handled. These preferences belong to L4
procedural memory, not persona behavior evolution or L2 profile facts, because
they describe reusable execution guidance rather than identity traits.

L2 keeps a semi-open graph predicate model so source-specific relationships can
be captured before the core ontology knows every useful verb. That openness is
bounded by a quality gate: custom predicates must describe stable, reusable
facts, while dialogue/query activity such as asking about, mentioning, looking
at, or wanting help with an object belongs in short-lived interaction context,
not the durable knowledge graph. Entity extraction follows the same boundary:
pronouns and vague placeholders such as “那个”, “他”, generic “app”, or generic
“PDF” may help resolve references, but should not become canonical L2 entities
unless they resolve to a concrete named entity or asset.

Knowledge graph endpoints must resolve through the entity catalog before they are
persisted. The L2 pipeline may ask an LLM to compare or integrate facts, but the
LLM is not an authority for inventing `entity_id` values. Phase 2 graph edges
must reference catalog IDs produced by Phase 1 entity resolution, existing graph
context, or source-owned structured hints that have first been registered in the
catalog. Non-Latin entity names keep their original script in catalog names and
aliases; ASCII slugs are storage identifiers only and must not replace the
source-language name in user-facing evidence.

The extraction runtime keeps Phase 1 admission, batch preparation, and entity
resolution separate from Phase 2 integration, candidate validation, conflict
handling, and persistence. Shared handoff data lives in a small extraction
contract module so either phase can evolve without importing implementation
details from the other.

`user_profile_projection` in `memory.db` is the product-facing read model for the
local user profile. It is rebuilt from current L2 profile assertions, records
field sources/conflicts, and derives deterministic fields such as `birth_year`
and `age_years` from `identity.birth_date`. Settings writes are user-authored
evidence: they create an L1 audit event, write confirmed L2 profile assertions,
and then refresh the profile projection and self-portrait projection together.
Product code and prompt assembly should read the projection first and fall back
to raw L2 assertions only when the projection does not yet exist.

`user_portrait_projection` is the product-facing self-portrait read model for
the local user. It is not an authority over L2 facts. It packages L2 assertions,
the current ToM snapshot, and review state into a stable `world/review/recent`
page model plus a short `prompt_summary` for main-chat context injection. Prompt
assembly must use that human-readable summary when available and must not dump
raw preference dictionaries, internal assertion keys, source tiers, or affinity
metadata into the main model prompt. Clearing L2 cognition artifacts must also
clear profile and portrait projections so local re-imports do not keep stale
user-understanding caches.

Portrait projection is a qualification layer above raw assertions. Explicit
user-authored, settings-backed, and user-confirmed profile assertions may enter
the portrait once they are active, but passive source assertions must also pass
source strength, evidence-count, validation-state, and trait-family alignment
checks. For example, an external `interest.*` assertion can become a preference
only after enough evidence accumulates, while a `tool.*` assertion belongs in
working style and must not appear as a preference. Assertions that fail this gate can
remain L2 facts or review material, but they must not enter `world` or
`prompt_summary`.
Materialized portrait rows are cacheable, not permanently authoritative: reads
and prompt assembly must rebuild them when newer profile, assertion, snapshot,
or safe graph inputs exist. User feedback or correction on a user assertion
should refresh the portrait projection after the assertion update succeeds.

Bootstrap is only responsible for injecting the first assistant opening for a
persona. After that opening is persisted, all profile extraction returns to the
normal chat -> L1 -> L2 pipeline; bootstrap must not own a separate user-profile
extraction path. To make a just-connected data source visible in that first
opening without waiting for full L2/L3 cognition, bootstrap may sample a small,
source-balanced set of recently written external-activity L1 events as temporary
first-chat context. Those samples are representative, bounded, and prompt-only;
they must not be treated as a durable profile or a replacement for normal
memory processing.

`L2` embedding uses a shared embedding pipeline across all layers; each layer defines its own text builder, chunk strategy, parent-table status writeback, and retrieval collapse logic. The entity catalog uses single-entity-single-vector without chunking. All L2 parent tables record unified embedding observation fields (`embedding_status`, `embedding_profile_id`, `last_embedded_at`); `knowledge_graph` also records these fields for relation-edge vectors. Runtime settings expose a persistent vector rebuild job for `L1`, `L2` entities, `L2` edges, `L3`, and `L4`.

Vector indexes must separate incompatible embeddings by hard identity. Remote embedding identity is `model + dimension + text_builder_version`; provider ID, base URL, API format, and provider type are provenance and may produce a soft warning but not a forced table split. Local embedding identity is `model_file_hash + dimension + text_builder_version`, where `model_file_hash` is derived from the ONNX model and tokenizer/config sidecar files. The sqlite-vec registry stores the hard index identity, so changing models or text-builder versions does not silently query stale vectors. When operators intentionally change embedding identity, Settings warns before saving and the rebuild job can regenerate all layer vectors in the background.

`L2` is the "evidence-backed interpretation layer", not the raw truth layer.

Key properties:

- Derived from `L1`, not independently produced
- All artifacts carry evidence references
- Confidence-scored
- Supports conflict handling and subsequent correction
- Defaults to durable projection jobs from `L1`, not in-memory queues

#### L2 Product Subdomains

**State Memory** stores versioned latest-truth about entities. Assertions follow a lifecycle:

- Status values: `tentative` → `corroborated` → `stable`; can transition to `superseded`, `expired`, `archived`, or `user_rejected`
- Supersession: When a fact changes (e.g. "I moved from Hangzhou to Shanghai"), the old assertion is marked `superseded` with `superseded_by` / `superseded_at` linking to the new one. This is a normal lifecycle transition, not a contradiction.
- Decay policies: `session_decay`, `fast_decay`, `time_window`, `evidence_only`, `none`
- Memory subdomain tag: `memory_subdomain` distinguishes `'state'` (mood, stress, engagement) from `'semantic'` (preferences, long-term facts) within assertions
- Reconciliation: `reconcile_entity()` re-derives confidence and stability from evidence counts and time spans
- Snapshot evolution: `refresh_entity_snapshot()` rebuilds from reconciled assertions + graph edges, maintaining `core_traits_history`, `preferences_history`, `relationship_history`, `mood_trajectory`, and `emerging_signals`

Assertion family semantics are centralized in `backend/src/magi/memory/l2/assertion_family_policy.py`. The canonical families are `stress`, `mood`, `engagement`, `trigger`, `relationship_shift`, `group_atmosphere`, `public_sentiment`, `identity_profile`, `communication_profile`, `preference_profile`, `routine_profile`, and `state_profile`. `preference_profile` owns stable interests, affinities, tastes, and preferences; `routine_profile` owns repeated behavior rhythms and habits. Each family policy defines Phase 2 guidance, default temporal scope, default decay policy and baseline TTL, snapshot bucket, and value-localization expectation. Runtime confidence and TTL tuning lives under `agent.memory.l2.assertion`, and both Phase 2 validation and assertion reconciliation must read those config-backed values rather than maintaining separate TTL or state-threshold constants. These policies drive validation, prompt text, decay defaults, and snapshot placement.

Family choice shapes downstream handling but does not by itself decide trust. Conflict decisions are primarily source-tier and active-key based: user-authored assertions remain authoritative over behavioral or plugin-derived inference unless the user explicitly corrects or rejects them. Family policy determines whether a value behaves like short-lived state, durable semantic profile, preference snapshot content, or core-trait context after it has passed source-tier and evidence gates.

Assertion API rows expose family display metadata, including `trait_value_i18n`, so the frontend can localize controlled state values while preserving literal user-authored profile and preference values.

**Episodic Memory** stores bounded historical activity, episode, and experience structure:

- Three tables: `episodes`, `episode_events`, `episodes_fts` (FTS5)
- Episode types: `activity`, `visit`, `session`, `conversation` (each with different time-gap thresholds)
- Streaming formation: `assign_events_to_episode()` hooks into L2 pipeline extract workers; uses time-gap detection and entity/topic overlap for theme continuity
- Status lifecycle: `candidate` → `active` (promotion), then terminal
  `merged` (explicit curation merge into a survivor episode) or `invalidated`
- Promotion reports newly-active episode IDs to callers; L2 formation stays
  L2-only, while runtime callers that hold L1/L2/L3 handles (periodic L2
  maintenance and manual reconsolidation) generate missing L3 episodic summaries
  for those episodes or for active backfill scope
- Product episode lists default to `status='active'`; episode detail reads join
  event memberships with live L2 assertions whose `evidence_events` intersect
  those events, while corrections reuse the assertion feedback path
- The episode review surface is reading-first: it presents Magi's natural
  language recap from the linked L3 episodic summary, then lets the user edit
  the display title, edit or regenerate the recap, and curate the member event
  boundary with explicit buttons. V1 keeps confidence-style reactions out of the
  surface until a dedicated feedback/confidence system exists.
- Add/remove event curation operates on system-suggested nearby candidate
  events, not a global event search. Merge curation chooses a suggested active
  episode and folds it into the current survivor. Split curation uses a
  chronological breakpoint between member events, creates two active child
  episodes, invalidates the source episode, and regenerates child recaps.
- Explicit merges move event memberships to the survivor, mark the absorbed
  episode `merged`, and recompute the survivor `source_event_count` from
  `episode_events`
- User agency fields: `user_label`, `user_note`, `user_pinned`
- Full-text search via FTS5 over `summary`, `label`, `user_label`
- Episodes can overlap and nest via `parent_episode_id`
- Each episode carries `primary_entity_ids`, `primary_place_ids`, `primary_topic_keys`, `continuity_signals`, `dominant_mode`

Episodes are the L2 episodic substrate, not necessarily the final
user-facing memory object. They organize L1 evidence into bounded activity or
theme segments such as browsing bursts, search sessions, debugging windows, or
conversation spans. They may be useful evidence even when they are too shallow,
generic, or source-driven to feel like a meaningful life/work experience.

**Experiences** are the product-grade episodic object surfaced in the review
page and timeline. An experience is promoted only when one or more substrate
episodes/events form a narratable memory with a clear theme, evidence boundary,
user involvement, and some change, outcome, decision, discovery, or unresolved
thread worth revisiting. L2 owns the experience identity, membership, lifecycle,
curation state, user-selected cover asset reference, and evidence backlinks. L3
owns the natural-language review and Magi interpretation attached to that
experience. Timeline and review surfaces consume experiences; they do not define
or persist them.

Experience membership must remain evidence anchored. The durable model should
allow membership rows to reference source episodes first and direct L1 events
when finer curation is needed. The source episode remains a supporting segment;
it does not become a new fact source. Any user/profile claim inferred from an
experience must enter the normal assertion pipeline with source policy,
confidence, and evidence links instead of being treated as true because an
experience summary said it.

Experience promotion is a second-stage process over active episodes:

- Build candidates from a single strong episode, adjacent same-theme episodes,
  or repeated cross-day themes.
- Score candidates for narrative quality: theme coherence, user involvement,
  boundary clarity, outcome or turning point, long-term relevance, and duplicate
  overlap with existing experiences.
- The V1 promotion gate applies deterministic quality checks before persistence:
  source/tool-only clusters, technical artifacts, weak boundaries, and candidates
  without user-action signals are rejected at seed level with a recorded reason,
  while user-accepted manual seeds remain promotable.
- Promote only candidates that can be expressed as a concrete natural-language
  memory, not merely as a source/app cluster.
- Generate the L3 experience review after promotion so the prose is attached to
  a stable L2 object with traceable evidence.
- Experience reviews use an experience-specific review prompt rather than the
  shorter episode recap prompt. The review stores a longer narrative plus
  generated intent/outcome metadata; non-fallback reviews refresh generated L2
  title/body fields so review pages and recall use the same prose, while
  user-owned labels and notes stay independent.
- Trigger promotion from both the manual `l2/episodes/reconsolidate` catch-up
  endpoint and the periodic L2 consolidation job, so the review page can refresh
  from the same evidence pipeline instead of relying on frontend-only filters.

**Semantic Memory** stores durable entities, relations, and preferences:

- Knowledge graph edges carry `fact_kind` (`explicit_fact`, `public_topology`, `interaction_evidence`, `stable_preference`) for admission policy enforcement
- Temporal validity: `valid_from` / `valid_to` on edges
- Privacy scope: `privacy_scope` on edges, facets, assertions, episodes, and experiences
- Synonym-aware edge dedup prevents predicate drift
- Confidence accumulation uses noisy-OR: `1 - (1-old)(1-new)`, capped at `agent.memory.l2.confidence.accumulation_cap` (default 0.99)

#### L2 Projection Pipeline

The default execution model:

1. `L1` fact is successfully written to durable store
2. Synchronous rule evidence classification and policy resolution run on the stored event when available
3. If `cognition_eligible=true` and evidence policy allows cognition, an `l2_projection_jobs` record is created in `memory.db`
4. If evidence classification is unavailable or inconclusive, raw L1 storage remains successful, but fact promotion and L2 graph/assertion writes wait for evidence resolution rather than treating the event as authoritative by default
5. `L2Pipeline` in the `runtime_worker` claims ready jobs and marks them `queued`
6. Claimed events are batched by batch owner / session / user; the worker marks jobs `running` before extraction
7. Successful extraction marks jobs `completed`; failures mark them `failed` or requeue to `pending`

Batch policy:

- Plugins provide `l2_batch_policy()` with advisory batching info: `max_events`, `min_ready_events`, `max_estimated_tokens`, `max_wait_seconds`
- For high-throughput sources, plugins can provide `catch_up_owner` for coarser-grained catch-up shards
- The pipeline switches between `catch_up` (throughput-focused) and `steady_state` (latency-focused) modes based on backlog
- Durable claim is subject to runtime backpressure
- Plugin sync cursors only track "synced to L1", not L2 progress
- The `runtime_worker` registers `memory_l1_maintenance` as a periodic task for L1 retention cleanup, including compressible L1 events that are already covered by L3 summaries and pinned-payload pruning.
- The `runtime_worker` registers `memory_l2_maintenance` as a periodic task for offline entity catalog / knowledge graph maintenance, including ghost references, mergeable types, orphan entities, assertion reconciliation, edge embedding refresh, predicate consolidation, and promotion-counter pruning.
- The `runtime_worker` registers `memory_l2_consolidate` as a separate periodic task for episode promotion/merge/invalidations, experience promotion, and missing episodic/experience summary generation.
- L2 experience consolidation caps LLM-backed seed selection per run, then falls back to local selection for remaining seeds so daily maintenance cannot spend unbounded time waiting on model calls.
- The `runtime_worker` registers `memory_l3_maintenance` as a periodic task for L3 summary retention cleanup.
- The `runtime_worker` registers `runtime_operational_gc` as a periodic task for non-layer cleanup such as L0 session expiry/checkpointing, runtime operational garbage collection, and chat asset garbage collection.
- `MaintenanceDaemon` remains only for lightweight process-local checks such as health checks and log-size warnings; it does not own data-retention cleanup.
- Manual `/l2/episodes/reconsolidate` uses the same scheduler target lock as `memory_l2_consolidate`; if consolidation is already running, the endpoint returns HTTP 409 instead of competing with scheduled episode consolidation.

Extraction flow:

- Phase 1 extracts current-batch entities, facts, and candidate observations from admitted events, using source-owned hints and extraction-profile instructions as anchors.
- Before Phase 2, the pipeline may build a deterministic evidence packet from current Phase 1 output, bounded L1 history contexts, existing L2 graph edges, and existing assertion state. This retrieval step must not call an LLM; it is a cost-controlled recall step that gives Phase 2 corroboration, conflict, and prior-state context. The packet also reports how many prior history contexts support each current candidate, so Phase 2 can distinguish a one-off mention from a recurring signal without adding another LLM recall step.
- Phase 2 integrates the current batch plus that deterministic packet into graph writes, contradiction hints, and eligible assertion candidates under the active extraction profile.
- Passive, single-source observations remain evidence. They should not become stable user-profile assertions unless source policy and graph-derived rules provide enough accumulated support.

A rare set of runtime-only events without `L1` durable anchors can use the in-process dispatch path, but they are not considered regular inputs to `L2` durable projection.

#### Evidence Classification and Write Policy

L2 ingestion uses shared evidence classification before LLM extraction. The implementation lives in the shared `magi.memory.evidence` package and is consumed by L1 retrieval annotation, fact-like retrieval scoping, and L2 write governance.

Classifier and policy responsibilities:

- Active classifier outputs: `user_self_report`, `assistant_tool_grounded`, `assistant_freeform`, `assistant_runtime_derivation`, `system_runtime`, `external_observation`
- Reserved policy classes: `user_report_about_others`, `assistant_quote`; these are present in the policy matrix for provenance-specific classifiers and explicit policy tests, but ordinary assistant quote-like text currently classifies as `assistant_freeform` unless upstream marks it more specifically
- Each class maps to a `PolicyDecision` controlling `allow_graph_write`, `allow_assertion_write`, `evidence_weight`, etc.
- `public_topology` and `stable_preference` fact kinds require explicit or structured extraction sources
- User questions, user requests/commands, assistant memory answers, and assistant freeform text must not become new user-profile facts through L2 graph/assertion writes
- Unknown evidence can be retained as raw L1 and episode/audit material, but must not be promoted into fact-like retrieval or L2 graph/assertion state without an explicit policy decision
- Existing L1 rows with missing, stale, or failed evidence annotations are repaired through `L1EventStore.backfill_evidence_annotations`, which reuses the same shared classifier and policy resolver

#### L2 Write-Side Semantic Conventions

Source integrations enrich events before L2 processing:

- Source integrations pass `structured_entity_hints` via `MemoryEvent.metadata_json`
- Sensor integrations pass `fact_hints` as the preferred source-owned structured-fact path
- Legacy `relation_candidates` may still feed older timeline/relation projections, but should not be the primary L2 cognition path for new plugins

Core principle: whoever best understands the raw data produces the high-confidence structural facts. `L2` is responsible for unified integration, conflict handling, persistence, and residual LLM extraction.

Write pipeline:

```text
Plugin / Sensor / Host integration
  -> source-owned semantic enrichment
  -> MemoryEvent.metadata_json
  -> Ingestion gateway normalization + admission
  -> L2 pipeline merge / conflict handling / persistence
```

**Enrichment ownership** is split by who understands the data:

- **Source-owned enrichers** — For browser history, calendar, maps, photo library, git activity, etc.
- **Modality-owned enrichers** — For images, PDFs, links; extract EXIF, OCR, titles, canonical URLs
- **Residual LLM extraction** — For free-form chat text or low-structure sources; fills remaining semantics

**Fact kinds** distinguish object structure from user evidence:

- `public_topology` — Stable object structure (e.g. account belongs to platform, place located in city)
- `interaction_evidence` — User interactions (e.g. visited, viewed, followed, used)
- `stable_preference` — Explicitly expressed preferences or high-confidence configuration exports

"Like" should not be simplified to a single graph predicate at write time. For most passive sources, the more appropriate durable representation is to write interaction evidence first, then let the query side perform affinity aggregation.

Tags, categories, and weak co-occurrence are not fact evidence. They may help search, grouping, or source-local summaries, but they must not become L2 user preferences without an explicit fact source or a host-owned derived rule over accumulated graph evidence.

**Admission rules** — Runtime decides whether a source-owned fact enters the durable graph, based on `fact_kind`, `predicate`, and `origin_mode` (`source_explicit`, `source_structured`, `heuristic`, `llm_inferred`):

- `public_topology` — Only facts from `source_explicit` or high-confidence `source_structured` can directly form rule candidates
- `interaction_evidence` — Real events (`VISITED`, `VIEWED`, `USES`) can typically form rule candidates directly
- `stable_preference` — Passive sources cannot directly write; only explicit self-description, configuration exports, favorites/subscription lists qualify

`FOLLOWS` requires stronger signals than single content page visits; account pages, profile pages, follow lists, or explicit subscription lists are acceptable.

**Plugin and ingestion responsibilities**:

- Source integrations produce: entity hints, fact hints, optional tags/batch hints
- Ingestion gateway handles: schema validation, canonical/local ref normalization, writing hints into `MemoryEvent.metadata_json`, generating rule-backed graph candidates per admission policy
- `L2Pipeline` handles: using source-owned hints as structural anchors, merging with LLM residual candidates, conflict handling, dedup, persistence, and snapshot refresh

**Graph-derived assertions** convert accumulated graph evidence into inferred profile assertions only through host-owned rules. Built-in interest aggregation and plugin-contributed `derived_assertion_specs` both compile into validated `GraphDerivedAssertionRule` instances. These rules consume admitted graph edges, write inferred assertions through the normal assertion lifecycle, and preserve source-tier conflict protection so user-authored assertions are never overwritten by behavioral inference. Rules may constrain allowed graph object types so broad passive objects such as individual web pages, generic software names, or implementation artifacts do not become user-profile traits unless the source explicitly marks them as suitable profile evidence. Host-owned quality gates also reject low-level object labels such as raw URLs, domains, file paths, coordinates, and hash-like identifiers before they can become profile assertions; those details may remain graph evidence but should not appear as portrait traits. The host fallback interest rule is intentionally conservative: repeated same-day activity and generic software objects remain graph evidence unless a source-specific rule upgrades them with stronger semantics. Source-specific rules are appropriate for repeated behavioral domains such as repository work, GitHub project activity, terminal tool usage, foreground app usage, music listening, game play, and browser content interests; single observations from those sources remain graph evidence.

Plugins may strengthen assertion quality by declaring structured hints, graph relation candidates, extraction profiles, source-specific Phase 1 instructions, source-specific Phase 2 integration instructions, and graph-derived assertion specs. They do not own the final assertion ontology or bypass source-tier conflict governance. Direct Phase 2 assertion candidates are accepted only for profiles that explicitly opt into `assertion_mode="phase2_candidate"` and pass the host family, trait, source policy, and validation gates.

**Ontology** distinguishes LLM-facing coarse types from system-facing internal types:

- LLM-facing: `person`, `group`, `organization`, `place`, `software`, `media`, `topic`
- System-facing (structured hints only): `presence`
- Internal topology predicates: `PRESENCE_OF`, `ON_PLATFORM`, `LOCATED_IN`
- Behavioral/preference predicates: `FOLLOWS`, `VISITED`, `VIEWED`, `USES`, `LIKES`, `DISLIKES`, `INTERESTED_IN`

Key constraints:

- Platforms use `software`, not a separate `platform` type
- Creator identity uses `person` / `group` / `organization`
- Venues and cities use `place`
- `category` is not exposed as a general graph entity type to LLMs; handle it as a query/topology facet first
- Extraction profiles distinguish LLM-facing allowlists from structured-hint allowlists
- `HAS_CATEGORY` does not enter the main graph; classification values are carried in facets/structured hints

**Graph storage** persists `fact_kind` on knowledge graph edges; rule-backed and LLM candidates are unified to the same schema before insertion.

#### L2 Query-Side: Unified Query Mode Pipeline

L2 retrieval uses a unified `query_mode` system (replacing the legacy `recall_intent` + `query_mode` dual system).

**Ten unified modes** are registered in the mode registry:

| Mode | Primary Layer | Evidence Shape | Reducer |
|------|--------------|---------------|---------|
| `event_stream` | L1 | passthrough | passthrough |
| `exact_fact` | L2 | fact_card | span_select |
| `current_state` | L2 | state_card | latest_version |
| `episode_recall` | L2 + L1 | episode_bundle | narrative |
| `experience_recall` | L2 + L1 | episode_bundle | narrative |
| `cross_session` | L2 + L1 | grouped_list | enumerate |
| `temporal_compare` | L2 + L1 | comparison_frame | anchor_compare |
| `summary` | L3 | passthrough | passthrough |
| `activity_summary` | L3 | activity_digest | time_window_aggregate |
| `strategy` | L4 | passthrough | passthrough |

Each mode defines a `QueryModePlan` with:

- Layer weights for mode-adaptive RRF
- Primary and secondary layer preferences
- Evidence assembler type and reducer type

The evidence assembler and reducer fields are the mode contract, not a guarantee that every named reducer has a dedicated implementation today. If a named assembler or reducer is not registered, the hybrid retrieval service still returns normal layer payloads and answer-facing findings for that mode. In the current implementation, `activity_summary` is exposed through the mode registry and `memory_query` tool; its `activity_digest` / `time_window_aggregate` entries describe the intended reduced evidence shape while the answer-facing path prioritizes L3 summary findings and falls back to L1 activity evidence.

**Fallback / auto routing**: Tool callers should pass an explicit `query_mode` when the answer shape is clear. Product-facing search surfaces and uncertain tool callers may omit `query_mode` to request auto routing. In that case the rule router chooses a mode from the query text, defaulting to `exact_fact` when no stronger signal is present. The workbench trace exposes the requested mode, resolved mode, executed layers, and per-layer result counts.

**Legacy migration**: Old `recall_intent` values (`event_recall`, `preference_recall`, etc.) and old mode names (`detail`, `experience`, `graph`) are mapped to unified modes via `normalize_query_mode()`.

**Semantic frame**: The `L2SemanticFrame` expresses structured query slots:

- `query_family` — affinity, relationship, profile, activity, lookup
- `subject_scope` — self, explicit, multi, none
- `subject_mode` — self, single, multi, none
- `relation_shape` — single_fact, shared_fact, between_people, comparison, two_hop, unknown
- `subject_mentions` / `object_mentions` — role-specific query mentions, used before generic entity order
- `answer_kind` — creator, place, topic, person, software, media, unknown
- `entity_mentions` — raw entity names or mentions extracted from the query for resolution
- `constraints` — controlled constraint list, not arbitrary graph queries

The semantic frame is the authoritative L2 role contract. Top-level `entities`, `subject_hint`, and `predicate_family` are derived from it for older execution helpers rather than treated as a separate LLM contract. Explicit-subject grounding must bind the resolved subject entity before graph retrieval. If the semantic frame says the query is about a single explicit entity, the first matching `subject_mentions` entry is the graph subject and matching `object_mentions` entries remain object candidates. Collective multi-person queries that ask for shared, common, or mutual facts use `subject_mode=multi` / `relation_shape=shared_fact` and seed retrieval from every matching subject rather than forcing one person. L2 relationship results must also be scoped back through their `L1` evidence event IDs to the current memory owner; an edge that cannot be verified against the caller's L1 scope must not answer a fact-like query.

**Query execution pipeline** conceptually follows this shape:

```text
Natural language
  -> SemanticFrame (extract stable semantic slots)
  -> ResolvedFrame (resolve constraints to executable form)
  -> CandidateSet + EvidenceSet (topology/facet → candidates, then evidence)
  -> RankedAnswer (aggregate and rank by query semantics)
```

**Candidates first, then evidence aggregation**: For `affinity` queries, platform/place/category constraints find candidate objects first, then user-candidate edges are used to compute affinity. Object eligibility and affinity strength are determined by separate mechanisms.

Explicit non-vector entity matches from the query are hard grounding constraints for L2 relationship retrieval. For example, if the query names or aliases a known place/software/person, structured graph lookup narrows to that object id; vector-only entity matches remain soft candidates and must not become hard filters.

**Affinity is read-time aggregation, not a single predicate**. For different answer kinds, strong evidence differs:

- Creator: `FOLLOWS`, explicit `LIKES`, `INTERESTED_IN`, repeated consumption
- Place: explicit `LIKES`, repeated `VISITED`
- Software: `USES`, explicit `LIKES` / `DISLIKES`
- Topic: `INTERESTED_IN`, explicit `LIKES`, repeated consumption

Scoring model: positive and negative evidence aggregate separately; direct evidence outweighs lifted evidence; multiple weak evidences use saturating aggregation; yes/no decisions model positive and negative evidence independently.

**Constraint scopes**:

- `target` — Modifies the answer object itself (e.g. "UP hosts on Bilibili", "cafes in Hangzhou")
- `interaction` — Modifies the interaction context (e.g. "places I frequent when in Hangzhou", "who I watch when using Bilibili")

Controlled facets: `platform`, `located_in`, `category`. Parsed constraints are either entity-backed (resolvable to graph entities) or facet-backed (carried in `entity_facets` sidecar).

**Strategy-style execution helpers**: Query execution templates are selected by `(query_family, answer_kind)` combinations. The current implementation dispatches affinity plans through `L2SemanticRelationshipMixin` and semantic-frame helper functions rather than a standalone registry object. Extending should still be done by adding focused constraint handlers, evidence collectors, grouping/scoring helpers, or new strategy modules instead of adding large query branches.

**`presence` in queries**: Creator affinity candidates are based on `presence`; `presence -> ON_PLATFORM -> software`, `presence -> PRESENCE_OF -> person/group/organization`. Default answers aggregate by identity; only explicit account/channel queries output by `presence`.

**L1 and L2 collaboration**:

- `L2` handles stable structural constraints and long-term affinity
- `L1` handles strong time windows, single experiences, sequence, and count-based evidence
- Hybrid queries combine L2 candidates with L1 time-sliced evidence
- For `exact_fact` recall, answer-facing results should retain direct `L1` evidence for non-enumeration fact questions when available; time-anchored queries should preserve the strongest `L1` evidence first. `L2` may summarize or disambiguate, but should not replace the underlying fact text outright

**Observability**: Execution traces include the generated `SemanticFrame`, `ResolvedFrame`, selected strategy key, active providers/collectors, matched constraints, and top-contributing evidence items.

#### User Agency and Privacy

Users can interact with L2 artifacts directly:

- **Assertion feedback**: `apply_user_feedback(assertion_id, "confirmed"/"rejected")` — adjusts confidence and validation state
- **Assertion correction**: `correct_assertion(assertion_id, new_value)` — supersedes old assertion, creates a corrected one at high confidence
- **Edge rejection**: `reject_edge(triple_id)` — marks a knowledge graph edge as `user_rejected`
- **Episode annotation**: `update_episode()` supports `user_label`, `user_note`, `user_pinned` fields
- **Episode review curation**: active episodes can regenerate their L3 recap,
  add or remove suggested member events, merge with a suggested active episode,
  or split into two chronological child episodes by event breakpoint. User-facing
  episode review surfaces should default to curated chapter-like episodes and
  keep raw L1 event identifiers in evidence/debug paths rather than primary
  reading views.
- **Experience review curation**: active experiences can be renamed, annotated,
  assigned a local media cover, hidden, regenerated, merged, split, and
  eventually curated at either source episode or direct event granularity.
  Experience edits update the L2 experience object and its membership; the L3
  review is regenerated or superseded from the updated evidence boundary.
- **Forget entity**: `forget_entity(entity_id)` — cascade soft-delete across KG edges, assertions, facets, and episodes
- **Forget time range**: `forget_time_range(start, end)` — invalidates episodes and archives assertions/edges in the range
- **Forget episode**: `forget_episode(episode_id)` — invalidates the episode, optionally returns member event IDs

Privacy scope (`privacy_scope`) is a day-1 architecture concern carried on every durable L2 object (assertions, edges, facets, episodes, experiences).

The default memory UI starts from a product overview rather than a raw layer
workbench. That overview aggregates L1 source coverage, L2 reviewable
assertions, L3 reviewable insights, storage usage, and recent memory formation.
Its summary cards show current memory totals plus live same-day formation
deltas from L1 event creation, L2 assertion inference, and L3 summary creation;
storage remains a current usage value until a durable daily snapshot exists.
A dedicated Sources page expands the overview's source coverage into a
user-facing ledger with per-source status, recent intake, and full-page source
detail views for recent raw items and source actions. Raw L1 events, L2 graph
inspection, and L4 skill memory remain available from Manage as
operator/developer surfaces, not as the default mental model for ordinary
memory review.
The memory story feed is a backend-assembled read model over L3 insight and
temporal summary records. The API owns story grouping, summary-page visibility,
featured ordering hints, display timestamps, preview text, detail lead text, and
summary statistics. Frontend story surfaces may translate labels and choose
visual treatment, but they should not reclassify raw `summary_category` values
or recompute story-feed statistics from the raw records.
The About You page presents the user-facing self portrait as an ordered
world model: first a grouped view of identity, long-running projects,
preferences, working style, and stable facts; then reviewable items that need
user judgment; then recent state observations. Personal-profile fields are
strong inputs to this portrait, not a second visible portrait surface. It should
translate L2 assertion metadata into readable groups and review actions instead
of exposing raw assertion/family/status names as primary UI copy.
`GET /api/memory/portrait/self` returns this as a backend-assembled `self_view`
with `world`, `review`, and `recent` sections. The legacy flat `observations`
list may remain as compatibility material, but page classification belongs in
the backend read model. The frontend may translate section and source labels,
but it should not infer grouping from keywords, source names, or raw text.
When a materialized `user_portrait_projection` exists, the endpoint may return
that page model directly only when it is fresh; otherwise it must rebuild it
from current profile, assertion, snapshot, and safe graph inputs. If no
materialized row exists, it can assemble the same shape from the current
projection/snapshot/assertion fallback path. The fallback path must use the same
portrait qualification policy as the materialized projection so weak passive
assertions do not leak into the page before the cache is refreshed.
The read model may include safe L2 graph relationships such as visited places
or owned/used tools as user-visible clues; those clues do not become durable
profile assertions unless they pass assertion policy separately.
The chat portrait rail is a separate surface: it may retrieve memory snippets
and render them in the active persona's voice for the current conversation, but
that presentation is not the product-facing self portrait and must not own
memory-layer projection rules.

### L3 — Reflection and Summaries

`L3` stores time-windowed or topic-compressed reflective memory.

Its purpose is to reduce cost for:

- Historical review
- Periodic summarization
- Pattern recognition
- Reflection-oriented prompt assembly

Typical outputs:

- Temporal summaries
- Topic summaries
- State-change summaries
- Trend-shift summaries
- Task reflections

`L3` should be more readable and searchable than raw `L1` event sequences, while always being traceable back to supporting evidence events.

`L3` vector index uses `summary` as the parent object and `chunk` as the retrieval unit.

#### Insight Generation Contract

Insight-style L3 records are produced from structured lower-layer outcomes, not from an open-ended LLM decision. The owning service first builds a typed candidate from L2 reconciliation, contradiction, trend, or task-outcome packets. A deterministic gate decides whether the candidate has user-facing value; only accepted candidates are persisted.

The gate must be rule-based and inspect structured state such as:

- assertion lifecycle status (`tentative`, `corroborated`, `stable`, `contradicted`, `superseded`)
- normalized trait/value changes
- evidence event count and time span
- insight category policy, such as state change vs. trend shift

LLMs may rewrite accepted insight content for readability, but must not decide whether an insight exists, what confidence/status it has, or which evidence supports it. Template text must remain available as a fallback.

Each recurring insight carries a stable `insight_key`. State-change and trend-shift keys are scoped to the entity and reviewable trait group, not to every currently observed value or every exact low-level trait in the packet, so an accumulating preference signal updates one reviewable card instead of creating a new row every time another value or adjacent preference facet appears. Writes are upserts by that key: repeated reconciliation of the same state updates evidence metadata or returns the existing record instead of creating another row. User-review fields such as `review_state` and `insight_metadata` belong to the L3 record so the frontend can present insights as reviewable cards rather than raw debug logs.

Trend-shift insights are reserved for durable long-span signals. Sparse or volatile outcomes should remain L2 evidence and should not become L3 trend cards until they have enough evidence, enough elapsed time, and a non-volatile stability kind.

#### Temporal Summary Generation

Temporal L3 summaries are generated by the host memory runtime, not by individual plugins. The runtime scheduler currently registers core interval targets for `hour`, `day`, `week`, and `month`. Source-specific activity schedules are registered from merged plugin summary profiles when their requested windows are in the scheduler interval catalog, and they may request a narrower `source_filter`; they still write normal L3 summary records through the same store. The temporal summary store and LLM service also understand `quarter` and `year` summary categories for explicit callers or future schedules that provide appropriate windows.

L3 summary generation and L3 retention maintenance are separate scheduler targets. `memory_l3_summary` creates or updates summaries; `memory_l3_maintenance` ages out old summaries according to the configured memory history behavior.

There is no separate digest layer or digest-specific scheduler. A digest-style view is just a temporal L3 summary with a time window, evidence links, and normal L3 retrieval behavior.

L3 summary LLM calls use the optional `memory_summarizer` runtime scenario. This scenario is intentionally not a required normal-settings choice: when it is absent, the scenario pool falls back to `core`, so users are not forced to understand or configure a separate summary model. Operators may still define `memory_summarizer` explicitly in configuration when summary generation should use a different model profile.

Temporal LLM generation is split into two calls over the same stable evidence-prefix prompt. The first call produces the user-facing detail body and is the required product output. The second call reuses the same evidence prefix plus the accepted body to extract a short `essence_prose` preview and optional structured fields such as topics, entities, sentiment, and change/pattern metadata. If the structured extraction fails, the accepted body still writes as a `temporal-llm` summary with empty structured fields and no preview. Rule-backed summaries remain an internal fallback and retry/debug lower bound; they should not be treated as normal Summary-page content unless a UI-specific quality gate explicitly allows them.

The same product contract applies to thematic topic summaries and episodic/experience summaries: user-facing prose is generated first and structured fields are extracted afterward. A failed structure pass must not discard accepted prose. L3 insight renderers also apply a display-quality gate; L2 natural summaries that still look like raw machine signals are ignored and the renderer falls back to structured family/value text or skips the insight.

Generation starts from `L1` facts that are eligible for cognition and excludes runtime telemetry and disposable events. The store does not load every matching event into the prompt. Instead, [evidence_selector.py](../backend/src/magi/memory/l3/evidence_selector.py) performs source-aware compaction:

1. Query lightweight per-source counts for the requested time window.
2. Allocate a bounded raw-evidence quota across sources using a per-source floor plus square-root weighted remainder.
3. Fetch a larger per-source feature pool for plugin-local aggregation.
4. Select representative raw events using a mix of recency, importance, and time spread.
5. Attach coverage metadata to the evidence pack so the model knows what was selected and what was omitted.

The default policy is `source_aware_compaction_v1`:

- raw events selected for the LLM evidence pack: up to `120`
- feature events exposed to each source plugin: up to `240` per source
- quota strategy: `per_source_floor_plus_sqrt_weighted_remainder`
- representative strategy: `recent_plus_importance_plus_time_spread`

The temporal evidence pack records:

- `window_event_count` — total eligible L1 events in the window
- `source_event_count` — selected raw events in the prompt evidence pack
- `omitted_event_count` — eligible events not represented as raw prompt events
- `source_distribution` — per-source total, selected, feature-pool, omission, and importance stats
- `selection_policy` — policy version and quota parameters
- `previous_period_summaries` — compact same-category summaries ending before this window, used only for comparison
- `child_period_summaries` — compact lower-granularity summaries inside this window, such as week summaries inside a month

This metadata is part of the prompt contract. The temporal summarizer must treat selected raw events as representative evidence, not as an exhaustive list of everything that happened in the window.

Previous and child period summaries are timeline context, not new evidence. They may help the model describe drift, continuity, or phase changes, but current-window facts must still be grounded in the current evidence pack. By default, `hour` and `day` summaries receive one previous same-period summary; `week` and `month` summaries receive up to three previous same-period summaries; `quarter` and `year` summaries receive up to two previous same-period summaries. Child context uses the next lower timeline scale: day summaries may include hour summaries, week summaries may include day summaries, month summaries may include week summaries, quarter summaries may include month summaries, and year summaries may include quarter summaries.

Temporal summary generation must honor the user's configured language preference even when running from scheduler contexts that do not carry an HTTP language header. The temporal summarizer passes the target language in both system and user prompts and rejects model outputs whose user-facing fields clearly violate the target language, falling back to deterministic rule text rather than storing mixed-language summaries.

Temporal LLM calls use period-specific generation profiles by default:

- `hour` windows get up to `180` seconds, keep thinking disabled, and focus on local sequence, immediate context, and short-lived shifts.
- `day` windows get up to `300` seconds, enable thinking, and focus on day blocks, attention shifts, explicit decisions, and repeated constraints.
- `week` windows get up to `600` seconds, enable thinking, and focus on durable themes, recurring interests, cross-source patterns, and notable changes.
- `month` windows get up to `600` seconds, enable thinking, and focus on cross-week themes, stage changes, sustained interests, project progress, and unusually frequent activities.
- `quarter` windows get up to `600` seconds, enable thinking, and focus on durable projects, decisions, constraints, source-specific habits, and cross-month phase changes.
- `year` windows get up to `600` seconds, enable thinking, and focus on year-scale durable themes, long-running projects, decisions, constraints, recurring interests, and unusually frequent activities.

The legacy flat `temporal_llm_timeout_seconds` setting remains an explicit override for testing or operator tuning; the previous default value `3.0` is treated as "use the period profile" so it does not force production summaries through a three-second budget.

Rule fallback is a user-facing lower bound, not a debug dump. It should describe the dominant sources or themes first, then add compact source-specific signals such as focus domains or repeated sites when available. Raw event counts, internal event type names, and compression counters belong in summary metadata rather than in the summary body unless they materially change interpretation.

Temporal summaries should remain compact, but they must not be over-compressed into a single generic paragraph for `day`, `week`, or `month` windows. The generated `content` field should preserve period-appropriate concrete anchors such as projects, tools, services, domains, media titles, decisions, and unresolved follow-up threads. The optional `essence_prose` field is the card-level preview for product surfaces: it should quickly answer what this period was about without replacing the richer `content`. The structured `change_and_pattern` payload may include `timeline`, `source_signals`, `decisions_and_actions`, `changes`, `patterns`, and `open_threads` arrays. These structured fields are part of the retrieval surface: L3 FTS and vector text include both the readable content and the structured summary fields so later recall can recover details even when the visible recap stays concise.

#### Plugin Temporal Features

Plugins may provide compact source-local features for temporal summaries through `build_temporal_summary_features`. The host passes the plugin a bounded event pool and a `TemporalSummaryFeatureBudget` that reports total, available, selected, and omitted counts for that source.

Plugin outputs should be structured evidence, not final cross-source summaries. Good outputs include:

- top domains, apps, artists, calendars, repositories, tags, or places
- coverage counts and coverage ratio
- time buckets or source-native session counts
- representative event ids
- short source-local `summary_lines` grounded in the provided event pool

The host attaches returned features to `TemporalEvidencePack.plugin_summary_features` and still performs the final L3 generation centrally. This keeps source-specific aggregation close to the source while preserving one cross-source summary model, one L3 persistence contract, and one retrieval surface.

Important boundary: if a source's events are stored in L1 with `cognition_eligible=false`, they will not participate in generic L3 temporal generation unless the selection policy or the source's memory policy is explicitly changed. A plugin hook alone does not override event admission policy.

### L4 — Procedural Memory

`L4` distills "how to do things better next time" execution experience.

It answers:

- What approach usually works best here?
- Which workflows frequently fail?
- Which workflow should be prioritized next time?
- Which tools or strategies should be avoided?

`L4` does not recount historical facts; it distills future execution guidelines.

Authoritative tool execution truth lives in `runtime_trace.trace_tools`. Exact tool attempts, provider challenges, errors, latency, and success counts should be read from runtime trace when a surface needs auditable execution facts. The current L4 store also maintains denormalized procedural rollups such as `total_attempts`, `success_rate`, bounded `l4_execution_traces`, circuit-breaker state, strategy hints, and context affinity for skill learning and fast advisory reads. Treat those L4 fields as cached procedural overlays that must be reconcilable with runtime trace, not as the canonical source for execution-history inspection.

`L4` vector index uses `skill` as the parent object and `chunk` as the retrieval unit.

`L1` / `L2` / `L3` / `L4` vector write pipelines share a common embedding pipeline; each layer defines only its own text builder, chunk strategy, parent-table status writeback, and retrieval collapse logic.

Examples:

- Common workflow templates
- Circuit-breaker states for unstable tools
- Successful strategy templates for task categories
- Context-dependent execution preferences
- Explicit task-handling preferences stated by the user

---

## Event Contract and Routing

All data entering durable memory is normalized into the `MemoryEvent` defined in [backend/src/magi/memory/event_contracts.py](../backend/src/magi/memory/event_contracts.py).

A fully normalized durable `MemoryEvent` carries these required fields, either supplied by the producer or derived during normalization:

- `event_id`
- `correlation_id`
- `event_type`
- `source`
- `timestamp`
- `created_at`
- `content`
- `memory_domain`
- `ingest_target`
- `cognition_eligible`
- `tom_depth`
- `retention_class`
- `author_type`
- `content_type`
- `importance_score`
- `level`

Optional identity, payload, embedding, and observability fields include:

- `source_item_id`, `idempotency_key`, `media_path`, `metadata_json`
- `session_id`, `turn_id`, `user_id`, `task_id`
- `embedding_status`, `embedding_profile_id`
- `causation_id`, `trace_id`, `span_id`, `parent_span_id`

### memory_domain

Expresses what semantic category the event belongs to.

Canonical domains:

- `user_authored`
- `interaction`
- `external_activity`
- `runtime_telemetry`
- `system_control`

This is the foundational field for isolating user experience, external activity, and runtime noise.

### ingest_target

Expresses where the event should initially land.

Canonical targets:

- `l0_only`
- `l1_only`
- `l0_and_l1`

This separates current execution signals from long-term memory facts.

### cognition_eligible

A coarse-grained boolean switch controlling whether an event can enter higher-level cognition.

- `true` — Allowed to participate in cognition and summarization
- `false` — Can enter `L1` but defaults to not participating in cognition

Durable storage and higher-level reasoning are not the same thing.

### retention_class

Expresses lifecycle policy:

- `permanent`
- `compressible`
- `disposable`

Retention policy must be an explicit contract, not implicit post-processing.

---

## Event Identity Rules

`L1` explicitly distinguishes internal primary key, stable external reference, source-side identity, and business idempotency key. These are strong constraints.

1. **`id`** — SQLite internal primary key. Used only for internal joins, sorting, and local relationship efficiency.

2. **`event_id`** — Stable external event identifier. Used for timeline references, `L2`/`L3` evidence backlinks, API responses, and logging.

3. **`source_item_id`** — Source-side item identity. Represents the producer's own business item identifier.

4. **`idempotency_key`** — Business idempotency key. Answers "is this the same business event?", not "is this the same database row?".

### L1 Uniqueness Rule

When `idempotency_key` is present, `L1` deduplicates by:

```sql
CREATE UNIQUE INDEX idx_fact_events_business_idempotency
  ON fact_events(source, event_type, idempotency_key);
```

This means:

- `event_id` is not the business dedup key
- `source_item_id` does not default to the business dedup key
- Internal `id` must never be reused as `event_id`

### Concrete Example

A Chrome history burst might look like:

- `id = 128431`
- `event_id = "evt_01JQ..."`
- `source = "chrome_history"`
- `event_type = "SENSOR_EVENT"`
- `source_item_id = "181979-181982"`
- `idempotency_key = "default:181979-181982"`

The system uses:

- `event_id` as the cross-layer stable reference
- `id` for internal joins
- `source_item_id` to display or echo source-side identity
- `(source, event_type, idempotency_key)` for business idempotency

---

## L1 Fact Event Storage

The `L1` canonical store is at [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py).

The `fact_events` core schema:

```sql
CREATE TABLE fact_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,
    idempotency_key TEXT,
    memory_domain INTEGER NOT NULL,
    cognition_eligible INTEGER NOT NULL DEFAULT 0,
    retention_class INTEGER NOT NULL DEFAULT 2,
    session_id TEXT,
    turn_id TEXT,
    session_seq INTEGER,
    user_id TEXT,
    content TEXT NOT NULL,
    author_type INTEGER NOT NULL,
    content_type INTEGER NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    media_path TEXT,
    metadata_json TEXT,
    deleted_at REAL,
    evidence_status INTEGER NOT NULL DEFAULT 1,
    evidence_class INTEGER NOT NULL DEFAULT 1,
    evidence_rule_version INTEGER NOT NULL DEFAULT 1,
    l1_retrieval_scope INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX idx_fact_events_business_idempotency
    ON fact_events(source, event_type, idempotency_key);

CREATE TABLE l1_session_sequences (
    session_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE l1_event_embedding_state (
    event_id TEXT PRIMARY KEY,
    embedding_status INTEGER NOT NULL DEFAULT 1,
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    updated_at REAL NOT NULL
);
```

Key notes:

- `event_id` is the external stable reference key
- `id` is the internal relationship key
- `session_seq` is the stable event order within a session; local context windows and evidence bundles should use it instead of depending on `turn_id` naming conventions
- `metadata_json` carries structured event payloads
- `author_type`, `content_type`, evidence fields, retrieval scope, and embedding status are stored as compact integer codes and decoded to labels at runtime/API boundaries
- Canonical `l1_retrieval_scope` labels are `none`, `fact_authoritative`, `conversation_only`, `audit_only`, and `source_backlink_only`
- Evidence columns describe L1 retrieval authority for the event; L2 graph/assertion policy remains a runtime decision and is not duplicated into `fact_events`
- Unknown or failed evidence annotations default to `l1_retrieval_scope='none'`
- Versioned evidence annotations can be backfilled in place without rewriting raw event content
- Embedding observation fields live in `l1_event_embedding_state`; `fact_events` remains the durable event truth table
- Durable events support soft deletion via `deleted_at`
- Schema evolution is migration-backed for current local databases; very old pre-Alembic development databases may still need a rebuild

---

## How Data Enters the Memory System

Producers are diverse, but all converge on the same memory contract.

### Chat Projection

Chat truth is first written to `chat.db`. A subset is then projected as `L1` canonical facts. This projection is intentionally lossy: it retains what memory needs, not a full transcript copy.

### Sensors and Plugins

Sensors run in the awareness layer and produce `SensorOutput`. The `SensorIngestionGateway` projects these outputs into memory.

For external activity sources, `SensorOutput` is not the final `L1` string. It is a source-truth envelope with:

- `activity`: structured source/action semantics owned by the plugin
- `narration`: factual body/title owned by the plugin

The host runtime then materializes that truth into durable memory projections:

- `content`: canonical persisted `L1` text
- `metadata_json.activity`: minimal stable retrieval facets (`source_code`, `action_code`, optional `object_code`, optional `qualifiers`)
- `metadata_json.projection`: host-owned projection metadata such as `renderer_version` and optional `embedding_head`

This keeps external activity memory consistent across plugins while avoiding per-plugin free-form `L1` sentence formats.

Gateway-side normalization rules:

- External sensor events are written as durable memory with a stable owner `user_id` taken from `SensorOutput.provenance`, then `domain_payload`, and finally `identity.defaults.CANONICAL_LOCAL_USER` as fallback.
- External sensor events remain session-independent by default: `session_id` and `turn_id` are not inherited from the current chat runtime.
- The host, not the plugin, decides the final `L1` sentence shape and embedding text shape for external activity events.

This is the primary path for:

- Browser history
- App usage
- Terminal / Git activity
- Other external activity plugins

### Runtime-Generated Events

Some runtime events may be normalized into memory when worth auditing or future learning. But runtime observations and durable memory are two systems. Default principle: high-frequency execution telemetry does not enter long-term memory.

---

## Retrieval and Prompt Integration

The memory layer handles recall, retrieval, ranking, and cross-layer evidence organization. The context layer handles prompt shaping and final injection strategy.

This is a deliberate boundary:

- Memory decides "what was found"
- Context decides "which results should actually enter the prompt"

Not all retrievable memories should be implicitly injected into ordinary conversation.

### Unified Retrieval Pipeline

The `HybridRetrievalService` orchestrates cross-layer retrieval with mode-aware behavior:

- Each `query_mode` defines a `QueryModePlan` with layer weight profiles
- Each fact-like mode defines which L1 evidence scopes are authoritative for that mode; BM25, vector, and keyword retrieval must apply those scopes before topK whenever scoped indexes are available
- Mode-adaptive RRF adjusts per-layer weights based on the query mode
- Evidence assemblers shape raw retrieval results into per-mode evidence formats (fact cards, state cards, episode bundles, comparison frames, grouped lists)
- Reducers produce final answering material (span selection, latest version, narrative, anchor comparison, enumeration)
- `memory_query` does not inherit the current chat session unless the caller explicitly provides `session_id`
- Unconstrained `L2` lookups must not degrade into a global "recent relationships" / "recent assertions" scan
- LLM-facing memory tool payloads should keep human-readable findings only; opaque ids stay in debug/observability channels rather than prompt context
- the answer-facing `historical_recall` contract may additionally expose compact `entity_refs` and `asset_refs` for reply-turn continuity and source-owned follow-up resolution, but raw local paths remain outside prompt context
- plugins may optionally enrich these refs through a recall-artifact projection hook keyed by `source_type`; memory still owns the final query contract and chat still owns attachment import/display
- For fact-like recall modes, answer-facing projection treats chat-derived assistant freeform replies and chat-derived user question prompts as non-authoritative artifacts. This projection hygiene is a last-mile defense; the primary defense is authoritative evidence scoping before retrieval ranking. These artifacts may remain in `L1` for audit or conversation replay, but they must not become factual `historical_recall.findings` unless the caller explicitly asks for chat-source evidence or uses a conversation-recall mode.
- Generic topK recall is representative evidence, not an exhaustive count surface. Queries that ask for counts, totals, or full enumeration need an explicit coverage contract. When a source-backed structured recall provider can answer exhaustively, it must set `coverage.can_claim_total=true`; otherwise downstream prompts and UI must treat returned findings as samples and avoid total-count claims.

Layer contributions:

- `L1` — Primary event fact recall
- `L2` — Structured evidence (graph edges, assertions, episodes, entity facets)
- `L3` — Compressed summary context
- `L4` — Execution experience and reusable strategies

### Prompt Strategy

Current implicit injection remains conservative:

- `L0` is default implicit context
- Higher-layer memories require explicit justification for injection
- Explicit historical recall and implicit prompt injection are separate decisions

This prevents stale, weakly-relevant, or noisy memories from being over-injected into ordinary conversation.

---

## Timeline Integration

The timeline module (`backend/src/magi/timeline/`) is a **read model** that consumes memory products. It does not own canonical truth.

Key integration points:

- **Episode-aware clustering**: At `day` and `week` scales, the timeline cluster builder prefers durable L2 episodes over transient re-clustering. Events not covered by any episode are clustered transiently to fill gaps. At `hour` and `month` scales, transient clustering is used exclusively.
- **State bands**: The state band builder derives `valence`, `stress_level`, and `engagement` from L3 summaries, L2 assertions, and ToM snapshots. Assertions with `superseded`, `archived`, `expired`, or `user_rejected` status are excluded.
- **State transitions**: The viewport builder extracts state transitions from superseded assertion chains, producing `{trait_name, old_value, new_value, changed_at}` records.
- **Episode context bundles**: When an anchor has an `episode_id`, the context bundle builder loads member events from `episode_events` instead of scanning by `representative_event_ids`. Bundles include `user_label` and `user_note`.
- **Viewport payload**: At `day`/`week` scales, the viewport includes `episodes`, `state_transitions`, `state_bands`, `clusters`, and `reflections`.
- **Activity previews**: L1 metadata may carry an `activity_snapshot` block for
  source title, summary, tags, entities, provenance, and asset references. This
  is a neutral memory snapshot; timeline owns the final read-model payload and
  should not require memory metadata to store a `timeline`-named structure.

---

## Retention, Compression, and Deletion

Retention policies are defined per event type and purpose, not as a global rule.

### General Rules

- User-authored durable memory defaults to stronger retention
- External activity is typically `compressible`
- Runtime telemetry is strictly limited or excluded by default
- Summaries and procedural memory must retain evidence backlink capability
- L1 retention uses `agent.memory.l1.retention_days`; L3 summary retention uses
  `agent.memory.l3.retention_days`. The legacy top-level
  `agent.memory.retention_days` is not the owner of scheduled L1/L3 cleanup.
- The settings UI exposes the layer-specific retention knobs that scheduled
  cleanup actually reads: L1 event retention, L3 summary retention, and L4
  inactive-skill retention.
- L1 cleanup may only delete compressible events that are already covered by L3
  summaries and are not still referenced by active L2 episodes, experiences,
  experience seeds, graph edges, assertions, or entity facets.
- L3 cleanup may age out ordinary hot-path summaries, but it must preserve
  reviewable/user-confirmed insights and episodic summaries attached to stable
  L2 episode or experience objects.

### What Compression Means

Compression does not mean "delete freely".

Compression means:

- Preserving the important shape of history
- Allowing low-value raw details to be reduced
- Still retaining enough references to explain why a summary or procedure exists

Compression must not sacrifice the only important durable representation.

---

## Operating Rules

These rules must be followed during day-to-day development:

1. Chat transcript truth lives in `chat.db`, not in `L1`
2. Runtime trace truth lives in `runtime_trace.db`, not in `L1`
3. `L1` is the canonical fact projection layer
4. `L2`, `L3`, `L4` are all derived layers that must explain their provenance from lower layers
5. Cache is a rebuildable layer and must not become an implicit truth layer
6. `event_id` is a stable external reference, not a source identity surrogate or business dedup key
7. When `idempotency_key` is present, business uniqueness is defined by `(source, event_type, idempotency_key)`
8. Read paths needing producer-side business identifiers should prefer `source_item_id`, then `idempotency_key`, not `event_id`
9. L1 retrieval authority and L2 write policy must share evidence classification semantics
10. Raw L1 writes can tolerate evidence-classifier failure; fact promotion and L2 graph/assertion writes must not treat unknown evidence as authoritative by default
11. Fact-like retrieval modes must constrain authoritative evidence before topK selection; answer-projection filters are only a last-mile guard
12. Span-level retrieval atoms, if introduced, are derived projections that hydrate back to raw `fact_events`; they are not new raw facts
13. Classifier, policy, embedding profile, and index-version changes mark derived evidence/index records stale and rebuild them instead of mutating `fact_events.content`

---

## Developer Entry Points

Main implementation entry points:

- [backend/src/magi/memory/\_\_init\_\_.py](../backend/src/magi/memory/__init__.py) — Public package entry point for the unified memory store

- [backend/src/magi/memory/unified_store.py](../backend/src/magi/memory/unified_store.py) — Unified L0-L4 memory store composition and lifecycle coordination

- [backend/src/magi/memory/layer_protocol.py](../backend/src/magi/memory/layer_protocol.py) and [backend/src/magi/memory/layers/](../backend/src/magi/memory/layers/) — Fan-out ingestion protocol and layer adapters for L0, L1, L2 projection/pipeline, and L4

- [backend/src/magi/memory/subscribers/memory_ingestion_subscriber.py](../backend/src/magi/memory/subscribers/memory_ingestion_subscriber.py) — Event-bus subscriber that translates domain events into normalized memory events

- [backend/src/magi/memory/event_contracts.py](../backend/src/magi/memory/event_contracts.py) — Standard event contracts and normalization logic

- [backend/src/magi/memory/l0/working_memory.py](../backend/src/magi/memory/l0/working_memory.py) — `L0` working memory

- [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py) — `L1` fact event store, retrieval, and vector index

- [backend/src/magi/memory/l2/store.py](../backend/src/magi/memory/l2/store.py) — `L2` durable cognition store (knowledge graph, assertions, episodes, projection jobs)

- [backend/src/magi/memory/l2/pipeline/__init__.py](../backend/src/magi/memory/l2/pipeline/__init__.py) — `L2` extraction and cognition pipeline facade, durable projection job claim/batching

- [backend/src/magi/memory/l2/episode_formation.py](../backend/src/magi/memory/l2/episode_formation.py) — Streaming episode assignment and consolidation

- [backend/src/magi/memory/evidence/classifier.py](../backend/src/magi/memory/evidence/classifier.py) — Shared deterministic evidence classification used by L1 retrieval and L2 write governance

- [backend/src/magi/memory/evidence/policy.py](../backend/src/magi/memory/evidence/policy.py) — Shared rule-based policy per evidence class for L1 retrieval authority and L2 write governance

- [backend/src/magi/memory/l1/event_store.py](../backend/src/magi/memory/l1/event_store.py) — `L1EventStore.backfill_evidence_annotations` maintenance path for repairing missing or stale L1 evidence annotations

- [backend/src/magi/memory/l3/summary_store.py](../backend/src/magi/memory/l3/summary_store.py) — `L3` summaries and evidence backlinks

- [backend/src/magi/memory/l4/procedural_memory.py](../backend/src/magi/memory/l4/procedural_memory.py) — `L4` procedural memory

- [backend/src/magi/memory/l4/task_preferences.py](../backend/src/magi/memory/l4/task_preferences.py) — Explicit task-handling preferences stored as `L4` procedural memory

- [backend/src/magi/memory/hybrid_retrieval/service.py](../backend/src/magi/memory/hybrid_retrieval/service.py) — Cross-layer unified retrieval orchestrator

- [backend/src/magi/memory/hybrid_retrieval/mode_registry.py](../backend/src/magi/memory/hybrid_retrieval/mode_registry.py) — Query mode registry (9 unified modes)

- [backend/src/magi/memory/hybrid_retrieval/l2_handler.py](../backend/src/magi/memory/hybrid_retrieval/l2_handler.py) — L2-specific handler with semantic frame planning

- [backend/src/magi/memory/integration.py](../backend/src/magi/memory/integration.py) — Runtime-facing memory integration boundary

- [backend/src/magi/awareness/ingestion_gateway.py](../backend/src/magi/awareness/ingestion_gateway.py) — Sensor / plugin event publish entry point

---

## Checklist for Plugin and Feature Developers

When connecting a new memory source, answer these questions first:

1. Is it transcript truth, runtime trace, or durable memory projection?
2. Should it land in `L0`, `L1`, or both?
3. What is the correct `memory_domain`?
4. Should it participate in downstream cognition?
5. What is the correct `retention_class`?
6. What is its source-side item identity?
7. What is its business idempotency key?

If these questions cannot be clearly answered, the feature is typically not ready to write into memory.

### Common Mistakes

- Writing raw runtime telemetry directly into `L1`
- Using `event_id` as a business source ID
- Defaulting `source_item_id` as the dedup key
- Writing mutable runtime intermediate state into the durable memory store
- Copying complete chat transcript truth into `L1`

---

## What This Document Intentionally Does Not Cover

This document does not describe:

- Phased implementation plans
- Temporary migration choreography
- Legacy schema compatibility layers
- Speculative new layers beyond `L4`

These belong in task plans, design drafts, or change notes — not in the long-term source-of-truth document.

---

## Summary

Magi's memory system is built on a simple but firm separation:

- Chat truth is not memory
- Runtime trace is not memory
- Durable memory starts from normalized `L1` facts

On this foundation:

- `L0` supports current execution
- `L1` stores canonical durable facts
- `L2` provides structured cognition across three subdomains: semantic memory (entities, relations, preferences), state memory (versioned latest-truth with supersession), and episodic memory (episode substrates plus promoted experiences)
- `L3` compresses and reflects
- `L4` distills reusable execution experience

The query pipeline uses a unified `query_mode` system, each mode defining its own evidence shape, reducer, and authoritative evidence scope. Retrieval is mode-adaptive, with per-mode RRF weight profiles and structured semantic frames for L2 queries.

User agency is first-class: users can confirm, correct, reject, annotate, and forget memory artifacts. Privacy scope is carried on every durable L2 object.

The identity model must always be clear:

- `id` — Internal join key
- `event_id` — Stable external reference
- `source_item_id` — Source-side identity
- `idempotency_key` — Business idempotency key
