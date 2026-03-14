# Memory System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current plugin-styled memory stack with the new L0-L4 lifecycle-based memory system defined in `backend/docs/memory-system-design.md`, without preserving old data or schemas.

**Architecture:** The implementation proceeds in four chunks. First, standardize event contracts and land L0/L1 as the new memory backbone. Second, replace the split relation/user-graph model with a unified L2 cognition store and defensive ToM pipeline. Third, rebuild L3/L4 as reflection memory and procedural memory. Finally, replace retrieval, prompt integration, memory API, and housekeeping so the runtime reads from the new memory graph end-to-end.

**Tech Stack:** Python 3.10+, SQLite, aiosqlite, FastAPI, Pydantic v2, asyncio, pytest, current Magi runtime bootstrap and task-agent architecture.

---

## Scope Notes

- No historical data migration.
- No old table compatibility.
- `SelfMemory`, `OtherMemory`, and scenario prompt storage stay in place.
- This plan targets backend runtime and memory modules only.
- Every completed task should be committed immediately with a Conventional Commit message.

## File Map

### New files

- `backend/src/magi/memory/event_contracts.py`
- `backend/src/magi/memory/l0_working_memory.py`
- `backend/src/magi/memory/l1_event_store.py`
- `backend/src/magi/memory/l2_cognition_store.py`
- `backend/src/magi/memory/l2_extractors.py`
- `backend/src/magi/memory/l3_summary_store.py`
- `backend/src/magi/memory/l3_generators.py`
- `backend/src/magi/memory/l4_procedural_memory.py`
- `backend/src/magi/memory/hybrid_retrieval/models.py`
- `backend/src/magi/memory/hybrid_retrieval/router.py`
- `backend/src/magi/memory/hybrid_retrieval/service.py`
- `backend/src/magi/memory/hybrid_retrieval/__init__.py`
- `backend/tests/memory/test_memory_event_contracts.py`
- `backend/tests/memory/test_l0_working_memory.py`
- `backend/tests/memory/test_l1_event_store.py`
- `backend/tests/memory/test_l2_cognition_store.py`
- `backend/tests/memory/test_l3_summary_store.py`
- `backend/tests/memory/test_l4_procedural_memory.py`
- `backend/tests/memory/test_hybrid_retrieval.py`
- `backend/tests/agent/test_chat_prompt_memory_payload.py`

### Replace or heavily rewrite

- `backend/src/magi/memory/__init__.py`
- `backend/src/magi/memory/integration.py`
- `backend/src/magi/memory/prompt_context_assembler.py`
- `backend/src/magi/agent/task_agents/chat/prompt_service.py`
- `backend/src/magi/runtime/bootstrap.py`
- `backend/src/magi/tools/memory_query.py`
- `backend/src/magi/api/routers/memory.py`

### Remove after replacement

- `backend/src/magi/memory/raw_event_store.py`
- `backend/src/magi/memory/l2_event_relations.py`
- `backend/src/magi/memory/l2_user_graph.py`
- `backend/src/magi/memory/l3_semantic_embeddings.py`
- `backend/src/magi/memory/l4_summaries.py`
- `backend/src/magi/memory/l5_capabilities.py`
- `backend/src/magi/memory/query/`

---

## Chunk 1: Foundations, L0, and L1

### Task 1: Standardize memory event contracts and config

**Files:**
- Create: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/test_memory_event_contracts.py`

- [ ] **Step 1: Write the failing tests for normalized memory events**

```python
def test_normalized_memory_event_requires_domain_and_ingest_target():
    ...

def test_runtime_progress_event_defaults_to_l0_only():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_memory_event_contracts.py -v`
Expected: FAIL because the new event contract module does not exist yet.

- [ ] **Step 3: Implement `MemoryEvent` and normalization helpers**

Required behavior:

1. Define `memory_domain`, `ingest_target`, `cognition_eligible`, `tom_depth`, `retention_class`.
2. Add helper constructors or normalization functions for:
   - user-authored content
   - external activity
   - runtime telemetry
3. Encode the routing defaults from `memory-system-design.md`.

- [ ] **Step 4: Add config fields**

Add config support in `backend/src/magi/config/models.py` for:

1. layer enable flags
2. L0 checkpoint settings
3. LLM extraction toggles
4. retention policy toggles
5. runtime replay override for `l0_only` events

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_memory_event_contracts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/src/magi/config/models.py backend/src/magi/memory/integration.py backend/tests/memory/test_memory_event_contracts.py
git commit -m "feat: add memory event contracts"
```

### Task 2: Implement L0 working memory with checkpoint support

**Files:**
- Create: `backend/src/magi/memory/l0_working_memory.py`
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l0_working_memory.py`

- [ ] **Step 1: Write failing tests for session, goal stack, and checkpoint restore**

```python
async def test_l0_restores_session_from_checkpoint():
    ...

async def test_l0_can_store_temporary_tactics():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l0_working_memory.py -v`
Expected: FAIL because the store does not exist.

- [ ] **Step 3: Implement the L0 store**

Required capabilities:

1. in-memory primary state
2. SQLite checkpoint tables
3. session lifecycle
4. goal stack CRUD
5. active entity upsert/read
6. temporary tactic upsert/read/expiry
7. restore on restart

- [ ] **Step 4: Wire L0 into runtime bootstrap and unified memory entrypoint**

Required wiring:

1. initialize L0 before task agents
2. expose L0 through the unified memory facade
3. register shutdown checkpoint flush

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l0_working_memory.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l0_working_memory.py backend/src/magi/runtime/bootstrap.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l0_working_memory.py
git commit -m "feat: add l0 working memory"
```

### Task 3: Replace raw event store with the new L1 event store

**Files:**
- Create: `backend/src/magi/memory/l1_event_store.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Remove: `backend/src/magi/memory/raw_event_store.py`
- Test: `backend/tests/memory/test_l1_event_store.py`

- [ ] **Step 1: Write failing tests for L1 insert/query behavior**

```python
async def test_l1_persists_memory_event_with_policy_fields():
    ...

async def test_l1_filters_by_domain_and_ingest_target():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l1_event_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement L1 schema and repository**

Required capabilities:

1. normalized event insert
2. domain/source/session/user/task filtering
3. `l0_only` event suppression from L1
4. soft delete support
5. vector columns and retry status fields
6. time-slice path routing abstraction

- [ ] **Step 4: Rewrite integration entry flow**

Required behavior:

1. runtime events enter normalizer first
2. `l0_only` events update L0 but do not write L1
3. `l0_and_l1` events update both
4. async fan-out starts only after L1 write succeeds

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l1_event_store.py tests/memory/test_memory_event_contracts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l1_event_store.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l1_event_store.py
git rm backend/src/magi/memory/raw_event_store.py
git commit -m "feat: replace raw store with l1 event store"
```

---

## Chunk 2: L2 Cognition and Defensive ToM

### Task 4: Implement unified L2 cognition store

**Files:**
- Create: `backend/src/magi/memory/l2_cognition_store.py`
- Remove: `backend/src/magi/memory/l2_event_relations.py`
- Remove: `backend/src/magi/memory/l2_user_graph.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Write failing tests for graph triples and ToM assertions**

```python
def test_l2_upserts_knowledge_graph_triple_with_evidence():
    ...

def test_l2_tom_assertion_starts_low_confidence():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L2 schema**

Required tables and behaviors:

1. `knowledge_graph`
2. `tom_trait_assertions`
3. `tom_snapshots`
4. conflict and deprecation helpers
5. validation-state updates
6. evidence backtrace storage

- [ ] **Step 4: Replace unified memory references**

Update the unified memory facade so callers use the new cognition store instead of the old relation/user graph split.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_cognition_store.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l2_cognition_store.py
git rm backend/src/magi/memory/l2_event_relations.py backend/src/magi/memory/l2_user_graph.py
git commit -m "feat: add l2 cognition store"
```

### Task 5: Add L2 extraction pipeline and strong-claim validation

**Files:**
- Create: `backend/src/magi/memory/l2_extractors.py`
- Modify: `backend/src/magi/memory/integration.py`
- Test: `backend/tests/memory/test_l2_cognition_store.py`

- [ ] **Step 1: Add failing tests for source-specific ToM depth**

```python
async def test_chat_event_can_generate_defensive_psychology_assertion():
    ...

async def test_group_chat_event_only_generates_topology_assertions():
    ...
```

- [ ] **Step 2: Run the targeted tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -k \"psychology or topology\" -v`
Expected: FAIL

- [ ] **Step 3: Implement extractor pipeline**

Required behavior:

1. map events to `tom_depth`
2. call LLM extractors for graph and ToM separately
3. seed all subjective assertions at low confidence
4. upgrade to stable only after evidence thresholds are met
5. downgrade on contradictory evidence

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l2_cognition_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_extractors.py backend/src/magi/memory/integration.py backend/tests/memory/test_l2_cognition_store.py
git commit -m "feat: add defensive tom extraction"
```

---

## Chunk 3: L3 Reflection Memory and L4 Procedural Memory

### Task 6: Rebuild summaries as L3 reflection memory

**Files:**
- Create: `backend/src/magi/memory/l3_summary_store.py`
- Create: `backend/src/magi/memory/l3_generators.py`
- Remove: `backend/src/magi/memory/l4_summaries.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l3_summary_store.py`

- [ ] **Step 1: Write failing tests for temporal/thematic summary generation**

```python
def test_temporal_summary_excludes_runtime_telemetry():
    ...

def test_thematic_summary_keeps_source_event_backtrace():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l3_summary_store.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L3 store and generators**

Required capabilities:

1. temporal summary generation
2. thematic summary generation
3. insight storage
4. source-event backtrace
5. vector support on summary rows
6. permanent-event no-delete guarantee

- [ ] **Step 4: Update integration hooks**

Make summary generation consume only `cognition_eligible=true` and non-disposable events.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l3_summary_store.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l3_summary_store.py backend/src/magi/memory/l3_generators.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l3_summary_store.py
git rm backend/src/magi/memory/l4_summaries.py
git commit -m "feat: add l3 reflection memory"
```

### Task 7: Replace capability memory with L4 procedural memory

**Files:**
- Create: `backend/src/magi/memory/l4_procedural_memory.py`
- Remove: `backend/src/magi/memory/l5_capabilities.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Test: `backend/tests/memory/test_l4_procedural_memory.py`

- [ ] **Step 1: Write failing tests for procedural skill learning**

```python
def test_repeated_failures_open_circuit_breaker():
    ...

def test_success_history_updates_proficiency_and_template():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l4_procedural_memory.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the L4 store**

Required capabilities:

1. skill upsert by tool/workflow/strategy identity
2. proficiency and success-rate tracking
3. circuit breaker state transitions
4. context-affinity storage
5. optimized prompt/params storage
6. event evidence trace

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/memory/test_l4_procedural_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l4_procedural_memory.py backend/src/magi/memory/integration.py backend/src/magi/memory/__init__.py backend/tests/memory/test_l4_procedural_memory.py
git rm backend/src/magi/memory/l5_capabilities.py
git commit -m "feat: add l4 procedural memory"
```

---

## Chunk 4: Retrieval, Prompt Wiring, API, and Cleanup

### Task 8: Replace legacy query service with hybrid retrieval

**Files:**
- Create: `backend/src/magi/memory/hybrid_retrieval/models.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/router.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/service.py`
- Create: `backend/src/magi/memory/hybrid_retrieval/__init__.py`
- Remove: `backend/src/magi/memory/query/`
- Modify: `backend/src/magi/tools/memory_query.py`
- Test: `backend/tests/memory/test_hybrid_retrieval.py`

- [ ] **Step 1: Write failing tests for detail/summary/experience routing**

```python
async def test_detail_query_prefers_l1_and_l0():
    ...

async def test_experience_query_prefers_l4():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_hybrid_retrieval.py -v`
Expected: FAIL

- [ ] **Step 3: Implement hybrid retrieval contracts and service**

Required behavior:

1. detail mode -> L0/L1 first
2. summary mode -> L3 first
3. experience/strategy mode -> L4 first
4. graph mode -> L2 first
5. raw evidence backtrace in response metadata

- [ ] **Step 4: Update `memory_query` tool**

Make the tool consume the new service and return layer-aware payloads.

- [ ] **Step 5: Re-run tests**

Run: `cd backend && pytest tests/memory/test_hybrid_retrieval.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval backend/src/magi/tools/memory_query.py backend/tests/memory/test_hybrid_retrieval.py
git rm -r backend/src/magi/memory/query
git commit -m "feat: add hybrid memory retrieval"
```

### Task 9: Wire new memory payloads into prompt assembly

**Files:**
- Modify: `backend/src/magi/memory/prompt_context_assembler.py`
- Modify: `backend/src/magi/agent/task_agents/chat/prompt_service.py`
- Test: `backend/tests/agent/test_chat_prompt_memory_payload.py`

- [ ] **Step 1: Write failing tests for prompt payload composition**

```python
async def test_prompt_context_includes_l0_l2_l3_l4_payloads():
    ...
```

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/agent/test_chat_prompt_memory_payload.py -v`
Expected: FAIL

- [ ] **Step 3: Implement new prompt payload mapping**

Required behavior:

1. L0 workbench enters prompt
2. L2 entity cards and relationship cards enter prompt
3. L3 reflections enter prompt
4. L4 procedural guidance enters prompt
5. legacy `preference_memory` keeps working

- [ ] **Step 4: Re-run tests**

Run: `cd backend && pytest tests/agent/test_chat_prompt_memory_payload.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/prompt_context_assembler.py backend/src/magi/agent/task_agents/chat/prompt_service.py backend/tests/agent/test_chat_prompt_memory_payload.py
git commit -m "feat: wire memory payload into prompts"
```

### Task 10: Replace memory API and housekeeping hooks

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: maintenance daemon related runtime files
- Test: `backend/tests/api/test_memory_api.py`

- [ ] **Step 1: Add failing tests for new memory API responses**

```python
def test_memory_statistics_api_returns_l0_l4_sections():
    ...
```

- [ ] **Step 2: Run the focused API tests**

Run: `cd backend && pytest tests/api/test_memory_api.py -v`
Expected: FAIL

- [ ] **Step 3: Update API and daemon wiring**

Required behavior:

1. expose new layer statistics
2. expose ToM assertions / snapshots
3. expose procedural skills
4. schedule compression and cleanup in maintenance daemon
5. keep scheduler reserved for business jobs

- [ ] **Step 4: Run verification suite for the new memory stack**

Run:

```bash
cd backend
pytest tests/memory/test_memory_event_contracts.py \
       tests/memory/test_l0_working_memory.py \
       tests/memory/test_l1_event_store.py \
       tests/memory/test_l2_cognition_store.py \
       tests/memory/test_l3_summary_store.py \
       tests/memory/test_l4_procedural_memory.py \
       tests/memory/test_hybrid_retrieval.py \
       tests/agent/test_chat_prompt_memory_payload.py \
       tests/api/test_memory_api.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/memory.py backend/src/magi/runtime/bootstrap.py backend/tests/api/test_memory_api.py
git commit -m "feat: finish memory runtime integration"
```

---

## Final Cleanup Checklist

- [ ] Remove dead imports from `backend/src/magi/memory/__init__.py`
- [ ] Remove old memory layer references from bootstrap logs and API labels
- [ ] Re-read `backend/docs/memory-system-design.md` and update any terminology drift
- [ ] Run `cd backend && pytest` if the focused suite passes and time allows
- [ ] Commit any remaining doc-sync changes separately

## Definition of Done

The memory system rewrite is complete when all of the following are true:

1. All runtime memory writes go through the new event contract.
2. `l0_only` runtime events no longer flood L1.
3. L2 graph and ToM run through one unified cognition store.
4. L3 summaries are reflection-oriented and evidence-traceable.
5. L4 procedural memory can influence future execution choices.
6. Prompt assembly reads L0/L2/L3/L4 payloads.
7. The legacy query layer is removed.
8. Memory API reflects the new architecture.
9. Focused test suite passes.
