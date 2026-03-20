# Hybrid Retrieval Runtime Singleton Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `HybridRetrievalService` from ad hoc construction sites and tool-local caching into a runtime-scoped singleton that is created after `UnifiedMemoryStore` is initialized, exported through the container/runtime bindings, and consumed consistently by API routes, tools, and context assembly.

**Architecture:** The runtime bootstrap owns a single `HybridRetrievalService` instance alongside `UnifiedMemoryStore`. The memory lifecycle module constructs the retrieval service after memory and LLM pool initialization. Runtime exports publish the singleton into DI bindings. Consumers stop constructing `HybridRetrievalService(unified_memory)` directly and instead resolve the shared runtime binding. This keeps retrieval policy, handler refresh behavior, and future caches/metrics consistent across entry points.

**Tech Stack:** Python 3.10+, dependency-injector, FastAPI, pytest

---

## Doc Alignment

- `docs/project-overview.md`
  The backend should keep cross-cutting runtime services in a clear composition root instead of rebuilding them in route/tool code.
- `docs/task-agent-runtime-architecture.md`
  Runtime services should be created during bootstrap, then injected into the agent/runtime stack as stable dependencies.

This plan keeps `HybridRetrievalService` runtime-scoped and owned by the bootstrap lifecycle rather than by request handlers or tools.

---

## File Map

### Bootstrap and runtime bindings

- Modify: `backend/src/magi/bootstrap/context.py`
  Add runtime ownership for the hybrid retrieval singleton.

- Modify: `backend/src/magi/core/container.py`
  Add a DI provider slot for the shared hybrid retrieval service.

- Modify: `backend/src/magi/core/runtime_bindings.py`
  Add `require_hybrid_retrieval_service()`.

- Modify: `backend/src/magi/memory/lifecycle.py`
  Construct `HybridRetrievalService` once after unified memory initialization.

- Modify: `backend/src/magi/bootstrap/exports.py`
  Export/reset the runtime singleton binding.

### Consumers

- Modify: `backend/src/magi/tools/builtin/memory_query_tool.py`
  Stop building/caching a private retrieval service and resolve the runtime binding instead.

- Modify: `backend/src/magi/api/routers/memory.py`
  Use the runtime singleton for `/memory/search` and eval read paths.

- Modify: `backend/src/magi/context/retrieval.py`
  Accept the shared retrieval service instead of constructing one ad hoc.

- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
  Pass the shared retrieval service into context retrieval.

### Tests

- Modify: `backend/tests/core/test_runtime_bindings.py`
- Modify: `backend/tests/bootstrap/test_runtime_trace_bootstrap.py`
  Extend bootstrap/runtime binding coverage for the new singleton.

- Modify: `backend/tests/tools/test_memory_query_tool.py`
  Update expectations to require the shared runtime binding.

- Modify: `backend/tests/context/test_retrieval_service.py`
  Verify context retrieval uses the injected singleton and still bypasses hybrid retrieval for L0-only requests.

- Modify: `backend/tests/api/test_memory_api.py`
  Verify the memory search route uses the bound runtime retrieval service.

---

## Chunk 1: Runtime Singleton Ownership

### Task 1: Add runtime bootstrap ownership and DI binding

**Files:**
- Modify: `backend/src/magi/bootstrap/context.py`
- Modify: `backend/src/magi/core/container.py`
- Modify: `backend/src/magi/core/runtime_bindings.py`
- Modify: `backend/src/magi/memory/lifecycle.py`
- Modify: `backend/src/magi/bootstrap/exports.py`
- Test: `backend/tests/core/test_runtime_bindings.py`
- Test: `backend/tests/bootstrap/test_runtime_trace_bootstrap.py`

- [ ] **Step 1: Write or extend failing tests for the runtime binding**

```python
def test_require_hybrid_retrieval_service_binding_raises_when_unbound() -> None:
    with pytest.raises(RuntimeError, match="hybrid_retrieval_service"):
        require_hybrid_retrieval_service()


@pytest.mark.asyncio
async def test_runtime_exports_register_hybrid_retrieval_service() -> None:
    context.memory.hybrid_retrieval_service = object()
    await RuntimeExportsModule(context).init()
    assert container.hybrid_retrieval_service() is context.memory.hybrid_retrieval_service
```

- [ ] **Step 2: Run the targeted binding/bootstrap tests**

Run:
`cd backend && pytest tests/core/test_runtime_bindings.py tests/bootstrap/test_runtime_trace_bootstrap.py -q`

Expected: FAIL because the binding/provider does not exist yet

- [ ] **Step 3: Implement runtime ownership**

Create a single `HybridRetrievalService` instance inside `MemoryStoreModule.init()` after `UnifiedMemoryStore.initialize()` and export it through `RuntimeExportsModule`.

- [ ] **Step 4: Re-run the targeted tests**

Run:
`cd backend && pytest tests/core/test_runtime_bindings.py tests/bootstrap/test_runtime_trace_bootstrap.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/bootstrap/context.py backend/src/magi/core/container.py backend/src/magi/core/runtime_bindings.py backend/src/magi/memory/lifecycle.py backend/src/magi/bootstrap/exports.py backend/tests/core/test_runtime_bindings.py backend/tests/bootstrap/test_runtime_trace_bootstrap.py
git commit -m "feat: add runtime hybrid retrieval binding"
```

## Chunk 2: Consumer Cutover

### Task 2: Move tools and API routes to the runtime singleton

**Files:**
- Modify: `backend/src/magi/tools/builtin/memory_query_tool.py`
- Modify: `backend/src/magi/api/routers/memory.py`
- Test: `backend/tests/tools/test_memory_query_tool.py`
- Test: `backend/tests/api/test_memory_api.py`

- [ ] **Step 1: Write or extend failing consumer tests**

```python
def test_tool_uses_runtime_hybrid_retrieval_binding(monkeypatch) -> None:
    monkeypatch.setattr(module, "require_hybrid_retrieval_service", lambda: service)
    tool = MemoryQueryTool()
    assert tool._get_service() is service
```

- [ ] **Step 2: Run the targeted tool/API tests**

Run:
`cd backend && pytest tests/tools/test_memory_query_tool.py tests/api/test_memory_api.py -q`

Expected: FAIL because consumers still build retrieval services directly

- [ ] **Step 3: Remove ad hoc construction from tools and routes**

All route/tool retrieval entry points should resolve `require_hybrid_retrieval_service()` instead of constructing `HybridRetrievalService(unified_memory)`.

- [ ] **Step 4: Re-run the targeted tests**

Run:
`cd backend && pytest tests/tools/test_memory_query_tool.py tests/api/test_memory_api.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/tools/builtin/memory_query_tool.py backend/src/magi/api/routers/memory.py backend/tests/tools/test_memory_query_tool.py backend/tests/api/test_memory_api.py
git commit -m "refactor: share runtime retrieval service"
```

## Chunk 3: Context Layer Cutover

### Task 3: Inject the shared retrieval service into context assembly

**Files:**
- Modify: `backend/src/magi/context/retrieval.py`
- Modify: `backend/src/magi/agent/task_agents/chat_task_agent.py`
- Test: `backend/tests/context/test_retrieval_service.py`
- Test: `backend/tests/agent/test_chat_task_agent_prompt_modules.py`

- [ ] **Step 1: Write or extend failing context tests**

```python
async def test_build_retrieved_memory_payload_uses_injected_service() -> None:
    retrieval = MagicMock()
    retrieval.query = AsyncMock(return_value=payload)
    service = ContextRetrievalService(unified_memory=memory, retrieval_service=retrieval)
```

- [ ] **Step 2: Run the targeted context tests**

Run:
`cd backend && pytest tests/context/test_retrieval_service.py tests/agent/test_chat_task_agent_prompt_modules.py -q`

Expected: FAIL because context retrieval still constructs its own service

- [ ] **Step 3: Switch context retrieval to the shared runtime service**

Keep the L0-only fast path, but route any hybrid query through the injected singleton.

- [ ] **Step 4: Re-run the targeted tests**

Run:
`cd backend && pytest tests/context/test_retrieval_service.py tests/agent/test_chat_task_agent_prompt_modules.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/context/retrieval.py backend/src/magi/agent/task_agents/chat_task_agent.py backend/tests/context/test_retrieval_service.py backend/tests/agent/test_chat_task_agent_prompt_modules.py
git commit -m "refactor: route context retrieval through runtime service"
```

## Chunk 4: Regression Verification

### Task 4: Run focused retrieval regression coverage

**Files:**
- No product code changes expected

- [ ] **Step 1: Run focused retrieval and bootstrap regression tests**

Run:
`cd backend && PYTHONPATH=src pytest tests/core/test_runtime_bindings.py tests/bootstrap/test_runtime_trace_bootstrap.py tests/memory/test_hybrid_retrieval_service.py tests/tools/test_memory_query_tool.py tests/context/test_retrieval_service.py tests/api/test_memory_api.py -q`

- [ ] **Step 2: Commit only if a test-only follow-up is required**

```bash
git add <tests-if-needed>
git commit -m "test: cover runtime retrieval singleton"
```

---

## Risks and Guardrails

- Do not keep two long-lived retrieval-service creation paths. Once the runtime binding exists, route consumers to it instead of preserving indefinite dual behavior.
- Keep `HybridRetrievalService` fail-fast if the binding is not initialized; startup order bugs should surface clearly.
- Do not move retrieval creation earlier than `UnifiedMemoryStore.initialize()`.
- Preserve the L0-only short-circuit in `ContextRetrievalService` so prompt assembly does not pay the hybrid query cost when only working memory is requested.
