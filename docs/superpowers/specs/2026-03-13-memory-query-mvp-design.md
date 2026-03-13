# Memory Query MVP Design

## Overview

This document defines the MVP redesign for memory retrieval in chat.

The goal is to let the chat model decide whether memory retrieval is needed during a conversation and, when needed, call `memory_query` as a normal tool. The detailed understanding of the retrieval request must live in `MemoryQueryService`, not in the fast routing model used by `ContextDecider`.

This design supersedes the older content-type-centric memory query design for the MVP path.

## Goals

- Enable memory retrieval during chat through normal tool calling
- Keep `ContextDecider` lightweight and focused on tool routing
- Query `UnifiedMemoryStore` event memory only for the MVP
- Support sensor-driven event sources such as Chrome history, git activity, chat, and terminal history
- Make retrieval understand layer, time window, source filters, and topic intent from the user query

## Non-Goals

- Do not inject retrieved memory into the system prompt before tool calling
- Do not include `SelfMemory` or `OtherMemory` in this MVP
- Do not make `ContextDecider` generate a detailed memory retrieval plan
- Do not require every layer handler to be implemented in the first iteration

## Design Principles

- `ContextDecider` should answer "Should memory retrieval be available for this turn?"
- `MemoryQueryService` should answer "What exactly should be queried and how?"
- Event memory should be queried using the existing `UnifiedMemoryStore` structure instead of a separate content-type abstraction
- Retrieval should prefer explicit, inspectable rules over hidden heuristics for source selection in the MVP

## Current Problem

The current code has two mismatched abstractions:

1. `UnifiedMemoryStore` stores event-centric memory in L1-L5 with fields such as `type`, `data`, `timestamp`, `source`, and `metadata`
2. `MemoryQueryService` currently assumes content-centric query types such as `browser_history`, `chat`, and `note`

This mismatch prevents `memory_query` from becoming the normal event-memory retrieval path for chat.

There is also a runtime gap:

- `ContextDecider` can suggest memory retrieval, but the main decision flow does not reliably route turns into `memory_query`
- `MemoryQueryTool` instantiates `MemoryQueryService` without real `UnifiedMemoryStore`-backed handlers

## MVP Architecture

```text
User Message
  -> ChatTaskAgent
  -> ChatExecutionCoordinator
  -> ContextDecider.decide(...)
      -> decides whether memory_query should be an available tool
  -> FunctionCallingHandler
  -> LLM may call memory_query
  -> MemoryQueryTool
  -> MemoryQueryService
      -> builds RetrievalPlan from query + optional params
      -> executes UnifiedMemoryStore-backed handlers
  -> tool result returned to LLM
  -> final answer returned to user
```

## Responsibilities

### ContextDecider

Location:
- `backend/src/magi/tools/context_decider.py`

Responsibilities for this MVP:

- Continue using the existing fast LLM plus fallback rules to decide tool routing
- Decide whether `memory_query` should be available for the current turn
- Do not generate a detailed retrieval object or retrieval parameters

`ContextDecider` may still use `evaluate_memory_need(...)`, but only as a lightweight routing helper or fallback. It should return a yes/no style recommendation for exposing `memory_query`, not a full retrieval plan.

### MemoryQueryTool

Location:
- `backend/src/magi/tools/memory_query.py`

Responsibilities for this MVP:

- Expose a tool interface that the main LLM can call
- Accept broad, partially specified inputs
- Build a real `MemoryQueryService` wired to runtime `UnifiedMemoryStore`
- Return retrieval results in an LLM-friendly structure

Tool inputs should remain permissive:

- `query` required
- `time_range` optional
- `sources` optional
- `query_mode` optional
- `limit` optional

The tool description should clearly tell the LLM:

- use this tool for questions about past activity or historical behavior
- pass time range when the user states one
- pass explicit sources if the user names them
- pass only `query` if uncertain; the service will infer the rest

### MemoryQueryService

Location:
- `backend/src/magi/memory/query/service.py`

Responsibilities for this MVP:

- Perform detailed retrieval understanding
- Convert the user request into a `RetrievalPlan`
- Execute layer handlers
- Merge, sort, and normalize results

This is the main intelligence boundary for memory retrieval. The detailed understanding must live here rather than in `ContextDecider`.

### UnifiedMemoryStore

Location:
- `backend/src/magi/memory/__init__.py`

Responsibilities for this MVP:

- Continue to serve as the unified event-memory storage backend
- Provide the L1 event data queried by the new retrieval handler

No major storage redesign is required in this MVP.

## Retrieval Model

The old model of querying by `data_types` such as `browser_history`, `chat`, and `note` is not the primary abstraction anymore.

The MVP retrieval model is event-centric.

### RetrievalPlan

`MemoryQueryService` should produce a `RetrievalPlan` with at least:

- `layers: list[str]`
- `query_mode: str`
- `source_filters: list[str]`
- `time_range: dict[str, Any]`
- `topic_query: str`
- `confidence: float`
- `reasoning: str`

Example:

```json
{
  "layers": ["L1"],
  "query_mode": "detail",
  "source_filters": ["chrome_history", "git", "chat", "terminal"],
  "time_range": {
    "relative": "1d",
    "calendar_hint": "yesterday"
  },
  "topic_query": "programming",
  "confidence": 0.87,
  "reasoning": "The user wants a detailed review of yesterday's programming-related activities."
}
```

### Why `layers` Must Be an Array

Even though the MVP mainly executes L1 detail queries, the retrieval model should support multi-layer aggregation from the start.

Examples:

- Detailed recall: `["L1"]`
- Recent review with summary: `["L1", "L4"]`
- Similar past solutions: `["L1", "L5"]`

This keeps the data model aligned with future retrieval expansion without forcing full implementation now.

## Query Understanding Rules

The MVP should infer retrieval structure inside `MemoryQueryService`.

### Query Mode

Suggested initial values:

- `detail`
- `summary`
- `experience`

Examples:

- "what did I do yesterday" -> `detail`
- "summarize what I was doing last week" -> `summary`
- "how did I solve this kind of issue before" -> `experience`

### Time Range

The service should infer time range from the query when not passed explicitly.

Initial examples:

- `yesterday` / `昨天` -> `{"relative": "1d", "calendar_hint": "yesterday"}`
- `last week` / `上周` -> `{"relative": "7d"}`
- `last month` / `上个月` -> `{"relative": "30d"}`
- `recently` / `最近` -> default `{"relative": "7d"}`

### Source Filters

Source filters should be inferred by explicit rules, not by a hidden model.

Initial explicit source rules:

- browser/web/search/docs -> `chrome_history`
- git/commit/branch/repo/pr -> `git`
- terminal/command/shell/bash/script -> `terminal`
- chat/said/discussed/talked -> `chat`

Initial topic-driven source defaults:

- programming/coding/development/bug/repo/implementation
  -> `git`, `terminal`, `chrome_history`, `chat`
- research/study/learning/docs
  -> `chrome_history`, `chat`, `terminal`

If both explicit and topic-driven sources match, merge and deduplicate them.

### Topic Query

The service should extract a topic-oriented query string for downstream filtering.

Examples:

- "programming-related things"
- "job search"
- "OpenAI docs research"

For the MVP, this can be a normalized string rather than a complex taxonomy.

## L1 Event Query Handler

New component:

- `backend/src/magi/memory/query/l1_handler.py`

Responsibilities:

1. Filter by time range
2. Filter by source
3. Extract searchable text from event fields
4. Score and sort by topic relevance and recency
5. Return normalized event snippets

### Searchable Text Extraction

The handler should derive searchable text from:

- event `type`
- event `source`
- text-like fields inside `data`
- text-like fields inside `metadata`

This allows heterogeneous sensors to participate without forcing one rigid payload schema in the MVP.

### Output Shape

The handler should not return raw event rows directly.

Each result should look like:

- `event_id`
- `timestamp`
- `source`
- `event_type`
- `summary`
- `details`
- `raw_ref`

Examples:

- git: "Committed changes to memory query routing"
- terminal: "Ran pytest for memory query tests"
- chrome_history: "Visited SQLite embedding docs related to retrieval design"
- chat: "Discussed chat-time memory retrieval design"

This keeps results compact and easier for the model to synthesize into a final answer.

## Tool-Routing Strategy

`ContextDecider.decide(...)` should remain the only routing decision entrypoint.

For this MVP:

- it should continue using the existing fast-model routing path
- it should decide whether `memory_query` belongs in `tools`
- it should not generate `layers`, `source_filters`, `topic_query`, or any detailed retrieval object

This keeps the fast model responsible only for routing, which matches its role and avoids pushing nuanced memory understanding into the wrong layer.

## API and Contract Changes

### Keep Broad Tool Inputs

The external tool contract should remain broad:

- the model may pass only `query`
- optional fields are hints, not strict requirements
- `MemoryQueryService` is responsible for filling the gaps

### Evolve Internal Query Models

The internal query models should be updated to support event-centric retrieval.

Recommended changes:

- keep `MemoryQueryRequest`
- add `sources` as a first-class field
- add `query_mode` as a first-class field
- add `RetrievalPlan`
- treat old `data_types` as compatibility-only input during migration

## Testing Strategy

Minimum validation for the MVP:

1. `ContextDecider` exposes `memory_query` for historical activity questions
2. `MemoryQueryService` infers L1 detail retrieval for "what did I do yesterday" style queries
3. Source rules infer `chrome_history`, `git`, `chat`, and `terminal` for programming-related activity review
4. `memory_query` returns non-empty normalized event results from `UnifiedMemoryStore`
5. A function-calling chat flow can call `memory_query` and produce a grounded final answer

## Risks

- Existing event payloads may not have enough consistent text fields for good topic matching
- Source naming may vary by plugin or sensor and need normalization
- The old `data_types` model may conflict with new event-centric rules during migration

## Follow-Up After MVP

- Add L4 summary handler
- Add L5 capability handler
- Add source normalization utilities for sensors/plugins
- Add optional prefetch/injection into prompt context after the tool path is stable
