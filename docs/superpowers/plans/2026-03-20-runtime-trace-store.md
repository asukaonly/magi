# Runtime Trace Store Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move chat execution tracing into a dedicated runtime trace store and remove trace persistence from the L1 memory schema.

**Architecture:** The implementation introduces a separate `runtime_trace.db` with turn, span, and node-detail tables; routes chat trace writes through a dedicated backend store; rebuilds chat trace snapshots from canonical span records; and removes trace writes plus read-side fallback from `runtime_observations`. L1 remains the durable memory fact store and stops owning execution observability.

**Tech Stack:** Python 3.10+, SQLite, FastAPI, React 18, TypeScript, pytest, Vitest

---

## File Map

### Runtime trace store

- Create: `backend/src/magi/runtime_trace/contracts.py`
  Typed write models and read models for trace turns, spans, LLM details, tool details, and intent details.

- Create: `backend/src/magi/runtime_trace/store.py`
  SQLite-backed runtime trace store with schema creation and write/read APIs.

- Create: `backend/src/magi/runtime_trace/__init__.py`
  Shared runtime-trace service construction helpers.

### Bootstrap and runtime paths

- Modify: `backend/src/magi/utils/runtime.py`
  Add a canonical path for `runtime_trace.db`.

- Modify: `backend/src/magi/bootstrap/context.py`
  Add runtime-trace service ownership in bootstrap context.

- Modify: `backend/src/magi/bootstrap/builder.py`
  Wire runtime-trace lifecycle at bootstrap time.

- Modify: `backend/src/magi/bootstrap/exports.py`
  Export the runtime-trace store to DI/runtime bindings.

### Write-side instrumentation

- Modify: `backend/src/magi/agent/task_agents/chat/postprocess_service.py`
  Replace runtime trace event writes with direct runtime-trace store writes.

- Modify: `backend/src/magi/agent/task_agents/chat/coordinator.py`
  Persist intent resolution through the runtime-trace store.

- Modify: `backend/src/magi/agent/execution/function_calling.py`
  Persist iteration, LLM call, and tool-call spans directly.

- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
  Surface trace metrics in a writer-friendly typed shape if needed.

- Modify: `backend/src/magi/agent/workers/worker_manager.py`
  Route worker lifecycle spans into the same runtime-trace store.

### Read side and transport

- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
  Read from `runtime_trace.db` only and remove `runtime_observations` fallback reconstruction.

- Modify: `backend/src/magi/api/services/chat_read_service.py`
  Keep transcript and trace-summary linkage stable after the storage split.

- Modify: `backend/src/magi/api/routers/messages.py`
  Keep `/messages/trace` served from the new runtime trace store.

- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
  Preserve live trace-summary broadcasts if they currently depend on old storage assumptions.

### L1 memory cleanup

- Modify: `backend/src/magi/memory/event_contracts.py`
  Stop classifying trace runtime events as L1-storable memory events.

- Modify: `backend/src/magi/memory/l1/event_store.py`
  Remove `runtime_observations` schema creation, queries, and counters.

- Modify: `backend/src/magi/memory/integration.py`
  Stop routing trace-only runtime events into unified memory ingestion.

- Modify: `backend/src/magi/agent/task_agents/chat/session_service.py`
  Remove any dependence on `runtime_observations` for transcript or trace state.

### Frontend and tests

- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/types/websocket.ts`
- Modify: `frontend/src/domain/chat/normalizers.ts`
- Modify: `frontend/src/components/chat/ToolchainDrawer.tsx`
- Modify: `frontend/src/__tests__/chatTraceState.test.ts`
- Modify: `frontend/src/__tests__/toolchainDrawer.test.tsx`
- Modify: `frontend/src/__tests__/realtimeProvider.test.tsx`

### Documentation

- Modify: `docs/project-overview.md`
  Update persistence boundaries to include `runtime_trace.db` and remove trace ownership from L1.

- Modify: `docs/task-agent-runtime-architecture.md`
  Update runtime flow wording so trace observability is owned by the runtime trace store rather than `runtime_observations`.

## Chunk 1: Runtime Trace Store Skeleton

### Task 1: Add runtime trace paths, contracts, and schema

**Files:**
- Create: `backend/src/magi/runtime_trace/contracts.py`
- Create: `backend/src/magi/runtime_trace/store.py`
- Create: `backend/src/magi/runtime_trace/__init__.py`
- Modify: `backend/src/magi/utils/runtime.py`
- Test: `backend/tests/runtime_trace/test_store.py`

- [ ] **Step 1: Write the failing store tests**

```python
async def test_runtime_trace_store_creates_turn_and_span_tables(tmp_path: Path) -> None:
    store = RuntimeTraceStore(db_path=str(tmp_path / "runtime_trace.db"))
    await store.initialize()

    tables = await list_sqlite_tables(store.db_path)
    assert "trace_turns" in tables
    assert "trace_spans" in tables
    assert "trace_llm_calls" in tables
```

- [ ] **Step 2: Run the new runtime trace store tests**

Run: `cd backend && pytest tests/runtime_trace/test_store.py -q`
Expected: FAIL because the runtime trace package and schema do not exist yet

- [ ] **Step 3: Implement the runtime trace contracts and SQLite schema**

```python
@dataclass(slots=True)
class TraceSpanRecord:
    span_id: str
    trace_id: str
    turn_id: str
    parent_span_id: str | None
    node_type: str
    name: str
    status: str
```

- [ ] **Step 4: Re-run the runtime trace store tests**

Run: `cd backend && pytest tests/runtime_trace/test_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/runtime_trace backend/src/magi/utils/runtime.py backend/tests/runtime_trace/test_store.py
git commit -m "feat: add runtime trace store schema"
```

### Task 2: Wire runtime trace store into bootstrap

**Files:**
- Modify: `backend/src/magi/bootstrap/context.py`
- Modify: `backend/src/magi/bootstrap/builder.py`
- Modify: `backend/src/magi/bootstrap/exports.py`
- Test: `backend/tests/bootstrap/test_runtime_trace_bootstrap.py`

- [ ] **Step 1: Write the failing bootstrap test**

```python
def test_bootstrap_exports_runtime_trace_store() -> None:
    exports = build_runtime_exports_for_test()
    assert exports.runtime_trace_store is not None
```

- [ ] **Step 2: Run the bootstrap test**

Run: `cd backend && pytest tests/bootstrap/test_runtime_trace_bootstrap.py -q`
Expected: FAIL because bootstrap does not expose the runtime trace service yet

- [ ] **Step 3: Add runtime trace service ownership to bootstrap**

```python
context.runtime_trace.store = RuntimeTraceStore(db_path=runtime_paths.runtime_trace_db_path)
```

- [ ] **Step 4: Re-run the bootstrap test**

Run: `cd backend && pytest tests/bootstrap/test_runtime_trace_bootstrap.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/bootstrap/context.py backend/src/magi/bootstrap/builder.py backend/src/magi/bootstrap/exports.py backend/tests/bootstrap/test_runtime_trace_bootstrap.py
git commit -m "feat: wire runtime trace bootstrap service"
```

## Chunk 2: Write-Side Cutover

### Task 3: Persist turn and intent nodes through the runtime trace store

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat/postprocess_service.py`
- Modify: `backend/src/magi/agent/task_agents/chat/coordinator.py`
- Test: `backend/tests/agent/test_chat_postprocess_service.py`
- Test: `backend/tests/agent/test_chat_execution_coordinator.py`

- [ ] **Step 1: Write the failing tests for turn and intent persistence**

```python
async def test_record_intent_resolution_writes_trace_span(runtime_trace_store) -> None:
    await service.record_intent_resolution(context, decision)
    span = await runtime_trace_store.get_span(f"{turn_id}:intent_resolution")
    assert span.node_type == "intent_resolution"
```

- [ ] **Step 2: Run the targeted chat trace writer tests**

Run: `cd backend && pytest tests/agent/test_chat_postprocess_service.py tests/agent/test_chat_execution_coordinator.py -q`
Expected: FAIL because chat runtime still emits old runtime events instead of writing canonical trace rows

- [ ] **Step 3: Implement direct runtime trace writes for turn start, intent resolution, and response emission**

```python
await runtime_trace_store.complete_span(
    TraceSpanRecord(
        span_id=f"{turn_id}:intent_resolution",
        trace_id=f"trace:{turn_id}",
        turn_id=turn_id,
        parent_span_id=f"{turn_id}:turn",
        node_type="intent_resolution",
        name="Intent resolution",
        status="completed",
    ),
    intent=TraceIntentResolutionRecord(...),
)
```

- [ ] **Step 4: Re-run the targeted chat trace writer tests**

Run: `cd backend && pytest tests/agent/test_chat_postprocess_service.py tests/agent/test_chat_execution_coordinator.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/postprocess_service.py backend/src/magi/agent/task_agents/chat/coordinator.py backend/tests/agent/test_chat_postprocess_service.py backend/tests/agent/test_chat_execution_coordinator.py
git commit -m "refactor: persist chat trace turns directly"
```

### Task 4: Persist iteration, LLM, and tool spans directly

**Files:**
- Modify: `backend/src/magi/agent/execution/function_calling.py`
- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
- Modify: `backend/src/magi/agent/workers/worker_manager.py`
- Test: `backend/tests/agent/test_function_calling_trace_store.py`
- Test: `backend/tests/agent/test_worker_trace_store.py`

- [ ] **Step 1: Write the failing tests for iteration, LLM, and tool trace rows**

```python
async def test_function_calling_writes_llm_and_tool_rows(runtime_trace_store) -> None:
    await orchestrator.execute(...)
    llm_rows = await runtime_trace_store.list_llm_calls(turn_id=turn_id)
    tool_rows = await runtime_trace_store.list_tools(turn_id=turn_id)
    assert llm_rows[0].model == "glm-5"
    assert tool_rows[0].tool_name == "weather"
```

- [ ] **Step 2: Run the targeted execution trace tests**

Run: `cd backend && pytest tests/agent/test_function_calling_trace_store.py tests/agent/test_worker_trace_store.py -q`
Expected: FAIL because function-calling and worker execution still rely on runtime event emission only

- [ ] **Step 3: Implement direct persistence of iteration, LLM call, tool call, and worker spans**

```python
await runtime_trace_store.record_llm_call(
    span=TraceSpanRecord(..., node_type="llm_call"),
    details=TraceLlmCallRecord(provider="glm", model="glm-5", input_tokens=2125, output_tokens=22),
)
```

- [ ] **Step 4: Re-run the targeted execution trace tests**

Run: `cd backend && pytest tests/agent/test_function_calling_trace_store.py tests/agent/test_worker_trace_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/execution/function_calling.py backend/src/magi/agent/task_agents/common/llm_service.py backend/src/magi/agent/workers/worker_manager.py backend/tests/agent/test_function_calling_trace_store.py backend/tests/agent/test_worker_trace_store.py
git commit -m "refactor: write runtime trace spans directly"
```

## Chunk 3: Read-Side Cutover

### Task 5: Rebuild chat trace snapshots from runtime trace tables only

**Files:**
- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
- Test: `backend/tests/api/test_chat_trace_read_service.py`

- [ ] **Step 1: Write the failing snapshot test against canonical spans**

```python
def test_trace_reader_builds_tree_from_span_parent_links(runtime_trace_store) -> None:
    snapshot = service.get_trace_snapshot(user_id="web_user", session_id="session-1", turn_id="turn-1")
    assert snapshot["root"]["children"][0]["kind"] == "intent_resolution"
    assert snapshot["root"]["children"][1]["kind"] == "iteration"
```

- [ ] **Step 2: Run the targeted trace reader tests**

Run: `cd backend && pytest tests/api/test_chat_trace_read_service.py -q`
Expected: FAIL because the reader still loads events from `runtime_observations`

- [ ] **Step 3: Refactor the reader to load `trace_turns`, `trace_spans`, `trace_llm_calls`, `trace_tools`, and `trace_intent_resolutions`**

```python
turn = self._trace_store.get_turn(turn_id=turn_id, session_id=session_id, user_id=user_id)
spans = self._trace_store.list_spans(trace_id=turn.trace_id)
```

- [ ] **Step 4: Re-run the targeted trace reader tests**

Run: `cd backend && pytest tests/api/test_chat_trace_read_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/services/chat_trace_read_service.py backend/tests/api/test_chat_trace_read_service.py
git commit -m "refactor: read chat traces from runtime trace store"
```

### Task 6: Keep message APIs and websocket updates stable after the storage split

**Files:**
- Modify: `backend/src/magi/api/routers/messages.py`
- Modify: `backend/src/magi/api/services/chat_read_service.py`
- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
- Test: `backend/tests/api/test_messages_sessions.py`
- Test: `backend/tests/websocket/test_handlers.py`

- [ ] **Step 1: Write the failing transport tests**

```python
def test_messages_trace_endpoint_returns_runtime_trace_snapshot(client) -> None:
    payload = client.get("/messages/trace", params={...}).json()
    assert payload["trace"]["summary"]["trace_available"] is True
```

- [ ] **Step 2: Run the targeted API and websocket tests**

Run: `cd backend && pytest tests/api/test_messages_sessions.py tests/websocket/test_handlers.py -q`
Expected: FAIL if transport code still assumes the old L1-backed trace reader path

- [ ] **Step 3: Point transport consumers at the new reader and preserve the external DTO shape**

```python
trace = trace_read_service.get_trace_snapshot(...)
return {"trace": trace}
```

- [ ] **Step 4: Re-run the targeted API and websocket tests**

Run: `cd backend && pytest tests/api/test_messages_sessions.py tests/websocket/test_handlers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/messages.py backend/src/magi/api/services/chat_read_service.py backend/src/magi/websocket/bridge_lifecycle.py backend/tests/api/test_messages_sessions.py backend/tests/websocket/test_handlers.py
git commit -m "refactor: serve traces from runtime trace store"
```

## Chunk 4: Remove Trace Ownership From L1

### Task 7: Stop sending trace-only events into unified memory

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/l1/test_event_store.py`
- Test: `backend/tests/memory/test_memory_layers.py`

- [ ] **Step 1: Write the failing memory-ingestion tests**

```python
async def test_trace_node_events_are_not_normalized_into_l1() -> None:
    normalized = normalize_runtime_event(trace_event)
    assert normalized is None
```

- [ ] **Step 2: Run the targeted memory tests**

Run: `cd backend && pytest tests/memory/l1/test_event_store.py tests/memory/test_memory_layers.py -q`
Expected: FAIL because trace runtime events are still classified as L1-storable

- [ ] **Step 3: Remove trace-only event types from unified-memory ingestion**

```python
if event.type in TRACE_RUNTIME_EVENT_TYPES:
    return None
```

- [ ] **Step 4: Re-run the targeted memory tests**

Run: `cd backend && pytest tests/memory/l1/test_event_store.py tests/memory/test_memory_layers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/src/magi/memory/integration.py backend/tests/memory/l1/test_event_store.py backend/tests/memory/test_memory_layers.py
git commit -m "refactor: stop storing traces in l1"
```

### Task 8: Remove `runtime_observations` from the L1 schema and helpers

**Files:**
- Modify: `backend/src/magi/memory/l1/event_store.py`
- Modify: `backend/src/magi/agent/task_agents/chat/session_service.py`
- Test: `backend/tests/memory/l1/test_event_store.py`
- Test: `backend/tests/agent/test_chat_session_service.py`

- [ ] **Step 1: Write the failing L1 schema cleanup tests**

```python
async def test_l1_store_initializes_without_runtime_observations_table(tmp_path: Path) -> None:
    store = L1EventStore(db_path=str(tmp_path / "l1_events.db"))
    await store.initialize()
    assert "runtime_observations" not in await list_sqlite_tables(store.db_path)
```

- [ ] **Step 2: Run the targeted L1 and chat-session tests**

Run: `cd backend && pytest tests/memory/l1/test_event_store.py tests/agent/test_chat_session_service.py -q`
Expected: FAIL because the L1 schema and helpers still assume `runtime_observations`

- [ ] **Step 3: Remove the table, related helpers, and dependent chat-session paths**

```python
CREATE TABLE IF NOT EXISTS fact_events (...)
```

- [ ] **Step 4: Re-run the targeted L1 and chat-session tests**

Run: `cd backend && pytest tests/memory/l1/test_event_store.py tests/agent/test_chat_session_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l1/event_store.py backend/src/magi/agent/task_agents/chat/session_service.py backend/tests/memory/l1/test_event_store.py backend/tests/agent/test_chat_session_service.py
git commit -m "refactor: remove runtime observations table"
```

## Chunk 5: Frontend And Docs

### Task 9: Keep frontend trace rendering aligned with the canonical runtime trace payload

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/types/websocket.ts`
- Modify: `frontend/src/domain/chat/normalizers.ts`
- Modify: `frontend/src/components/chat/ToolchainDrawer.tsx`
- Test: `frontend/src/__tests__/chatTraceState.test.ts`
- Test: `frontend/src/__tests__/toolchainDrawer.test.tsx`
- Test: `frontend/src/__tests__/realtimeProvider.test.tsx`

- [ ] **Step 1: Write the failing frontend trace tests**

```ts
it('renders llm and intent node details from canonical trace payload', () => {
  expect(screen.getByText('Intent resolution')).toBeInTheDocument();
  expect(screen.getByText('glm-5')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the targeted frontend tests**

Run: `cd frontend && npm test -- --run src/__tests__/chatTraceState.test.ts src/__tests__/toolchainDrawer.test.tsx src/__tests__/realtimeProvider.test.tsx`
Expected: FAIL until the frontend normalizers and drawer consume the new payload shape correctly

- [ ] **Step 3: Update frontend contracts and rendering**

```ts
type TraceLlmDetails = {
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
};
```

- [ ] **Step 4: Re-run the targeted frontend tests**

Run: `cd frontend && npm test -- --run src/__tests__/chatTraceState.test.ts src/__tests__/toolchainDrawer.test.tsx src/__tests__/realtimeProvider.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/chat.ts frontend/src/types/websocket.ts frontend/src/domain/chat/normalizers.ts frontend/src/components/chat/ToolchainDrawer.tsx frontend/src/__tests__/chatTraceState.test.ts frontend/src/__tests__/toolchainDrawer.test.tsx frontend/src/__tests__/realtimeProvider.test.tsx
git commit -m "refactor: align frontend with runtime trace store"
```

### Task 10: Update architecture docs and run final verification

**Files:**
- Modify: `docs/project-overview.md`
- Modify: `docs/task-agent-runtime-architecture.md`

- [ ] **Step 1: Update persistence-boundary and runtime-ownership docs**

```md
- `~/.magi/data/runtime_trace.db`
  Canonical runtime trace storage for chat execution observability
```

- [ ] **Step 2: Run backend verification**

Run: `cd backend && pytest tests/runtime_trace tests/api/test_chat_trace_read_service.py tests/agent/test_chat_postprocess_service.py tests/agent/test_chat_execution_coordinator.py tests/agent/test_function_calling_trace_store.py tests/agent/test_worker_trace_store.py tests/memory/l1/test_event_store.py tests/memory/test_memory_layers.py tests/agent/test_chat_session_service.py tests/api/test_messages_sessions.py tests/websocket/test_handlers.py -q`
Expected: PASS

- [ ] **Step 3: Run frontend verification**

Run: `cd frontend && npm test -- --run src/__tests__/chatTraceState.test.ts src/__tests__/toolchainDrawer.test.tsx src/__tests__/realtimeProvider.test.tsx src/__tests__/chatPage.test.tsx`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/project-overview.md docs/task-agent-runtime-architecture.md
git commit -m "docs: document runtime trace store boundary"
```
