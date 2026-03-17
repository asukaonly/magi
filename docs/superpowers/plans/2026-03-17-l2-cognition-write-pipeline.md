# L2 Cognition Write Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the full L2 write pipeline so L1 events asynchronously drive entity extraction, entity resolution, graph/assertion writes, entity-level reconcile, and snapshot materialization, while also exposing a manual L2 lab in the frontend for injecting test events and triggering reconcile/merge actions.

**Architecture:** Keep `L1` as the durable synchronous source of truth and move `L2` to an asynchronous, evidence-first pipeline. The backend will split L2 into four responsibilities: event extraction, entity catalog/resolution, entity reconcile, and snapshot materialization. The frontend L2 tab becomes a lightweight lab that can post synthetic events into the normal memory path and manually trigger reconcile/materialization for testing.

**Tech Stack:** Python 3.10+, asyncio, FastAPI, aiosqlite, existing Magi `ScenarioLLMPool`, React 18, TypeScript, Vitest, existing memory API/hook/components.

---

## Scope Guardrails

- Keep L0 and L1 write semantics intact.
- Do not block the caller on L2 LLM work.
- Do not write `tom_snapshots` directly from a single event.
- LLM outputs are candidates only; database writes stay rule-driven and state-machine-driven.
- Preserve evidence backlinks to `L1 event_id` for every L2 artifact.
- Add manual L2 testing controls only inside the existing memory workspace; do not invent a separate admin page.
- Do not touch unrelated local changes already present in the worktree.

## Source Documents To Re-read Before Implementation

- `docs/project-overview.md`
- `docs/product-configuration-guide.md`
- `docs/task-agent-runtime-architecture.md`
- `docs/memory-system-design.md`
- `docs/memory-system-execution-plan.md`

## File Map

### New backend files

- `backend/src/magi/memory/l2_models.py`
  Contracts for mentions, canonical entities, graph candidates, assertion candidates, contradiction hints, reconcile outcomes, and manual lab requests.
- `backend/src/magi/memory/l2_prompt_templates.py`
  Centralized English prompt templates for mention extraction, entity resolution, graph extraction, ToM extraction, contradiction hints, and entity reconcile.
- `backend/src/magi/memory/l2_entity_catalog.py`
  SQLite-backed entity catalog, aliases, and mention resolution helpers.
- `backend/src/magi/memory/l2_pipeline.py`
  Async queues, worker tasks, micro-batch windowing, event extraction orchestration, touched-entity fan-out, and shutdown/drain behavior.
- `backend/src/magi/memory/l2_llm_service.py`
  Thin wrapper around `ScenarioLLMPool` that executes the L2 prompts and validates JSON responses.
- `backend/tests/memory/test_l2_entity_catalog.py`
- `backend/tests/memory/test_l2_pipeline.py`
- `backend/tests/memory/test_l2_manual_api.py`

### Modified backend files

- `backend/src/magi/memory/__init__.py`
  Stop synchronous L2 writes inside `ingest_event()`, enqueue L2 work instead, expose manual trigger helpers.
- `backend/src/magi/memory/integration.py`
  Extend statistics to report L2 queue/extract/reconcile/materialize counts and failures.
- `backend/src/magi/memory/l2_cognition_store.py`
  Expand schema and store methods for entity catalog links, assertion coexistence, contradiction state transitions, reconcile persistence, and snapshot materialization.
- `backend/src/magi/memory/l1_event_store.py`
  Add helper methods for event lookup by `event_id`, neighborhood windows, and entity-oriented evidence fetches used by reconcile.
- `backend/src/magi/memory/lifecycle.py`
  Wire `ScenarioLLMPool` into L2 services and start/stop pipeline workers with the memory lifecycle.
- `backend/src/magi/api/routers/memory.py`
  Add manual L2 lab endpoints for synthetic event ingest, event extraction replay, entity reconcile, snapshot refresh, and entity listing.
- `backend/src/magi/bootstrap/context.py`
  Add explicit L2 pipeline state if needed by lifecycle ownership.

### New frontend files

- `frontend/src/__tests__/l2LabPage.test.tsx`
  UI tests for manual event injection and manual reconcile flows.

### Modified frontend files

- `frontend/src/api/modules/memory.ts`
  Add request/response types and API calls for the L2 lab endpoints.
- `frontend/src/hooks/useMemory.ts`
  Add L2 lab state, manual action handlers, mutation loading state, and refresh choreography.
- `frontend/src/components/memory/L2Tab.tsx`
  Add the manual event composer, entity selector, reconcile/materialize actions, and richer L2 cards.
- `frontend/src/pages/Events.tsx`
  Pass the new L2 lab props into `L2Tab`.
- `frontend/src/i18n/locales/zh-CN/app.json`
- `frontend/src/i18n/locales/en/app.json`
  Add all new user-facing strings under `memory.l2` and keep keys aligned.

---

## Chunk 1: Split L2 Off The Synchronous L1 Path

### Task 1: Freeze the async L2 architecture in code-facing contracts

**Files:**
- Create: `backend/src/magi/memory/l2_models.py`
- Modify: `backend/src/magi/memory/event_contracts.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for the new L2 contract objects**

Cover these cases:
- extraction job payload can be created from a stored `event_id`
- reconcile job payload can carry one or more `entity_id`
- manual lab request validates source, user id, and text payload
- contradiction hints and reconcile outcomes serialize deterministically

- [ ] **Step 2: Run the focused test file**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k contracts -v`
Expected: FAIL because `l2_models.py` and its DTOs do not exist.

- [ ] **Step 3: Implement the L2 model module**

Required contracts:
- `EntityMention`
- `CanonicalEntityCandidate`
- `GraphCandidate`
- `TomAssertionCandidate`
- `ContradictionHint`
- `L2EventExtractionJob`
- `L2EntityReconcileJob`
- `L2SnapshotRefreshJob`
- `ManualL2EventRequest`
- `ManualL2ActionResponse`

Implementation notes:
- keep all contracts JSON-safe
- include `event_id` and `evidence_text` in candidate payloads
- keep confidence fields explicit floats
- encode action type labels so stats and logs stay stable

- [ ] **Step 4: Add any minimal event-contract fields needed by L2 routing**

Only add fields that unblock the pipeline, for example:
- manual source marker for L2 lab events
- optional `entity_focus_hint`
- optional `source_item_id` reuse for manual lab correlation

Do not widen the event contract beyond the needs of L2.

- [ ] **Step 5: Re-run the focused contract tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k contracts -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_models.py backend/src/magi/memory/event_contracts.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 pipeline contracts"
```

### Task 2: Replace synchronous L2 writes with queued background work

**Files:**
- Create: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/memory/lifecycle.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for async queue behavior**

Cover these cases:
- `UnifiedMemoryStore.ingest_event()` writes L1 but does not call L2 extraction synchronously
- cognition-ineligible events do not enqueue L2 work
- cognition-eligible events enqueue extraction jobs
- pipeline stats track enqueued, completed, failed, and skipped jobs
- lifecycle shutdown drains or cleanly stops workers

- [ ] **Step 2: Run the focused queue tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k queue -v`
Expected: FAIL because `ingest_event()` still performs synchronous `l2.apply_memory_event()`.

- [ ] **Step 3: Implement `l2_pipeline.py`**

Responsibilities:
- own `asyncio.Queue` instances for extract, reconcile, and snapshot refresh
- support micro-batch extraction windows keyed by entity/session/source/time bucket
- record counters for enqueued jobs, retries, and failures
- expose `start()`, `shutdown()`, `enqueue_event()`, `enqueue_entities()`, `enqueue_snapshot_refresh()`

Do not add a second scheduler system; keep it local to the memory lifecycle.

- [ ] **Step 4: Update `UnifiedMemoryStore`**

Change `backend/src/magi/memory/__init__.py` so that:
- L0 remains synchronous
- L1 remains synchronous
- L4 remains as-is unless explicitly deferred later
- L2 extraction is replaced by queue enqueue only
- manual helper methods exist for:
  - replaying extraction for an `event_id`
  - reconciling one or more entities
  - refreshing snapshots for one or more entities

- [ ] **Step 5: Update integration and lifecycle wiring**

In `backend/src/magi/memory/integration.py` and `backend/src/magi/memory/lifecycle.py`:
- create/start the L2 pipeline after the stores initialize
- stop it during shutdown before store teardown
- add L2 pipeline statistics into the integration response
- make sure log messages distinguish extract vs reconcile vs snapshot jobs

- [ ] **Step 6: Re-run the queue tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k queue -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/__init__.py backend/src/magi/memory/integration.py backend/src/magi/memory/lifecycle.py backend/tests/memory/test_l2_pipeline.py
git commit -m "refactor: queue l2 cognition writes"
```

---

## Chunk 2: Entity Extraction, Resolution, And Prompted Candidate Generation

### Task 3: Build the entity catalog and mention-resolution layer

**Files:**
- Create: `backend/src/magi/memory/l2_entity_catalog.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Test: `backend/tests/memory/test_l2_entity_catalog.py`

- [ ] **Step 1: Write failing tests for entity canonicalization**

Cover these cases:
- exact alias mapping resolves `上海` and `魔都` to one canonical place entity
- unresolved ambiguous mentions are kept unresolved
- low-confidence matches do not merge automatically
- mention rows preserve raw surface form and evidence event ids
- catalog can list canonical entities and aliases for frontend selection

- [ ] **Step 2: Run the focused entity catalog tests**

Run: `cd backend && pytest tests/memory/test_l2_entity_catalog.py -v`
Expected: FAIL because the entity catalog schema and API do not exist.

- [ ] **Step 3: Extend `l2_cognition_store.py` schema**

Add tables for:
- `entity_catalog`
- `entity_aliases`
- `entity_mentions`

Keep them in `memory.db` so the L2 state remains consolidated with other non-L1 layers.

- [ ] **Step 4: Implement `l2_entity_catalog.py`**

Required behavior:
- upsert canonical entity nodes
- add aliases and source-specific identifiers
- store mention-level evidence
- resolve by exact alias first
- support a “do not merge” outcome for ambiguous candidates
- expose list/query methods for the manual L2 UI

- [ ] **Step 5: Re-run entity catalog tests**

Run: `cd backend && pytest tests/memory/test_l2_entity_catalog.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_entity_catalog.py backend/src/magi/memory/l2_cognition_store.py backend/tests/memory/test_l2_entity_catalog.py
git commit -m "feat: add l2 entity catalog"
```

### Task 4: Add LLM prompt templates and the L2 LLM service

**Files:**
- Create: `backend/src/magi/memory/l2_prompt_templates.py`
- Create: `backend/src/magi/memory/l2_llm_service.py`
- Modify: `backend/src/magi/memory/lifecycle.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for L2 prompt execution plumbing**

Cover these cases:
- prompt template renders mention extraction payloads deterministically
- invalid JSON from the model fails closed and returns no candidates
- low-confidence resolution is surfaced as unresolved
- single-event ToM candidates are capped at low confidence

- [ ] **Step 2: Run the focused LLM service tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k llm -v`
Expected: FAIL because the prompt templates and LLM wrapper do not exist.

- [ ] **Step 3: Implement prompt templates exactly once in `l2_prompt_templates.py`**

Include templates for:
- entity mention extraction
- entity resolution against candidate canonical entities
- graph fact candidate extraction
- defensive ToM assertion extraction
- contradiction hint detection
- entity-level reconcile summary

Constraints:
- English prompt bodies
- JSON-only output instructions
- conservative extraction language
- no direct snapshot generation prompt in this first pass

- [ ] **Step 4: Implement `l2_llm_service.py`**

Required behavior:
- call the existing `ScenarioLLMPool`
- parse JSON safely
- reject malformed payloads
- normalize confidence bounds
- return empty candidate lists on failure instead of raising into caller logic

Use whichever existing scenario is the closest fit today; document any temporary scenario reuse in code comments and in the final implementation PR notes.

- [ ] **Step 5: Wire the service into memory lifecycle**

Update `backend/src/magi/memory/lifecycle.py` so the L2 pipeline can depend on the new service without reaching across unrelated layers.

- [ ] **Step 6: Re-run the LLM service tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k llm -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/l2_prompt_templates.py backend/src/magi/memory/l2_llm_service.py backend/src/magi/memory/lifecycle.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 llm extraction service"
```

### Task 5: Implement event extraction and candidate persistence

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Modify: `backend/src/magi/memory/l1_event_store.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for end-to-end event extraction**

Cover these cases:
- extraction loads the triggering event from L1 and optionally nearby context
- extracted mentions are stored before resolution
- resolved entities write canonical IDs into graph and assertion candidates
- graph facts are restricted to explicit facts and stable-preference candidates
- single-event ToM outputs remain `tentative`

- [ ] **Step 2: Run the focused extraction tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k extract -v`
Expected: FAIL because the queue worker cannot yet perform full extraction.

- [ ] **Step 3: Add L1 helper reads**

In `backend/src/magi/memory/l1_event_store.py`, implement helpers for:
- `get_event(event_id)`
- `get_neighbor_events(event_id, before, after)`
- `query_events_for_entity_window(...)`

Do not broaden retrieval APIs for end-user search; keep these helpers L2-internal.

- [ ] **Step 4: Implement extraction worker logic**

In `backend/src/magi/memory/l2_pipeline.py`:
- load the event and local context window
- run mention extraction
- resolve mentions through rules first, then the LLM service only when needed
- persist mentions and aliases
- run graph candidate extraction
- run ToM candidate extraction only when `tom_depth` allows it
- store graph candidates and assertion candidates with evidence links
- emit touched entity ids into the reconcile queue

- [ ] **Step 5: Expand `l2_cognition_store.py` persistence methods**

Required changes:
- keep `knowledge_graph` upserts idempotent
- allow `tom_trait_assertions` to coexist by `(entity_id, entity_type, trait_name, trait_value)` instead of collapsing all values under one trait
- preserve `validation_state`, `supporting_event_ids`, and contradiction bookkeeping

- [ ] **Step 6: Re-run extraction tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k extract -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/l2_cognition_store.py backend/src/magi/memory/l1_event_store.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: extract l2 candidates from l1 events"
```

---

## Chunk 3: Reconcile, Contradictions, And Snapshot Materialization

### Task 6: Implement contradiction hints and entity-level reconcile

**Files:**
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for reconcile state transitions**

Cover these cases:
- repeated compatible evidence upgrades an assertion from `tentative` to `corroborated`
- stable traits require multiple independent events and sufficient time span
- explicit reversal generates contradiction hints and downgrades prior assertions
- exclusive graph facts become `deprecated` or `conflicted` according to rule table
- volatile traits stay out of stable snapshot fields

- [ ] **Step 2: Run the focused reconcile tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k reconcile -v`
Expected: FAIL because entity-level reconcile logic is not implemented.

- [ ] **Step 3: Add contradiction rule helpers in `l2_cognition_store.py`**

Rules to encode first:
- graph exclusivity for one-of-one predicates such as `WORKS_AT` and `LIVES_IN`
- direct negation for preference polarity flips
- state reversal for mood/stress-like traits
- weak tension fallback when evidence is mixed but not decisive

Do not attempt a general ontology engine in this iteration.

- [ ] **Step 4: Implement reconcile workers**

In `backend/src/magi/memory/l2_pipeline.py`:
- load all active/candidate assertions for an entity
- load related graph facts and recent events
- compute support counts and time span per trait/value
- optionally call the LLM reconcile prompt for borderline cases only
- write resulting `validation_state`, confidence, contradiction flags, and touched snapshot fields
- enqueue snapshot refresh when a stable outcome changes

- [ ] **Step 5: Re-run reconcile tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k reconcile -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_pipeline.py backend/src/magi/memory/l2_cognition_store.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: add l2 entity reconcile"
```

### Task 7: Materialize snapshots only from reconciled evidence

**Files:**
- Modify: `backend/src/magi/memory/l2_cognition_store.py`
- Modify: `backend/src/magi/memory/l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`

- [ ] **Step 1: Write failing tests for snapshot materialization**

Cover these cases:
- stable preference leaves populate `preferences`
- multiple food-item preferences can coexist while also deriving an abstract category only when taxonomy support exists
- stress/mood temporary states update `current_*` fields without being treated as permanent traits
- contradicted assertions are removed or revised out of snapshot fields
- `relationship_topology` is built from graph facts, not from raw event text

- [ ] **Step 2: Run the focused snapshot tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k snapshot -v`
Expected: FAIL because snapshot refresh is still tightly coupled to single-assertion updates.

- [ ] **Step 3: Refactor snapshot writes into explicit materialization methods**

In `backend/src/magi/memory/l2_cognition_store.py`:
- add a method that rebuilds one entity snapshot from reconciled assertions + graph summary
- separate stable fields from temporary fields
- support version bumping and source assertion bookkeeping

- [ ] **Step 4: Implement snapshot refresh worker**

In `backend/src/magi/memory/l2_pipeline.py`:
- consume `L2SnapshotRefreshJob`
- rebuild snapshot deterministically
- track last materialization stats

Do not let extraction workers write `tom_snapshots` directly anymore.

- [ ] **Step 5: Re-run snapshot tests**

Run: `cd backend && pytest tests/memory/test_l2_pipeline.py -k snapshot -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l2_cognition_store.py backend/src/magi/memory/l2_pipeline.py backend/tests/memory/test_l2_pipeline.py
git commit -m "feat: materialize l2 snapshots from reconcile"
```

---

## Chunk 4: Manual L2 Lab API And Frontend Controls

### Task 8: Add backend L2 lab endpoints for manual event injection and manual merge

**Files:**
- Modify: `backend/src/magi/api/routers/memory.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/src/magi/memory/l2_entity_catalog.py`
- Test: `backend/tests/memory/test_l2_manual_api.py`

- [ ] **Step 1: Write failing API tests for manual L2 lab actions**

Cover these cases:
- manual event injection writes through the normal unified memory ingestion path
- replay extraction accepts an existing `event_id`
- entity reconcile accepts one or more `entity_id`
- snapshot refresh accepts one or more `entity_id`
- entity listing returns canonical ids and aliases for the frontend picker

- [ ] **Step 2: Run the focused API tests**

Run: `cd backend && pytest tests/memory/test_l2_manual_api.py -v`
Expected: FAIL because the endpoints do not exist.

- [ ] **Step 3: Add API models and endpoints in `backend/src/magi/api/routers/memory.py`**

Add endpoints such as:
- `POST /api/memory/l2/manual-event`
- `POST /api/memory/l2/extract/{event_id}`
- `POST /api/memory/l2/reconcile`
- `POST /api/memory/l2/materialize`
- `GET /api/memory/l2/entities`
- `GET /api/memory/l2/snapshots`

The manual event endpoint should accept enough fields to test safely:
- text
- source
- user id
- session id
- entity focus hint
- cognition toggle
- ToM depth

- [ ] **Step 4: Add helper methods on `UnifiedMemoryStore`**

Expose high-level methods that the router can call without reaching inside queue internals.

- [ ] **Step 5: Re-run API tests**

Run: `cd backend && pytest tests/memory/test_l2_manual_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/api/routers/memory.py backend/src/magi/memory/__init__.py backend/src/magi/memory/l2_entity_catalog.py backend/tests/memory/test_l2_manual_api.py
git commit -m "feat: add l2 manual lab api"
```

### Task 9: Add manual controls to the frontend L2 tab

**Files:**
- Modify: `frontend/src/api/modules/memory.ts`
- Modify: `frontend/src/hooks/useMemory.ts`
- Modify: `frontend/src/components/memory/L2Tab.tsx`
- Modify: `frontend/src/pages/Events.tsx`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Test: `frontend/src/__tests__/l2LabPage.test.tsx`

- [ ] **Step 1: Write failing frontend tests for the L2 lab**

Cover these cases:
- the L2 tab renders a manual event composer
- submitting a manual event calls the new API and refreshes L2 data
- reconcile button calls the manual merge endpoint
- entity picker renders canonical entities from the API
- button labels and toasts use i18n keys instead of hardcoded strings

- [ ] **Step 2: Run the focused frontend test file**

Run: `cd frontend && npm run test -- l2LabPage.test.tsx`
Expected: FAIL because the test file and controls do not exist.

- [ ] **Step 3: Expand the API module and hook**

In `frontend/src/api/modules/memory.ts` add:
- request/response types for manual event, extract replay, reconcile, materialize, entity list, snapshot list
- API methods for those routes

In `frontend/src/hooks/useMemory.ts` add:
- manual event form state
- selected entity ids
- loading flags for inject/reconcile/materialize
- action handlers that refresh L2 state and statistics after success

- [ ] **Step 4: Redesign `frontend/src/components/memory/L2Tab.tsx` as an L2 lab**

Add sections for:
- quick L2 metrics
- manual event composer
- entity picker and manual reconcile/materialize actions
- relations list
- assertions list
- optional snapshot preview panel if data is available

Keep the design aligned with the existing component patterns; do not introduce a separate route.

- [ ] **Step 5: Add i18n keys in both locale files**

Required groups:
- `memory.l2.labTitle`
- `memory.l2.manualEvent`
- `memory.l2.reconcile`
- `memory.l2.materialize`
- `memory.l2.entityPicker`
- success and failure toasts

- [ ] **Step 6: Re-run the focused frontend tests**

Run: `cd frontend && npm run test -- l2LabPage.test.tsx`
Expected: PASS.

- [ ] **Step 7: Run type-check and lint**

Run:
- `cd frontend && npm run type-check`
- `cd frontend && npm run lint`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/modules/memory.ts frontend/src/hooks/useMemory.ts frontend/src/components/memory/L2Tab.tsx frontend/src/pages/Events.tsx frontend/src/i18n/locales/zh-CN/app.json frontend/src/i18n/locales/en/app.json frontend/src/__tests__/l2LabPage.test.tsx
git commit -m "feat: add l2 manual testing workspace"
```

---

## Chunk 5: Verification, Documentation Sync, And Hand-off

### Task 10: Run focused verification and update docs if behavior changed

**Files:**
- Modify: `docs/memory-system-execution-plan.md`
- Modify: `docs/memory-system-design.md`
- Test: `backend/tests/memory/test_l2_entity_catalog.py`
- Test: `backend/tests/memory/test_l2_pipeline.py`
- Test: `backend/tests/memory/test_l2_manual_api.py`
- Test: `frontend/src/__tests__/l2LabPage.test.tsx`
- Test: `frontend/src/__tests__/eventsPage.test.tsx`

- [ ] **Step 1: Re-read the final behavior against root docs**

Check especially:
- L2 is asynchronous after L1
- entity catalog/aliases exist as a practical anti-explosion layer
- assertions coexist by trait/value
- snapshots are materialized from reconcile outputs, not raw events
- the frontend L2 tab now includes manual testing controls

- [ ] **Step 2: Update docs only where implementation semantics changed**

Likely updates:
- `docs/memory-system-design.md` for entity catalog and queue ownership details
- `docs/memory-system-execution-plan.md` to mark the old synchronous snapshot path obsolete

Do not fork the root docs from reality.

- [ ] **Step 3: Run the backend focused suite**

Run:
`cd backend && pytest tests/memory/test_l2_entity_catalog.py tests/memory/test_l2_pipeline.py tests/memory/test_l2_manual_api.py -v`

Expected: PASS.

- [ ] **Step 4: Run the frontend focused suite**

Run:
`cd frontend && npm run test -- l2LabPage.test.tsx eventsPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Run cross-check quality commands**

Run:
- `cd frontend && npm run type-check`
- `cd frontend && npm run lint`
- `cd backend && pytest tests/memory/test_l2_pipeline.py -k "not slow" -v`

If any command cannot run in the environment, capture that explicitly in the execution notes.

- [ ] **Step 6: Commit doc sync and verification fallout**

```bash
git add docs/memory-system-design.md docs/memory-system-execution-plan.md backend/tests/memory/test_l2_entity_catalog.py backend/tests/memory/test_l2_pipeline.py backend/tests/memory/test_l2_manual_api.py frontend/src/__tests__/l2LabPage.test.tsx frontend/src/__tests__/eventsPage.test.tsx
git commit -m "docs: align l2 cognition pipeline plan"
```

---

## Implementation Notes For Workers

### Minimal ontology to freeze before coding

Start with a deliberately small, stable vocabulary.

Entity types:
- `user`
- `person`
- `place`
- `organization`
- `group`
- `food`
- `topic`
- `event`

Graph predicates:
- `LIKES`
- `DISLIKES`
- `WORKS_AT`
- `LIVES_IN`
- `VISITED`
- `INTERACTED_WITH`
- `MEMBER_OF`
- `HAS_PUBLIC_SENTIMENT`

Trait families:
- `stress`
- `mood`
- `engagement`
- `preference`
- `trigger`
- `relationship_shift`
- `public_sentiment`
- `group_atmosphere`

### Reconcile rules to freeze before coding

- Single-event ToM inference cannot exceed low confidence.
- Stable traits require repeated evidence across independent events and sufficient time span.
- Volatile states may update `current_*` snapshot fields without becoming permanent traits.
- Contradiction handling differs by record class:
  - graph facts: `deprecated` or `conflicted`
  - ToM assertions: `contradicted` or downgraded confidence
- Keep leaf preferences and derive abstract categories only when multiple leaf items support the same parent taxonomy.

### Manual lab UX acceptance bar

The L2 tab is acceptable when a tester can do all of the following without leaving the page:
- type a synthetic event and submit it into the normal memory ingestion path
- refresh the page and see resulting relations/assertions
- choose one or more canonical entities
- trigger manual reconcile/merge
- trigger snapshot materialization
- confirm success/failure from visible UI feedback

### Suggested commit cadence

1. `feat: add l2 pipeline contracts`
2. `refactor: queue l2 cognition writes`
3. `feat: add l2 entity catalog`
4. `feat: add l2 llm extraction service`
5. `feat: extract l2 candidates from l1 events`
6. `feat: add l2 entity reconcile`
7. `feat: materialize l2 snapshots from reconcile`
8. `feat: add l2 manual lab api`
9. `feat: add l2 manual testing workspace`
10. `docs: align l2 cognition pipeline plan`

Plan complete and saved to `docs/superpowers/plans/2026-03-17-l2-cognition-write-pipeline.md`. Ready to execute?
