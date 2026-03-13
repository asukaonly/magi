# Memory Query MVP Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat-time memory retrieval work as a normal tool flow where `ContextDecider` exposes `memory_query` for historical questions and `MemoryQueryService` queries `UnifiedMemoryStore` event memory, with MVP execution focused on L1 detail retrieval.

**Architecture:** Keep `ContextDecider` lightweight so it only decides whether `memory_query` should be available. Move detailed retrieval understanding into `MemoryQueryService`, which builds an event-centric `RetrievalPlan`, infers source filters and time range, and runs a real `UnifiedMemoryStore`-backed L1 query handler. Return normalized event snippets to the main LLM through the existing function-calling loop.

**Tech Stack:** Python 3.10+, asyncio, aiosqlite, FastAPI runtime wiring, dataclasses, existing task-agent/function-calling runtime

---

## File Structure

```text
backend/src/magi/
├── memory/
│   └── query/
│       ├── models.py                 # Expand request/result models and add RetrievalPlan
│       ├── router.py                 # Replace old layer-only routing with event-centric plan building
│       ├── service.py                # Build retrieval plan, execute handlers, merge results
│       ├── handlers.py               # Keep shared handler registry utilities if still needed
│       ├── l1_handler.py             # NEW: UnifiedMemoryStore-backed L1 event query handler
│       └── __init__.py               # Export new models/handler/service contracts
├── tools/
│   ├── memory_query.py              # Wire tool to runtime UnifiedMemoryStore and new request fields
│   └── context_decider.py           # Decide whether memory_query should be available
└── agent/task_agents/chat/
    └── coordinator.py               # Consume updated ContextDecision tools as usual

backend/tests/
├── memory/test_memory_query.py       # Expand unit coverage for RetrievalPlan and L1 querying
└── test_context_decider_memory.py    # Update routing tests around memory_query exposure
```

---

## Chunk 1: Event-Centric Query Contracts

### Task 1: Add RetrievalPlan and broaden MemoryQueryRequest

**Files:**
- Modify: `backend/src/magi/memory/query/models.py`
- Modify: `backend/src/magi/memory/query/__init__.py`
- Test: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write failing tests for the new retrieval contract**

Add tests that assert:
- `MemoryQueryRequest` accepts `sources` and `query_mode`
- `RetrievalPlan` stores `layers` as an ordered list
- `MemoryQueryResult.query_meta` can expose `layers`, `query_mode`, and `source_filters`

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "RetrievalPlan or MemoryQueryRequest" -v`
Expected: FAIL because `RetrievalPlan`, `sources`, and `query_mode` do not exist yet

- [ ] **Step 3: Implement the minimal model changes**

Update `models.py` to:
- add `sources: Optional[List[str]] = None`
- add `query_mode: Optional[str] = None`
- keep `data_types` as compatibility-only input for now
- add a new `RetrievalPlan` dataclass with:
  - `layers: List[str]`
  - `query_mode: str`
  - `source_filters: List[str]`
  - `time_range: Dict[str, Any]`
  - `topic_query: str`
  - `confidence: float`
  - `reasoning: str`

- [ ] **Step 4: Export the new contract from `__init__.py`**

- [ ] **Step 5: Re-run the focused tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "RetrievalPlan or MemoryQueryRequest" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/query/models.py backend/src/magi/memory/query/__init__.py backend/tests/memory/test_memory_query.py
git commit -m "feat: add event-centric memory query models"
```

---

## Chunk 2: Retrieval Plan Inference

### Task 2: Replace layer-only routing with event-centric plan building

**Files:**
- Modify: `backend/src/magi/memory/query/router.py`
- Modify: `backend/src/magi/memory/query/service.py`
- Test: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write failing tests for retrieval plan inference**

Add tests for:
- `"What did I do yesterday?"` -> `layers == ["L1"]`, `query_mode == "detail"`
- `"Analyze what programming-related things I did yesterday"` -> inferred sources contain `git`, `terminal`, `chrome_history`, `chat`
- `"Summarize what I was doing last week"` -> `query_mode == "summary"` and `layers` includes `L1`

- [ ] **Step 2: Run those tests and confirm they fail**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "routing or retrieval plan" -v`
Expected: FAIL because router still returns `primary_layer`/`secondary_layers`

- [ ] **Step 3: Implement `RetrievalPlan` inference in `router.py`**

Refactor the router to:
- output `layers` instead of `primary_layer` + `secondary_layers`
- infer `query_mode`
- infer `source_filters` from explicit source keywords
- add topic-driven default source sets
- infer `time_range` only when the request did not already provide one
- keep the implementation rule-based and inspectable

- [ ] **Step 4: Update `MemoryQueryService` to use `RetrievalPlan`**

Change `service.py` so it:
- builds or refines a `RetrievalPlan`
- passes the plan to downstream handlers
- updates `query_meta` to expose `layers`, `query_mode`, `source_filters`, and confidence

- [ ] **Step 5: Re-run the focused tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "routing or retrieval plan" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/query/router.py backend/src/magi/memory/query/service.py backend/tests/memory/test_memory_query.py
git commit -m "feat: infer event memory retrieval plans"
```

---

## Chunk 3: UnifiedMemoryStore-Backed L1 Querying

### Task 3: Implement `L1EventQueryHandler`

**Files:**
- Create: `backend/src/magi/memory/query/l1_handler.py`
- Modify: `backend/src/magi/memory/query/service.py`
- Test: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write failing unit tests for L1 event filtering**

Add tests covering:
- time-range filtering over L1 events
- source filtering over L1 events
- topic matching using text from `type`, `source`, `data`, and `metadata`
- normalized output shape with `event_id`, `timestamp`, `source`, `event_type`, `summary`, `details`, and `raw_ref`

- [ ] **Step 2: Run those tests and confirm they fail**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "L1EventQueryHandler or normalized output" -v`
Expected: FAIL because the handler does not exist

- [ ] **Step 3: Implement the handler**

Create `l1_handler.py` with:
- a constructor that accepts `UnifiedMemoryStore`
- a `query(request, plan)`-style method compatible with service execution
- time filtering over `l1_raw`
- source filtering using `plan.source_filters`
- searchable text extraction from event row fields
- relevance sorting by topic match plus recency
- normalized event snippet rendering

- [ ] **Step 4: Wire the handler into `MemoryQueryService`**

Allow `MemoryQueryService` to receive concrete layer handlers and call the new L1 handler whenever `L1` appears in `plan.layers`.

- [ ] **Step 5: Re-run the focused tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "L1EventQueryHandler or normalized output" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/query/l1_handler.py backend/src/magi/memory/query/service.py backend/tests/memory/test_memory_query.py
git commit -m "feat: add L1 event memory query handler"
```

---

## Chunk 4: Tool Wiring to Runtime Memory

### Task 4: Wire `memory_query` to runtime `UnifiedMemoryStore`

**Files:**
- Modify: `backend/src/magi/tools/memory_query.py`
- Modify: `backend/src/magi/memory/query/service.py`
- Test: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write failing tests for tool construction and permissive inputs**

Add tests that assert:
- the tool can execute with only `query`
- `sources` and `query_mode` are accepted optional inputs
- the service is built with a real `UnifiedMemoryStore`-backed L1 handler

- [ ] **Step 2: Run those tests and confirm they fail**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "memory_query tool" -v`
Expected: FAIL because the tool still requires old parameters and instantiates a bare service

- [ ] **Step 3: Update tool schema and runtime wiring**

Modify `memory_query.py` to:
- make `time_range` optional
- replace `data_types` with `sources` in the main schema while optionally tolerating old input during migration
- describe the tool as a historical event-memory tool
- get `UnifiedMemoryStore` from runtime/bootstrap accessors
- build `MemoryQueryService` with `L1EventQueryHandler`

- [ ] **Step 4: Re-run the focused tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py -k "memory_query tool" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/tools/memory_query.py backend/src/magi/memory/query/service.py backend/tests/memory/test_memory_query.py
git commit -m "feat: wire memory query tool to unified memory"
```

---

## Chunk 5: Chat-Time Tool Exposure

### Task 5: Make `ContextDecider` expose `memory_query` for historical questions

**Files:**
- Modify: `backend/src/magi/tools/context_decider.py`
- Modify: `backend/tests/test_context_decider_memory.py`
- Optional verify read-only behavior in: `backend/src/magi/agent/task_agents/chat/coordinator.py`

- [ ] **Step 1: Write failing tests for memory tool exposure**

Update `test_context_decider_memory.py` so it asserts:
- historical questions expose `memory_query`
- non-historical questions still do not
- `evaluate_memory_need(...)` only needs to answer whether the tool should be suggested, not generate a full retrieval plan

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `cd backend && pytest tests/test_context_decider_memory.py -v`
Expected: FAIL because the tests no longer match the old guidance shape

- [ ] **Step 3: Simplify `evaluate_memory_need(...)`**

Refactor it so it:
- returns a yes/no style memory guidance
- keeps the implementation lightweight
- does not generate full memory query parameters

- [ ] **Step 4: Merge memory guidance into `decide(...)`**

Update `decide(...)` so that after the normal fast-model route decision:
- if memory guidance says memory retrieval is useful
- and `memory_query` is available
- append `memory_query` to `decision.tools` if not already present

- [ ] **Step 5: Re-run the focused tests**

Run: `cd backend && pytest tests/test_context_decider_memory.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/tools/context_decider.py backend/tests/test_context_decider_memory.py
git commit -m "feat: expose memory query for historical turns"
```

---

## Chunk 6: End-to-End Validation

### Task 6: Add service-level and integration-style validation

**Files:**
- Modify: `backend/tests/memory/test_memory_query.py`
- Optional add: `backend/tests/test_memory_query_chat_integration.py`

- [ ] **Step 1: Add end-to-end style tests**

Cover:
- a programming-related "what did I do yesterday" query
- source inference to `git`, `terminal`, `chrome_history`, and `chat`
- L1 handler returning grounded event snippets
- empty-result behavior when nothing matches

- [ ] **Step 2: Run targeted memory query tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py -v`
Expected: PASS

- [ ] **Step 3: Run context decider tests**

Run: `cd backend && pytest tests/test_context_decider_memory.py -v`
Expected: PASS

- [ ] **Step 4: Run a broader backend smoke suite**

Run: `cd backend && pytest tests/memory/test_memory_query.py tests/test_context_decider_memory.py tests/test_memory_layers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/memory/test_memory_query.py backend/tests/test_context_decider_memory.py
git commit -m "test: cover chat memory query MVP flow"
```

---

## Notes for Execution

- Follow the current runtime architecture in `docs/task-agent-runtime-architecture.md`; do not bypass the existing function-calling path
- Preserve backward compatibility only where needed for a safe migration from `data_types` to event-centric query inputs, then remove unused compatibility code in a follow-up task
- Prefer small commits after each completed task, as required by the repository handbook

Plan complete and saved to `docs/superpowers/plans/2026-03-13-memory-query-mvp.md`. Ready to execute?
