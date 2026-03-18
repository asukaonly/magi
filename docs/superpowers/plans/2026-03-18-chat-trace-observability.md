# Chat Trace Observability Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current tool-centric chat trace with a millisecond-based full execution trace that covers intent resolution, LLM calls, tool calls, orchestration, worker execution, retries, and final response emission.

**Architecture:** The implementation introduces normalized trace-node runtime events in `runtime_observations`, instruments chat and worker execution at shared write-side boundaries, and refactors the read side to build trace trees from explicit span relationships instead of inferring structure from mixed event types. `fact_events` remains the transcript source of truth, while `runtime_observations` becomes the canonical execution-trace store.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, React 18, TypeScript, Zustand, Vitest, pytest

---

## File Map

### Backend write side

- Modify: `backend/src/magi/agent/task_agents/chat/postprocess_service.py`
  Add normalized trace emission for turn lifecycle, tool loops, tool calls, and response emission.

- Modify: `backend/src/magi/agent/task_agents/chat/coordinator.py`
  Emit intent-resolution trace data with execution-mode decisions.

- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
  Centralize task-agent LLM trace capture for direct chat and worker LLM calls.

- Modify: `backend/src/magi/agent/execution/function_calling.py`
  Emit normalized tool-loop and tool-call nodes with retry and attempt metadata.

- Modify: `backend/src/magi/agent/workers/worker_manager.py`
  Emit worker lifecycle and worker LLM trace nodes.

- Modify: `backend/src/magi/llm/provider_bridge.py`
  Surface normalized LLM metrics needed by the trace model.

- Create: `backend/src/magi/agent/trace/contracts.py`
  Typed contracts and constants for normalized trace nodes.

- Create: `backend/src/magi/agent/trace/emitter.py`
  Shared helper for emitting normalized trace-node events with millisecond timing.

- Create: `backend/src/magi/agent/trace/time.py`
  Wall-clock and monotonic helpers for millisecond-safe timing.

### Backend read side

- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
  Rebuild snapshots and summaries from normalized trace-node events.

- Modify: `backend/src/magi/api/services/chat_read_service.py`
  Keep transcript rendering independent while adopting the new trace summary shape.

- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
  Broadcast richer trace-summary payloads for live updates.

- Modify: `backend/src/magi/api/routers/messages.py`
  Return the new snapshot and summary contract from `/messages/trace`.

### Frontend

- Modify: `frontend/src/api/modules/messages.ts`
  Update trace DTOs to the millisecond-based schema.

- Modify: `frontend/src/types/chat.ts`
  Update normalized chat trace contracts.

- Modify: `frontend/src/types/websocket.ts`
  Update live trace-update payloads.

- Modify: `frontend/src/domain/chat/normalizers.ts`
  Normalize new summary, node, retry, metrics, and IO payload fields.

- Modify: `frontend/src/pages/Chat.tsx`
  Consume the new summary contract and live updates.

- Modify: `frontend/src/components/chat/ToolchainDrawer.tsx`
  Render full execution trace details instead of tool-only nodes.

### Tests

- Modify: `backend/tests/agent/test_chat_postprocess_service.py`
- Create: `backend/tests/agent/test_trace_emitter.py`
- Modify: `backend/tests/llm/test_provider_bridge.py`
- Modify: `backend/tests/llm/test_function_calling_tool_call_parser.py`
- Create: `backend/tests/api/test_chat_trace_read_service.py`
- Modify: `frontend/src/__tests__/chatTraceState.test.ts`
- Modify: `frontend/src/__tests__/toolchainDrawer.test.tsx`
- Modify: `frontend/src/__tests__/realtimeProvider.test.tsx`

## Chunk 1: Normalized Trace Contracts And Timing

### Task 1: Add trace contracts and millisecond timing helpers

**Files:**
- Create: `backend/src/magi/agent/trace/contracts.py`
- Create: `backend/src/magi/agent/trace/time.py`
- Create: `backend/tests/agent/test_trace_emitter.py`

- [ ] **Step 1: Write the failing tests for trace node contract and duration helpers**

```python
def test_duration_ms_uses_monotonic_delta():
    started_wall_ms = 1710751000123
    started_mono = 10.0
    ended_wall_ms = 1710751001123
    ended_mono = 11.125

    record = build_trace_timing(
        started_at_ms=started_wall_ms,
        ended_at_ms=ended_wall_ms,
        started_monotonic=started_mono,
        ended_monotonic=ended_mono,
    )

    assert record.duration_ms == 1125
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/agent/test_trace_emitter.py -q`
Expected: FAIL because trace contracts or helpers do not exist yet

- [ ] **Step 3: Implement the shared contracts and timing helpers**

```python
@dataclass(slots=True)
class TraceNodePayload:
    trace_id: str
    turn_id: str
    span_id: str
    parent_span_id: str | None
    node_type: str
    name: str
    status: str
    attempt_index: int
    retry_count: int
    started_at_ms: int
    ended_at_ms: int | None
    duration_ms: int | None
```

- [ ] **Step 4: Run the new backend trace helper tests**

Run: `cd backend && pytest tests/agent/test_trace_emitter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/trace/contracts.py backend/src/magi/agent/trace/time.py backend/tests/agent/test_trace_emitter.py
git commit -m "feat: add trace timing contracts"
```

## Chunk 2: Chat Runtime Write-Side Instrumentation

### Task 2: Emit turn, intent, and response trace nodes from chat runtime

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat/coordinator.py`
- Modify: `backend/src/magi/agent/task_agents/chat/postprocess_service.py`
- Modify: `backend/tests/agent/test_chat_postprocess_service.py`
- Modify: `backend/tests/agent/test_chat_execution_coordinator.py`

- [ ] **Step 1: Write failing tests for intent-resolution and response-emission trace payloads**

```python
async def test_chat_postprocess_emits_response_trace_node():
    await service.handle(context, result)
    assert emitted_runtime_events[-1]["event_type"] == "TRACE_NODE_COMPLETED"
    assert emitted_runtime_events[-1]["payload"]["node_type"] == "response_emit"
```

- [ ] **Step 2: Run the targeted chat runtime tests**

Run: `cd backend && pytest tests/agent/test_chat_postprocess_service.py tests/agent/test_chat_execution_coordinator.py -q`
Expected: FAIL because normalized trace-node events are not emitted yet

- [ ] **Step 3: Implement turn lifecycle, intent-resolution, and response-emission trace events**

```python
await trace_emitter.emit_node_completed(
    node_type="intent_resolution",
    name="Intent resolution",
    output={
        "intent": decision.intent_name,
        "execution_mode": decision.execution_mode.value,
        "route_reason": decision.reasoning,
    },
)
```

- [ ] **Step 4: Re-run the targeted chat runtime tests**

Run: `cd backend && pytest tests/agent/test_chat_postprocess_service.py tests/agent/test_chat_execution_coordinator.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/coordinator.py backend/src/magi/agent/task_agents/chat/postprocess_service.py backend/tests/agent/test_chat_postprocess_service.py backend/tests/agent/test_chat_execution_coordinator.py
git commit -m "feat: trace chat intent and response nodes"
```

### Task 3: Instrument main LLM calls and function-calling tool loops

**Files:**
- Modify: `backend/src/magi/agent/task_agents/common/llm_service.py`
- Modify: `backend/src/magi/llm/provider_bridge.py`
- Modify: `backend/src/magi/agent/execution/function_calling.py`
- Modify: `backend/tests/llm/test_provider_bridge.py`
- Modify: `backend/tests/llm/test_function_calling_tool_call_parser.py`

- [ ] **Step 1: Write failing tests for LLM metrics and tool-loop trace payloads**

```python
async def test_provider_bridge_returns_trace_metrics():
    response = await bridge.complete(...)
    assert response.metadata["trace_metrics"]["input_tokens"] == 12
    assert response.metadata["trace_metrics"]["thinking_enabled"] is False
```

- [ ] **Step 2: Run the targeted LLM and function-calling tests**

Run: `cd backend && pytest tests/llm/test_provider_bridge.py tests/llm/test_function_calling_tool_call_parser.py -q`
Expected: FAIL because trace metrics and normalized tool-loop events are incomplete

- [ ] **Step 3: Implement shared LLM trace payload generation and tool-loop span emission**

```python
trace_metrics = {
    "provider": provider_name,
    "model": response.model,
    "input_tokens": usage.input_tokens,
    "output_tokens": usage.output_tokens,
    "reasoning_tokens": usage.reasoning_tokens,
    "thinking_enabled": not disable_thinking,
}
```

- [ ] **Step 4: Re-run the targeted LLM and function-calling tests**

Run: `cd backend && pytest tests/llm/test_provider_bridge.py tests/llm/test_function_calling_tool_call_parser.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/common/llm_service.py backend/src/magi/llm/provider_bridge.py backend/src/magi/agent/execution/function_calling.py backend/tests/llm/test_provider_bridge.py backend/tests/llm/test_function_calling_tool_call_parser.py
git commit -m "feat: trace llm calls and tool loops"
```

## Chunk 3: Worker And Orchestration Instrumentation

### Task 4: Trace worker dispatch, worker lifecycle, and worker LLM calls

**Files:**
- Modify: `backend/src/magi/agent/workers/worker_manager.py`
- Modify: `backend/src/magi/agent/task_orchestrator.py`
- Modify: `backend/tests/agent/test_task_orchestrator.py`
- Modify: `backend/tests/agent/test_chat_task_agent_orchestration.py`

- [ ] **Step 1: Write failing tests for worker dispatch and worker trace nodes**

```python
async def test_worker_dispatch_emits_trace_node():
    await orchestrator.start(...)
    assert any(p["node_type"] == "worker_dispatch" for p in emitted_trace_payloads)
```

- [ ] **Step 2: Run the orchestration-focused tests**

Run: `cd backend && pytest tests/agent/test_task_orchestrator.py tests/agent/test_chat_task_agent_orchestration.py -q`
Expected: FAIL because worker trace nodes do not exist yet

- [ ] **Step 3: Implement worker-dispatch, worker-root, and worker-LLM instrumentation**

```python
await trace_emitter.emit_node_started(
    node_type="worker",
    name=subtask.description,
    tags={"worker_id": worker_id, "subtask_id": subtask_id},
)
```

- [ ] **Step 4: Re-run the orchestration-focused tests**

Run: `cd backend && pytest tests/agent/test_task_orchestrator.py tests/agent/test_chat_task_agent_orchestration.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/workers/worker_manager.py backend/src/magi/agent/task_orchestrator.py backend/tests/agent/test_task_orchestrator.py backend/tests/agent/test_chat_task_agent_orchestration.py
git commit -m "feat: trace worker execution lifecycle"
```

## Chunk 4: Read Side And API Contract

### Task 5: Refactor chat trace read service to assemble explicit span trees

**Files:**
- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
- Modify: `backend/src/magi/api/services/chat_read_service.py`
- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
- Modify: `backend/src/magi/api/routers/messages.py`
- Create: `backend/tests/api/test_chat_trace_read_service.py`

- [ ] **Step 1: Write failing tests for normalized span-tree snapshots and millisecond summaries**

```python
def test_trace_snapshot_prefers_turn_trace_terminal_event():
    snapshot = service.get_trace_snapshot(...)
    assert snapshot["status"] == "failed"
    assert snapshot["summary"]["duration_ms"] == 1287
```

- [ ] **Step 2: Run the read-side trace tests**

Run: `cd backend && pytest tests/api/test_chat_trace_read_service.py tests/api/test_messages_router_bindings.py -q`
Expected: FAIL because the read side still expects legacy tool-centric events and second-based summaries

- [ ] **Step 3: Implement span-tree reconstruction and new summary fields**

```python
summary = {
    "turn_id": turn_id,
    "status": root.status,
    "headline": headline,
    "duration_ms": root.duration_ms,
    "retry_count": retry_count,
    "trace_available": bool(root.children),
}
```

- [ ] **Step 4: Re-run the read-side trace tests**

Run: `cd backend && pytest tests/api/test_chat_trace_read_service.py tests/api/test_messages_router_bindings.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/services/chat_trace_read_service.py backend/src/magi/api/services/chat_read_service.py backend/src/magi/websocket/bridge_lifecycle.py backend/src/magi/api/routers/messages.py backend/tests/api/test_chat_trace_read_service.py
git commit -m "feat: rebuild chat trace from span nodes"
```

## Chunk 5: Frontend Trace Rendering

### Task 6: Update frontend trace types, normalizers, and drawer rendering

**Files:**
- Modify: `frontend/src/api/modules/messages.ts`
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/types/websocket.ts`
- Modify: `frontend/src/domain/chat/normalizers.ts`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/components/chat/ToolchainDrawer.tsx`
- Modify: `frontend/src/__tests__/chatTraceState.test.ts`
- Modify: `frontend/src/__tests__/toolchainDrawer.test.tsx`
- Modify: `frontend/src/__tests__/realtimeProvider.test.tsx`

- [ ] **Step 1: Write failing frontend tests for duration-ms, token metrics, retries, and IO rendering**

```tsx
it('renders llm metrics and retry details', () => {
  render(<ToolchainDrawer snapshot={snapshot} ... />)
  expect(screen.getByText(/input tokens/i)).toBeInTheDocument()
  expect(screen.getByText(/retry 2/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the targeted frontend tests**

Run: `cd frontend && npm run test -- chatTraceState toolchainDrawer realtimeProvider`
Expected: FAIL because the frontend types and rendering still assume legacy summary and node fields

- [ ] **Step 3: Implement the new frontend trace contract and richer drawer UI**

```ts
export interface NormalizedTraceNode {
  id: string;
  kind: string;
  label: string;
  status: string;
  startedAtMs?: number | null;
  endedAtMs?: number | null;
  durationMs?: number | null;
  retryCount: number;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  metrics?: Record<string, unknown> | null;
}
```

- [ ] **Step 4: Re-run the targeted frontend tests**

Run: `cd frontend && npm run test -- chatTraceState toolchainDrawer realtimeProvider`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/messages.ts frontend/src/types/chat.ts frontend/src/types/websocket.ts frontend/src/domain/chat/normalizers.ts frontend/src/pages/Chat.tsx frontend/src/components/chat/ToolchainDrawer.tsx frontend/src/__tests__/chatTraceState.test.ts frontend/src/__tests__/toolchainDrawer.test.tsx frontend/src/__tests__/realtimeProvider.test.tsx
git commit -m "feat: render full chat execution trace"
```

## Chunk 6: Final Verification

### Task 7: Run focused verification and document any remaining gaps

**Files:**
- Modify: `docs/superpowers/specs/2026-03-18-chat-trace-observability-design.md` only if implementation deviates

- [ ] **Step 1: Run backend trace-focused verification**

Run: `cd backend && pytest tests/agent/test_trace_emitter.py tests/agent/test_chat_postprocess_service.py tests/llm/test_provider_bridge.py tests/llm/test_function_calling_tool_call_parser.py tests/api/test_chat_trace_read_service.py -q`
Expected: PASS

- [ ] **Step 2: Run frontend trace-focused verification**

Run: `cd frontend && npm run test -- chatTraceState toolchainDrawer realtimeProvider`
Expected: PASS

- [ ] **Step 3: Run type-check for frontend contract changes**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 4: If the implementation changed the spec, update the spec immediately**

```md
Update the design doc only where shipped behavior intentionally differs from the approved design.
```

- [ ] **Step 5: Commit verification or spec-alignment follow-up if needed**

```bash
git add <changed-files>
git commit -m "test: verify chat trace observability flow"
```
