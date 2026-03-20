# Runtime Trace Store Design

## Goal

Split runtime execution tracing out of the L1 memory model so chat traces, intent resolution, LLM metrics, and tool execution details are persisted in a dedicated observability store instead of being flattened into canonical memory events.

The new design should make execution traces first-class runtime data with their own schema, retention policy, and read model while keeping L1 focused on durable memory facts only.

## Problem

The current system stores runtime execution events in `runtime_observations` inside the L1 database and forces them through the same normalized event contract as durable memory facts.

That coupling creates three concrete failures:

- trace nodes are flattened into a single `content` string such as `"completed"` or `"running"`
- read-side trace reconstruction must infer hierarchy from mixed legacy events instead of reading canonical spans
- observability concerns such as LLM token usage, intent routing, and tool-call arguments are constrained by a schema designed for memory retrieval rather than execution analysis

The recent removal of `structured_payload` made this boundary failure explicit: `TRACE_NODE_COMPLETED` still executes and is written, but the structured span payload is no longer recoverable from storage.

## Design Principles

### Principle 1: Memory facts and runtime observations are different domains

`L1` should store durable facts that matter for memory, retrieval, summarization, and cognition.

Runtime trace data should store short-lived execution telemetry that matters for:

- debugging
- execution inspection
- performance analysis
- user-facing trace visualization

These two domains may share identifiers such as `turn_id`, `session_id`, and `user_id`, but they must not share a forced event schema.

### Principle 2: Persist structured trace records, not flattened text

Execution tracing must preserve the structured span payload required by the UI and read-side services:

- hierarchy
- timing
- status
- per-node metrics
- tool details
- intent resolution
- LLM usage

Trace writes should never rely on `content` as a lossy transport for structured runtime state.

### Principle 3: Read side should consume canonical trace tables

`ChatTraceReadService` should read a dedicated runtime trace store, not reconstruct spans from memory-oriented event rows.

The runtime trace store should expose:

- one turn-level summary row
- one span tree
- specialized side tables for node-specific data

### Principle 4: No compatibility branch

This refactor should move directly to the final architecture:

- no dual-write to old and new trace storage
- no fallback trace reconstruction from `runtime_observations`
- no continued dependence on L1 text fields for trace UI data

Legacy `runtime_observations` becomes removable once the new store is live.

### Principle 5: Typed internal contracts remain the default

The runtime already prefers typed internal contracts. The dedicated trace store should continue that principle with explicit write and read models rather than anonymous dictionaries in core boundaries.

## Scope

Included:

- new dedicated runtime trace database
- dedicated trace schema
- write-side trace store and typed contracts
- direct read-side consumption of runtime trace tables
- frontend trace DTO adjustments if required by the new schema
- removal of trace dependence on `runtime_observations`

Excluded:

- historical backfill from old `runtime_observations`
- export to third-party observability backends
- redesign of unrelated memory pages
- generalized non-chat observability beyond the current chat execution path

## Target Storage Model

### Database boundary

Create a dedicated SQLite database:

- `~/.magi/data/runtime_trace.db`

It is intentionally separate from:

- `~/.magi/data/memories/l1_events.db`
- `~/.magi/data/memories/memory.db`

This gives runtime tracing independent:

- schema evolution
- retention policy
- write throughput
- indexing strategy
- compaction strategy

## Tables

### `trace_turns`

One row per traced chat turn.

Purpose:

- top-level drawer summary
- turn status
- mode and orchestration identity
- high-level timing

Recommended fields:

- `trace_id TEXT PRIMARY KEY`
- `turn_id TEXT NOT NULL UNIQUE`
- `session_id TEXT NOT NULL`
- `user_id TEXT NOT NULL`
- `status TEXT NOT NULL`
- `mode TEXT NOT NULL`
- `orchestration_id TEXT`
- `started_at_ms INTEGER NOT NULL`
- `ended_at_ms INTEGER`
- `duration_ms INTEGER`
- `user_message_preview TEXT`
- `response_preview TEXT`
- `error_summary TEXT`
- `created_at_ms INTEGER NOT NULL`
- `updated_at_ms INTEGER NOT NULL`

### `trace_spans`

Canonical execution tree rows.

Purpose:

- restore hierarchy directly
- drive drawer node rendering
- expose per-node status and timing

Recommended fields:

- `span_id TEXT PRIMARY KEY`
- `trace_id TEXT NOT NULL`
- `turn_id TEXT NOT NULL`
- `parent_span_id TEXT`
- `node_type TEXT NOT NULL`
- `name TEXT NOT NULL`
- `status TEXT NOT NULL`
- `attempt_index INTEGER NOT NULL DEFAULT 1`
- `retry_count INTEGER NOT NULL DEFAULT 0`
- `iteration INTEGER`
- `execution_agent_id TEXT`
- `result_preview TEXT`
- `error_text TEXT`
- `started_at_ms INTEGER NOT NULL`
- `ended_at_ms INTEGER`
- `duration_ms INTEGER`
- `created_at_ms INTEGER NOT NULL`
- `updated_at_ms INTEGER NOT NULL`

Key indexes:

- `(trace_id, parent_span_id, started_at_ms)`
- `(turn_id, started_at_ms)`
- `(trace_id, node_type)`

### `trace_intent_resolutions`

Dedicated payload for intent nodes.

Purpose:

- explicit route explanation
- stable UI display of intent decision details

Recommended fields:

- `span_id TEXT PRIMARY KEY`
- `trace_id TEXT NOT NULL`
- `turn_id TEXT NOT NULL`
- `intent TEXT NOT NULL`
- `execution_mode TEXT NOT NULL`
- `route_reason TEXT`
- `selected_tools_json TEXT NOT NULL`
- `selected_worker_type TEXT`

### `trace_llm_calls`

Dedicated payload for `llm_call` nodes.

Purpose:

- exact model/provider/token metrics
- no more inference from mixed payloads

Recommended fields:

- `span_id TEXT PRIMARY KEY`
- `trace_id TEXT NOT NULL`
- `turn_id TEXT NOT NULL`
- `provider TEXT NOT NULL`
- `model TEXT NOT NULL`
- `input_tokens INTEGER NOT NULL DEFAULT 0`
- `output_tokens INTEGER NOT NULL DEFAULT 0`
- `reasoning_tokens INTEGER NOT NULL DEFAULT 0`
- `cache_read_tokens INTEGER NOT NULL DEFAULT 0`
- `cache_write_tokens INTEGER NOT NULL DEFAULT 0`
- `thinking_enabled INTEGER NOT NULL DEFAULT 0`
- `request_preview TEXT`
- `response_preview TEXT`

### `trace_tools`

Dedicated payload for tool-call nodes.

Purpose:

- tool name, arguments, result summary, and failure data

Recommended fields:

- `span_id TEXT PRIMARY KEY`
- `trace_id TEXT NOT NULL`
- `turn_id TEXT NOT NULL`
- `tool_name TEXT NOT NULL`
- `tool_call_id TEXT`
- `arguments_json TEXT NOT NULL`
- `success INTEGER NOT NULL`
- `execution_time_ms INTEGER`
- `error_code TEXT`
- `error_message TEXT`
- `result_preview TEXT`

### Optional `trace_events_raw`

Append-only event journal for debugging and rebuild support.

Purpose:

- raw audit trail
- diagnostic replay if projection code changes

Recommended fields:

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `trace_id TEXT`
- `turn_id TEXT`
- `event_type TEXT NOT NULL`
- `timestamp_ms INTEGER NOT NULL`
- `payload_json TEXT NOT NULL`

This table is optional and must never become the primary read model.

## Runtime Write Model

Introduce a dedicated trace store API instead of routing trace writes through `normalize_runtime_event`.

Recommended writer responsibilities:

- `start_turn(...)`
- `upsert_turn_status(...)`
- `complete_span(...)`
- `fail_span(...)`
- `record_intent_resolution(...)`
- `record_llm_call(...)`
- `record_tool_call(...)`
- `record_raw_event(...)` if the raw journal is kept

All write-side instrumentation currently emitting `TRACE_NODE_*` runtime events should write directly into this store.

## Trace Node Taxonomy

The first version should support these canonical span types:

- `turn`
- `intent_resolution`
- `iteration`
- `llm_call`
- `tool_call`
- `orchestration`
- `worker`
- `response_emit`

The important design change is that `iteration` and `tool_call` are no longer guessed from mixed runtime event types. They become ordinary spans in the canonical tree.

## Read-Side Model

`ChatTraceReadService` should be refactored to:

1. load one `trace_turns` row
2. load all `trace_spans` for the same `trace_id`
3. hydrate node-specific detail tables:
   - `trace_intent_resolutions`
   - `trace_llm_calls`
   - `trace_tools`
4. build the final UI tree strictly from `span_id` and `parent_span_id`

The read side must not fall back to `runtime_observations`.

## Relationship With L1

L1 should keep only memory-worthy facts.

Examples that stay in L1:

- `UserMessage`
- `AIResponse`
- selected `ActionExecuted` facts that are intentionally memory-relevant
- timeline or observation facts that matter for memory

Examples that leave L1 entirely:

- `TURN_TRACE_STARTED`
- `TURN_TRACE_COMPLETED`
- `TRACE_NODE_STARTED`
- `TRACE_NODE_COMPLETED`
- `TRACE_NODE_FAILED`
- `CHAT_TOOL_LOOP_STEP`
- `TOOL_INTERACTION`
- any execution-only span metadata

The shared keys between runtime trace and L1 are:

- `turn_id`
- `session_id`
- `user_id`

That linkage is enough for transcript UI, memory, and trace UI to coexist without schema coupling.

## Lifecycle And Retention

Runtime trace data should have a shorter retention window than memory facts.

Suggested policy:

- keep recent traces in full detail
- allow future pruning by age or row cap
- never let trace retention policy dictate L1 retention policy

Retention can be added after the storage split. It should not block the schema split.

## Migration Direction

This refactor should proceed as a direct cutover:

1. add runtime trace DB and store
2. switch write-side trace instrumentation to the new store
3. switch `ChatTraceReadService` to the new store
4. remove read-side fallback from `runtime_observations`
5. stop writing trace events into L1 entirely
6. remove `runtime_observations` table from L1 schema and lifecycle code

Historical trace preservation is out of scope. Old traces may disappear after the cutover and that is acceptable for this phase.

## Risks

### Risk 1: write-side scatter

Trace writes currently happen from multiple layers:

- chat postprocess
- function calling
- worker runtime

Mitigation:

- add one shared `RuntimeTraceStore` and typed writer contracts
- avoid ad-hoc SQL in feature layers

### Risk 2: partial turn completion

If a trace turn is started but not finalized, the UI may show dangling traces.

Mitigation:

- `trace_turns` should be upserted throughout execution
- completion and failure should be explicit status transitions

### Risk 3: frontend contract churn

The frontend currently consumes a snapshot tree and summary. Changing storage should not force a product redesign.

Mitigation:

- keep the external `/messages/trace` response shape stable where possible
- change internals first, then trim any redundant legacy fields deliberately

## Recommendation

Implement this as a dedicated `RuntimeTraceStore` backed by `runtime_trace.db`, and remove execution-trace storage from the L1 memory schema entirely.

This is the cleanest architecture because it restores the intended ownership boundary:

- memory owns durable facts
- runtime trace owns execution observability

That separation fixes the current trace breakage and prevents future schema collisions between retrieval-oriented memory data and structured runtime telemetry.
