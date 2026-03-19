# L1 L3 Batched Async Embeddings Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change L1 and L3 async embedding workers from single-item processing to local batched processing that flushes when 5 items accumulate or when the oldest queued item has waited 1 second.

**Architecture:** Keep the existing local `asyncio.Queue` model and vector storage layout. Add batch embedding support to `MemoryEmbeddingService`, then update the L1 and L3 background workers to collect eligible items into batches, call the embedding adapter once per batch, and upsert each returned vector back into the existing sqlite-vec registries.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, sqlite-vec, existing Magi memory stores, pytest.

---

## File Map

- Modify: `backend/src/magi/memory/embedding_service.py`
  - Add batch embedding helper that uses the embedding scenario adapter's batch API.
- Modify: `backend/src/magi/memory/l1/event_store.py`
  - Replace one-by-one async embedding consumption with batch-size / flush-window behavior.
- Modify: `backend/src/magi/memory/l3/summary_store.py`
  - Mirror the same batch-size / flush-window behavior for summary embeddings.
- Modify: `backend/tests/memory/l1/test_event_store.py`
  - Add focused async worker tests for batch size and flush timeout.
- Modify: `backend/tests/memory/l3/test_summary_store.py`
  - Add matching tests for L3 summary batching.

## Chunk 1: L1 Batch Worker

### Task 1: Add failing L1 batching tests

**Files:**
- Modify: `backend/tests/memory/l1/test_event_store.py`

- [ ] Write a failing test proving 5 queued events trigger one batch embedding call.
- [ ] Run the focused pytest selection and confirm it fails for the missing behavior.
- [ ] Write a failing test proving fewer than 5 events flush after roughly 1 second.
- [ ] Run the focused pytest selection and confirm it fails for the missing behavior.
- [ ] Commit after the tests are in place and verified red.

### Task 2: Implement L1 batched async embedding

**Files:**
- Modify: `backend/src/magi/memory/embedding_service.py`
- Modify: `backend/src/magi/memory/l1/event_store.py`

- [ ] Add `embed_texts(...)` to the memory embedding service.
- [ ] Update the L1 worker to collect a batch and flush on size or timeout.
- [ ] Re-run the focused L1 tests until green.
- [ ] Commit the L1 implementation.

## Chunk 2: L3 Batch Worker

### Task 3: Add failing L3 batching tests

**Files:**
- Modify: `backend/tests/memory/l3/test_summary_store.py`

- [ ] Write a failing test proving 5 queued summaries trigger one batch embedding call.
- [ ] Run the focused pytest selection and confirm it fails for the missing behavior.
- [ ] Write a failing test proving fewer than 5 summaries flush after roughly 1 second.
- [ ] Run the focused pytest selection and confirm it fails for the missing behavior.
- [ ] Commit after the tests are in place and verified red.

### Task 4: Implement L3 batched async embedding

**Files:**
- Modify: `backend/src/magi/memory/l3/summary_store.py`

- [ ] Mirror the L1 batch worker behavior for L3 summaries.
- [ ] Re-run the focused L3 tests until green.
- [ ] Run combined L1/L3 verification.
- [ ] Commit the L3 implementation and final verification.
