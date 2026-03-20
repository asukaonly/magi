# L1 Event Model Final Shape Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current mixed legacy L1 event shape with a final simplified model: unified message payloads at the bus boundary, a minimal durable L1 schema, no `structured_payload`, no `raw_content`, no identity split fields, and no compatibility path.

**Architecture:** Standardize text-bearing events around `content`, `author_type`, and `content_type` first, then rebuild L1 normalization and persistence around those fields. After the new canonical shape exists, update all L1 consumers to read only official columns or store helpers, then rebuild FTS/vector derivation from code-level `get_search_text(...)` and `get_embedding_text(...)` methods instead of stored denormalized text blobs.

**Tech Stack:** Python 3.12, asyncio, aiosqlite, sqlite-vec, FastAPI services, existing Magi message bus and memory layers, pytest.

---

## Final Contracts

### Standard text event payload

All text-bearing user/assistant/system/tool/sensor events that enter the message bus should use this shape:

```python
{
    "content": str,
    "author_type": "user" | "assistant" | "system" | "tool" | "sensor" | "external",
    "content_type": "text" | "thinking" | "tool_result" | "observation" | "summary",
    "user_id": str | None,
    "session_id": str | None,
    "turn_id": str | None,
    "task_id": str | None,
    "goal_id": str | None,
    "source_item_id": str | None,
    "timestamp": float | None,
}
```

Rules:
- No `message` / `response` split.
- No fallback JSON blob in L1.
- New semantics must be represented by explicit stable fields, not by inventing new payload keys.

### Final L1 durable columns

Keep:

- `event_id`
- `correlation_id`
- `event_type`
- `source`
- `source_item_id`
- `timestamp`
- `created_at`
- `session_id`
- `turn_id`
- `user_id`
- `task_id`
- `content`
- `author_type`
- `content_type`
- `memory_domain`
- `ingest_target`
- `cognition_eligible`
- `tom_depth`
- `retention_class`
- `importance_score`
- `level`
- `media_path`
- `deleted_at`

Delete:

- `parent_event_id`
- `goal_id`
- `raw_content`
- `structured_payload`
- `metadata`
- `runtime_user_id`
- `memory_owner_id`
- `importance_t0_base`
- `importance_t1_score`
- `importance_version`
- `entity_focus_hint`
- `speaker_role`
- `grounding_type`
- `derived_from_event_ids`
- `semantic_owner_hint`
- `originality_type`
- `extraction_profile_id`
- `structured_entity_hints`
- `structured_graph_hints`

Derived in code only, not stored:

- `search_text`
- `embedding_text`

## File Map

### Core contracts and storage

- Modify: `backend/src/magi/events/events.py`
  - Keep event type constants, but update standard text event expectations in comments/tests if needed.
- Modify: `backend/src/magi/memory/event_contracts.py`
  - Replace the legacy `MemoryEvent` shape with the final contract.
  - Remove JSON blob fields and identity split fields.
  - Normalize bus events into `content`, `author_type`, and `content_type`.
- Modify: `backend/src/magi/memory/l1/event_store.py`
  - Rebuild the L1 table schema around the final columns.
  - FTS/vector indexing should derive text from `content` plus stable enum fields in code, not from a stored denormalized blob.
- Modify: `backend/src/magi/memory/__init__.py`
  - Remove references to deleted event fields and align ingestion logging/return values with the new contract.

### Event producers

- Modify: `backend/src/magi/api/services/message_dispatch_service.py`
  - Publish user text events with `content`.
- Modify: `backend/src/magi/awareness/action_emitter.py`
  - Publish assistant text events with `content`.
- Modify: other direct event producers under `backend/src/magi/agent/`, `backend/src/magi/awareness/`, and `backend/src/magi/timeline/` that still emit `message` / `response` or rely on removed L1-only fields.

### L1 consumers

- Modify: `backend/src/magi/agent/task_agents/chat/session_service.py`
  - Restore conversation from official L1 columns, not `structured_payload`.
- Modify: `backend/src/magi/api/services/chat_read_service.py`
  - Read `content`.
- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
  - Stop querying JSON payload fields. If `turn_id` remains required, promote it to a first-class L1 column in the same change or stop depending on L1 for that filter.
- Modify: `backend/src/magi/memory/l2/evidence_classifier.py`
  - Use `author_type`, `content_type`, `source`, and `event_type`.
- Modify: `backend/src/magi/memory/l2/context_collector.py`
  - Use `content`.
- Modify: `backend/src/magi/memory/l2/pipeline.py`
  - Remove reads of deleted fields and derive context from canonical columns only.
- Modify: `backend/src/magi/memory/l3/temporal_llm_service.py`
- Modify: `backend/src/magi/memory/l3/topic_llm_service.py`
- Modify: `backend/src/magi/memory/l3/summary_store.py`
  - Read `content` instead of `raw_content`.
- Modify: `backend/src/magi/memory/l4/procedural_memory.py`
  - Remove payload-json dependence for L1 events.

### Tests

- Modify: `backend/tests/memory/l1/test_event_store.py`
- Modify: `backend/tests/memory/test_sqlite_vec_retrieval.py`
- Modify: `backend/tests/memory/test_l1_fts5.py`
- Modify: `backend/tests/memory/test_hybrid_retrieval.py`
- Modify: `backend/tests/memory/test_layer_handlers.py`
- Modify: `backend/tests/memory/l2/test_context_collector.py`
- Modify: `backend/tests/memory/l2/test_pipeline.py`
- Modify: `backend/tests/memory/l3/test_temporal_llm_service.py`
- Modify: `backend/tests/memory/l3/test_topic_llm_service.py`
- Modify: `backend/tests/api/test_messages_sessions.py`
- Modify: `backend/tests/api/test_memory_api.py`
- Modify: `backend/tests/api` and `backend/tests/agent` files that still assert `message` / `response` / `structured_payload`.

## Chunk 1: Standardize Bus Text Events

### Task 1: Replace `message` / `response` payload divergence with unified text payloads

**Files:**
- Modify: `backend/src/magi/api/services/message_dispatch_service.py`
- Modify: `backend/src/magi/awareness/action_emitter.py`
- Modify: `backend/tests/api/...`

- [ ] **Step 1: Write failing tests for unified text payload shape**

Add focused tests proving:
- user messages publish `content`, `author_type="user"`, `content_type="text"`
- assistant responses publish `content`, `author_type="assistant"`, `content_type="text"`
- no emitted text event relies on `message` or `response`

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest <focused test selection> -v`
Expected: FAIL because producers still emit legacy payload keys.

- [ ] **Step 3: Implement the producers with the final payload shape**

- [ ] **Step 4: Re-run the focused tests and verify they pass**

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/services/message_dispatch_service.py backend/src/magi/awareness/action_emitter.py backend/tests/api
git commit -m "refactor: unify text event payloads"
```

## Chunk 2: Rebuild L1 Canonical Contract

### Task 2: Replace the legacy `MemoryEvent` shape with the final schema

**Files:**
- Modify: `backend/src/magi/memory/event_contracts.py`
- Modify: `backend/src/magi/memory/l1/event_store.py`
- Modify: `backend/tests/memory/l1/test_event_store.py`
- Modify: `backend/tests/memory/test_l1_fts5.py`
- Modify: `backend/tests/memory/test_sqlite_vec_retrieval.py`

- [ ] **Step 1: Write failing tests for the final L1 row shape**

Cover:
- `content` exists and stores only canonical content text
- `author_type` and `content_type` are explicit columns
- removed blob/legacy fields are absent
- FTS/vector derivation uses `get_search_text(...)` / `get_embedding_text(...)` from code, not a stored denormalized text field

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory/l1/test_event_store.py backend/tests/memory/test_l1_fts5.py backend/tests/memory/test_sqlite_vec_retrieval.py -v`
Expected: FAIL because the contract and schema still use legacy fields.

- [ ] **Step 3: Implement the final `MemoryEvent` contract**

Implementation notes:
- Remove deleted fields from the dataclass.
- Normalize `content`, `author_type`, and `content_type`.
- Keep `correlation_id`, `created_at`, `source_item_id`, and `task_id`.
- Drop compatibility code and old aliases entirely.

- [ ] **Step 4: Implement the final L1 schema and indexing**

Implementation notes:
- Rename `raw_content` storage to `content`.
- Drop `structured_payload` and `metadata`.
- Derive FTS/vector input in code from canonical columns only.
- Keep async batch embeddings for L1.

- [ ] **Step 5: Re-run the focused tests and verify they pass**

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/event_contracts.py backend/src/magi/memory/l1/event_store.py backend/tests/memory/l1/test_event_store.py backend/tests/memory/test_l1_fts5.py backend/tests/memory/test_sqlite_vec_retrieval.py
git commit -m "refactor: rebuild l1 event schema"
```

## Chunk 3: Convert L1 Readers To Official Columns

### Task 3: Remove consumer dependence on payload JSON blobs

**Files:**
- Modify: `backend/src/magi/agent/task_agents/chat/session_service.py`
- Modify: `backend/src/magi/api/services/chat_read_service.py`
- Modify: `backend/src/magi/api/services/chat_trace_read_service.py`
- Modify: `backend/src/magi/memory/l2/context_collector.py`
- Modify: `backend/src/magi/memory/l2/evidence_classifier.py`
- Modify: `backend/src/magi/memory/l2/pipeline.py`
- Modify: `backend/src/magi/memory/l3/*.py`
- Modify: `backend/src/magi/memory/l4/procedural_memory.py`
- Modify: matching tests under `backend/tests/agent`, `backend/tests/api`, `backend/tests/memory/l2`, `backend/tests/memory/l3`

- [ ] **Step 1: Write failing tests proving consumers only depend on canonical columns**

Cover:
- chat history restoration reads `content`
- chat read services read `content`
- no L1 query path reads `structured_payload`
- no L2/L3 consumer expects `raw_content`

- [ ] **Step 2: Run the focused tests and verify they fail**

- [ ] **Step 3: Refactor the consumers to use the final L1 model**

Implementation notes:
- If `turn_id` is still required from L1-backed reads, promote it to a real column now instead of keeping JSON extraction.
- Keep all access behind typed row/entity helpers where practical.

- [ ] **Step 4: Re-run the focused tests and verify they pass**

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/agent/task_agents/chat/session_service.py backend/src/magi/api/services/chat_read_service.py backend/src/magi/api/services/chat_trace_read_service.py backend/src/magi/memory/l2 backend/src/magi/memory/l3 backend/src/magi/memory/l4 backend/tests/agent backend/tests/api backend/tests/memory/l2 backend/tests/memory/l3
git commit -m "refactor: move l1 readers to canonical columns"
```

## Chunk 4: Full Verification And Cleanup

### Task 4: Run end-to-end verification and delete dead assumptions

**Files:**
- Modify: any remaining references found by ripgrep

- [ ] **Step 1: Search for removed field names and write failing regression tests if gaps remain**

Search for:
- `structured_payload`
- `raw_content`
- `runtime_user_id`
- `memory_owner_id`
- `message`
- `response`

- [ ] **Step 2: Remove remaining dead references**

- [ ] **Step 3: Run the full memory/chat verification suite**

Run:

```bash
PYTHONPATH=/Users/asuka/code/magi/backend/src pytest backend/tests/memory backend/tests/api backend/tests/agent -v
```

Expected: PASS for the updated final-shape contract.

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi backend/tests
git commit -m "refactor: finalize l1 event model cleanup"
```
