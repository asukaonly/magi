# Hybrid Retrieval Evidence Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve formal product memory recall quality by making L1 retrieval rank more answerable evidence and by preparing structured evidence bundles for downstream answer synthesis.

**Architecture:** Keep `HybridRetrievalService` as the formal layer router and strengthen `L1Handler` as the main answerability-aware retriever. First improve L1 reranking and retrieval trace without changing benchmark-only paths, then add service-level evidence packaging for grouped session context and temporal reasoning support.

**Tech Stack:** Python 3.10+, FastAPI, aiosqlite, sqlite-vec, pytest

---

## File Map

- Modify: `backend/src/magi/memory/hybrid_retrieval/handlers.py`
  - Add L1 rerank helpers and retrieval trace emission.
- Modify: `backend/src/magi/memory/hybrid_retrieval/service.py`
  - Add service-level evidence packaging after layer fusion.
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`
  - Extend retrieval payload contracts for grouped evidence bundles and trace metadata.
- Test: `backend/tests/memory/test_layer_handlers.py`
  - Add focused unit tests for L1 rerank behavior and trace fields.
- Test: `backend/tests/memory/test_hybrid_retrieval_service.py`
  - Add service-level tests for evidence packaging.

## Chunk 1: L1 Answerability Rerank

### Task 1: Add failing tests for L1 rerank

**Files:**
- Modify: `backend/tests/memory/test_layer_handlers.py`

- [ ] **Step 1: Write the failing tests**

Add tests that assert:
- a concise user-authored factual event outranks a generic assistant response when both are retrieved
- the returned L1 events include structured retrieval trace metadata for debugging

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/memory/test_layer_handlers.py -q`
Expected: FAIL because `L1Handler` currently preserves fused order and emits no rerank trace.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/src/magi/memory/hybrid_retrieval/handlers.py` to:
- compute per-event rerank features after hydration
- boost user-authored and phrase-dense events
- penalize verbose assistant guidance
- attach retrieval trace metadata to each returned event

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/memory/test_layer_handlers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/handlers.py backend/tests/memory/test_layer_handlers.py
git commit -m "feat: improve l1 retrieval reranking"
```

## Chunk 2: Service-Level Evidence Packaging

### Task 2: Add failing tests for grouped evidence bundles

**Files:**
- Modify: `backend/tests/memory/test_hybrid_retrieval_service.py`
- Modify: `backend/src/magi/memory/hybrid_retrieval/models.py`

- [ ] **Step 1: Write the failing tests**

Add tests that assert:
- `HybridRetrievalService` emits grouped evidence bundles for L1 hits
- neighboring turns from the same session are included when available
- trace records bundle counts

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/memory/test_hybrid_retrieval_service.py -q`
Expected: FAIL because the retrieval payload currently only exposes flat `l1_events`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/src/magi/memory/hybrid_retrieval/service.py` and `backend/src/magi/memory/hybrid_retrieval/models.py` to:
- define a structured evidence bundle field
- group L1 hits by session and local turn neighborhood
- expose the grouped bundles alongside the flat payload

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/asuka/code/magi/backend && pytest tests/memory/test_hybrid_retrieval_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/hybrid_retrieval/service.py backend/src/magi/memory/hybrid_retrieval/models.py backend/tests/memory/test_hybrid_retrieval_service.py
git commit -m "feat: add grouped retrieval evidence bundles"
```

## Chunk 3: Final Verification

### Task 3: Run focused regression suite

**Files:**
- No code changes

- [ ] **Step 1: Run retrieval-focused tests**

Run:
```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/test_layer_handlers.py tests/memory/test_hybrid_retrieval_service.py tests/memory/test_rrf_fusion.py -q
```

Expected: PASS

- [ ] **Step 2: Run API smoke for memory query**

Run:
```bash
cd /Users/asuka/code/magi/backend && pytest tests/api/test_memory_api.py -q -k "memory_search_api_uses_runtime_hybrid_retrieval_service"
```

Expected: PASS

- [ ] **Step 3: Commit follow-up fixes if needed**

```bash
git add <files>
git commit -m "test: verify hybrid retrieval evidence flow"
```

Plan complete and saved to `docs/superpowers/plans/2026-03-20-hybrid-retrieval-evidence-improvements.md`. Ready to execute.
