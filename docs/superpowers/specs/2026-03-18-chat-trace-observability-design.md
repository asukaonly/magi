# Chat Trace Observability Design

## Goal

Redesign chat execution tracing so one turn can show a complete, ordered execution chain with millisecond timing, explicit success or failure state, retry history, and node-specific input or output details.

The new trace model should cover direct chat execution, function-calling loops, orchestration launches, worker execution, and LLM calls with one consistent node contract.

## Problem

The current chat trace is assembled from a narrow set of runtime events and is heavily biased toward tool usage.

Current gaps:

- no meaningful trace is visible when a turn does not call tools
- the UI tree is reconstructed from partial events instead of persisted execution nodes
- LLM activity is mostly invisible in the trace
- intent resolution is not represented as a first-class node
- retry behavior is flattened into final outcomes
- trace completion is inferred from `AIResponse` instead of explicit execution-state events
- timing is stored and summarized in second-based fields rather than millisecond-oriented metrics

This makes the current trace useful for a tool chain demo, but not for full-path observability or performance analysis.

## Design Principles

### Principle 1: Trace every major execution stage

The trace must represent the full user-facing execution path:

- turn start
- intent resolution
- main LLM call
- function-calling loop rounds
- tool execution
- orchestration launch
- worker dispatch
- worker LLM calls
- final response emission

### Principle 2: Persist execution nodes, not just raw side events

Read-side services should not guess structure from unrelated event types where avoidable.

Each traceable stage should emit normalized runtime span records with:

- identity
- hierarchy
- timing
- status
- retry metadata
- compact node-specific payload

### Principle 3: Keep chat transcript and execution trace separate

`fact_events` remains the source of truth for user-visible chat messages such as `UserMessage` and `AIResponse`.

`runtime_observations` becomes the source of truth for execution tracing.

Trace status and timing must not depend on `AIResponse` except as a legacy fallback during migration.

### Principle 4: Millisecond semantics are mandatory

Every trace node must expose:

- `started_at_ms`
- `ended_at_ms`
- `duration_ms`

Display-level duration and performance analytics must use millisecond values.

### Principle 5: Retries are observable, not summarized away

A retried node must preserve both:

- logical retry counters on the parent node
- per-attempt child nodes when multiple attempts occurred

This allows the UI to show both final state and attempt-by-attempt history.

## Scope

Included:

- new runtime trace node model
- new event taxonomy for chat execution observability
- LLM call metrics for main chat and worker execution
- retry modeling
- explicit turn execution boundaries
- read-side changes for trace snapshots and summaries
- frontend contract changes required by the richer trace data

Excluded:

- historical backfill for old trace data
- OpenTelemetry export
- non-chat runtime flows outside `ChatTaskAgent`, `TaskOrchestrator`, and workers
- redesign of unrelated chat page layout

## Target Model

### Canonical trace node contract

Every persisted runtime trace node should conform to this logical model:

```json
{
  "trace_id": "trace_turn_xxx",
  "turn_id": "turn_xxx",
  "span_id": "span_xxx",
  "parent_span_id": "span_parent",
  "node_type": "llm_call",
  "name": "Main response generation",
  "status": "completed",
  "attempt_index": 1,
  "retry_count": 0,
  "started_at_ms": 1710751000123,
  "ended_at_ms": 1710751001456,
  "duration_ms": 1333,
  "input": {},
  "output": {},
  "metrics": {},
  "error": null,
  "tags": {
    "user_id": "web_user",
    "session_id": "session_xxx",
    "orchestration_id": null,
    "worker_id": null
  }
}
```

### Required common fields

- `trace_id`
  Stable identifier for the turn-level trace tree

- `turn_id`
  Required correlation key for one user turn

- `span_id`
  Unique identifier for this node

- `parent_span_id`
  Allows tree reconstruction without read-side guessing

- `node_type`
  One of the normalized execution node types

- `name`
  Human-readable label for the UI

- `status`
  `running`, `completed`, or `failed`

- `attempt_index`
  One-based attempt number for retried nodes

- `retry_count`
  Number of retries attempted by the logical node

- `started_at_ms`, `ended_at_ms`, `duration_ms`
  Millisecond timestamps and computed duration

- `input`, `output`, `metrics`
  Node-specific structured payloads

- `error`
  Compact failure payload for failed nodes

## Node Taxonomy

The first version should support these node types:

- `turn`
- `intent_resolution`
- `llm_call`
- `tool_loop`
- `tool_call`
- `orchestration`
- `worker_dispatch`
- `worker`
- `response_emit`
- `retry_attempt`

### `turn`

Root node for one user turn.

Input:

- `user_message_preview`
- `source`

Output:

- optional final response preview

### `intent_resolution`

Represents the route and intent decision for the turn.

Input:

- omitted by design to reduce duplication

Output:

- `intent`
- `execution_mode`
- `route_reason`
- `selected_tools`
- `selected_worker_type`

### `llm_call`

Used for both main chat LLM calls and worker LLM calls.

Input:

- prompt or message summary only
- optional tool availability summary

Output:

- finish reason
- tool call summary
- response preview

Metrics:

- `provider`
- `model`
- `input_tokens`
- `output_tokens`
- `reasoning_tokens`
- `cache_read_tokens`
- `cache_write_tokens`
- `thinking_enabled`
- `duration_ms`

Tags:

- `role`: `main` or `worker`
- `worker_id` when applicable

### `tool_loop`

Represents one function-calling round.

Output:

- `iteration`
- `tool_count`
- `tool_names`

### `tool_call`

Represents one tool invocation.

Input:

- normalized arguments

Output:

- result preview
- structured result summary when available

Metrics:

- `execution_time_ms`

### `orchestration`

Represents parent orchestration setup and aggregation.

Output:

- `planner`
- `subtask_count`
- `allow_parallel`

### `worker_dispatch`

Represents one worker launch request from the parent orchestration.

Output:

- `worker_id`
- `subtask_id`
- `subagent_type`

### `worker`

Represents one worker lifecycle.

Output:

- `worker_id`
- `subtask_id`
- `summary`

### `response_emit`

Represents final assistant response publication to the chat channel.

Output:

- `response_preview`
- `response_chars`

### `retry_attempt`

Represents an individual attempt under a retried logical node.

This node is optional when a logical node never retries, but required when retries happen.

## Event Taxonomy

The runtime should emit normalized trace events into `runtime_observations`.

Suggested first-class event types:

- `TURN_TRACE_STARTED`
- `TURN_TRACE_COMPLETED`
- `TURN_TRACE_FAILED`
- `TRACE_NODE_STARTED`
- `TRACE_NODE_COMPLETED`
- `TRACE_NODE_FAILED`

The event payload should always include:

- `trace_id`
- `turn_id`
- `span_id`
- `parent_span_id`
- `node_type`
- `name`
- `attempt_index`
- `retry_count`
- `started_at_ms`
- `ended_at_ms`
- `duration_ms`
- `status`
- `input`
- `output`
- `metrics`
- `error`
- `user_id`
- `session_id`

Existing event types such as `CHAT_TOOL_LOOP_STEP`, `TOOL_INTERACTION`, and worker progress events may continue to exist during implementation, but the read side should converge on the normalized trace-node events as the primary source of truth.

## Timing Semantics

### Wall clock

Use wall-clock milliseconds for persisted timestamps:

- `started_at_ms`
- `ended_at_ms`

### Duration clock

Use monotonic clock deltas to compute `duration_ms`.

This avoids negative or skewed durations when system time changes.

### Display contract

The frontend should not infer duration from raw timestamps when `duration_ms` is already present.

## Retry Semantics

Retry-aware nodes should follow these rules:

- the logical node keeps final `status` and total `retry_count`
- each attempt is represented as a child `retry_attempt` node when attempts > 1
- each attempt node has its own timing and error data
- final success after retries must remain visible as `completed` on the logical node

Example:

```text
Tool call: web_fetch (completed, retries=2)
├── Attempt 1 (failed, timeout)
├── Attempt 2 (failed, 500)
└── Attempt 3 (completed)
```

## `fact_events` And `runtime_observations` Responsibilities

### `fact_events`

`fact_events` keeps transcript and product-facing message content:

- `UserMessage`
- `AIResponse`

It should continue to power:

- chat history
- chat session titles
- transcript rendering

It should not be the primary source of:

- trace timing
- trace final state
- trace hierarchy

### `runtime_observations`

`runtime_observations` becomes the canonical trace store for execution observability:

- root turn lifecycle
- intent resolution
- LLM calls
- orchestration and worker dispatch
- tool loops and tool calls
- final response emission
- retry attempts

### Turn correlation rule

`turn_id` remains the primary correlation key shared by transcript events and trace events.

`AIResponse` no longer defines trace completion. Instead:

- `TURN_TRACE_COMPLETED` defines successful end of execution
- `TURN_TRACE_FAILED` defines terminal failure
- `AIResponse` only records the emitted user-visible assistant message

## Read-Side Architecture

`ChatTraceReadService` should be refactored from event guessing to node assembly:

1. load normalized trace-node events for one `turn_id`
2. reconstruct nodes by `span_id`
3. attach children by `parent_span_id`
4. compute rollups from explicit node states
5. use `TURN_TRACE_*` events for root status
6. expose summary and snapshot directly from normalized nodes

### Summary contract

The compact summary should include:

- `turn_id`
- `status`
- `headline`
- `duration_ms`
- `active_steps`
- `completed_steps`
- `failed_steps`
- `retry_count`
- `trace_available`

`duration_seconds` should be removed from the steady-state contract and replaced by `duration_ms`.

### Snapshot contract

Each UI node should expose:

- `id`
- `kind`
- `label`
- `status`
- `started_at_ms`
- `ended_at_ms`
- `duration_ms`
- `attempt_index`
- `retry_count`
- `input`
- `output`
- `metrics`
- `error`
- `children`

## Frontend Expectations

The chat page and toolchain drawer should evolve from a tool-centric view to a full execution-trace drawer.

The UI should be able to show:

- node label and type
- success or failure state
- exact duration in milliseconds
- retry badge
- compact input or output blocks where available
- token metrics for LLM nodes

LLM-specific rows should show at least:

- model
- input tokens
- output tokens
- reasoning tokens when present
- whether deeper reasoning was enabled

## Write-Side Integration Points

### Chat runtime

Instrument:

- intent classification
- main LLM call
- function-calling loop rounds
- tool calls
- final response emission

### Orchestration runtime

Instrument:

- orchestration start
- worker dispatch
- aggregation

### Worker runtime

Instrument:

- worker lifecycle root
- worker LLM calls
- worker tool calls

### LLM service boundary

Centralize LLM trace capture close to the provider bridge or shared LLM execution service so both main chat and workers report the same metric schema.

## Migration Rules

This change should be treated as clean-slate for trace semantics.

Rules:

- do not add long-lived compatibility branches in the read side
- allow legacy data to render best-effort during the transition if cheap
- make the normalized trace-node events the only steady-state contract

## Validation

Required verification areas:

- direct LLM turn with no tools still produces a non-empty trace
- function-calling turn shows intent, LLM, loop, and tool nodes
- orchestration turn shows parent orchestration, dispatch, worker, and worker LLM nodes
- failed turns emit terminal failure without relying on missing `AIResponse`
- retrying nodes show attempt history
- duration fields are millisecond-based across backend and frontend contracts
- chat transcript remains correct and independent from trace state

## Recommended Delivery Order

1. introduce normalized trace-node events and millisecond timing helpers
2. instrument chat runtime intent and LLM calls
3. instrument orchestration and worker execution
4. refactor `ChatTraceReadService` to consume normalized nodes
5. update frontend types and rendering for richer trace data
6. remove old summary fields and old trace assumptions
