# Timeline Projection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild timeline as a lazy-generated time projection over `L1 + L3`, with cacheable projection items and no timeline-first fact storage semantics.

**Architecture:** Add a dedicated timeline projection layer on the backend that reads canonical memory data, builds `event` and `summary` items for a requested time window, and caches them in a projection table. Replace the current timeline page read path to consume projection items instead of timeline-native events, then converge timeline sensor/manual-entry flows onto canonical memory writes rather than timeline-specific raw storage.

**Tech Stack:** Python 3.10+, FastAPI, aiosqlite, React 18, TypeScript, TanStack Query, Vitest, Testing Library

---

## File Map

### Backend

- Create: `backend/src/magi/timeline/projection_models.py`
  Define projection DTOs, item types, and cache-key helpers.
- Create: `backend/src/magi/timeline/projection_store.py`
  Persist and load lazy-generated timeline projection items.
- Create: `backend/src/magi/timeline/projection_builder.py`
  Build timeline items from `L1 + L3` for a requested time window.
- Modify: `backend/src/magi/timeline/service.py`
  Replace event-feed semantics with query/build/cache orchestration.
- Modify: `backend/src/magi/api/routers/timeline.py`
  Add projection-oriented list/detail endpoints and retire event-feed assumptions from the timeline page path.
- Modify: `backend/src/magi/timeline/handler.py`
  Remove new-path reliance on timeline-first writes and route timeline source payloads into canonical memory writes.
- Modify: `backend/src/magi/timeline/contracts.py`
  Narrow contracts to projection-safe payloads or split projection contracts from source-ingest contracts if needed.
- Modify: `backend/src/magi/memory/l1/event_store.py`
  Add any targeted query helpers needed by the projection builder for time-window reads.

### Frontend

- Modify: `frontend/src/api/modules/timeline.ts`
  Consume projection-oriented timeline responses.
- Modify: `frontend/src/pages/Timeline.tsx`
  Replace event-native page assumptions with projection-window loading.
- Modify: `frontend/src/components/timeline/TimelineFeed.tsx`
  Render `event` and `summary` projection items.
- Modify: `frontend/src/components/timeline/TimelineComposer.tsx`
  Keep manual journal creation only if it now writes canonical memory events; otherwise remove timeline-only assumptions.

### Tests

- Create: `backend/tests/timeline/test_timeline_projection_store.py`
- Create: `backend/tests/timeline/test_timeline_projection_builder.py`
- Modify: `backend/tests/api/test_timeline_api.py`
- Modify: `backend/tests/timeline/test_timeline_runtime_bridge.py`
- Modify: `frontend/src/__tests__/timelinePage.test.tsx`

## Chunk 1: Build The Projection Foundation

### Task 1: Codify the projection contracts and persistence layer

**Files:**
- Create: `backend/src/magi/timeline/projection_models.py`
- Create: `backend/src/magi/timeline/projection_store.py`
- Test: `backend/tests/timeline/test_timeline_projection_store.py`

- [ ] **Step 1: Write the failing projection-store tests**

Cover:
- saving projection items for one `window_key`
- reading cached items back in `sort_time DESC`
- invalidating a cached window by `window_key + filter_hash + projection_version`

- [ ] **Step 2: Run the focused backend test to verify red**

Run: `cd backend && pytest tests/timeline/test_timeline_projection_store.py -v`
Expected: FAIL because the projection store and models do not exist yet.

- [ ] **Step 3: Implement projection DTOs and SQLite store**

Add:
- timeline item type enum or literals for `event` and `summary`
- cache-key helpers for `window_key`, `filter_hash`, and `projection_version`
- a SQLite-backed projection store for save/load/invalidate operations

- [ ] **Step 4: Re-run the focused test to verify green**

Run: `cd backend && pytest tests/timeline/test_timeline_projection_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/projection_models.py backend/src/magi/timeline/projection_store.py backend/tests/timeline/test_timeline_projection_store.py
git commit -m "feat: add timeline projection store"
```

### Task 2: Build the lazy projection builder over `L1 + L3`

**Files:**
- Create: `backend/src/magi/timeline/projection_builder.py`
- Modify: `backend/src/magi/memory/l1/event_store.py`
- Test: `backend/tests/timeline/test_timeline_projection_builder.py`

- [ ] **Step 1: Write the failing builder tests**

Cover:
- a window with only `L1` events yields `event` items
- a window with overlapping `L3` summaries yields `summary` items
- all projection items preserve `source_event_ids` or `source_summary_ids`

- [ ] **Step 2: Run the focused backend test to verify red**

Run: `cd backend && pytest tests/timeline/test_timeline_projection_builder.py -v`
Expected: FAIL because the projection builder does not exist yet.

- [ ] **Step 3: Implement the projection builder**

Implement:
- time-window loading from `L1`
- overlap loading from `L3`
- initial projection rules for `event` and `summary`
- stable `sort_time` computation

- [ ] **Step 4: Add or refine any narrow L1 query helpers needed by the builder**

Keep the helper surface small and focused on time-window reads rather than generic timeline semantics.

- [ ] **Step 5: Re-run the focused backend test to verify green**

Run: `cd backend && pytest tests/timeline/test_timeline_projection_builder.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/timeline/projection_builder.py backend/src/magi/memory/l1/event_store.py backend/tests/timeline/test_timeline_projection_builder.py
git commit -m "feat: add timeline projection builder"
```

## Chunk 2: Switch The Timeline Read Path To Projection Items

### Task 3: Rework TimelineService into query/build/cache orchestration

**Files:**
- Modify: `backend/src/magi/timeline/service.py`
- Modify: `backend/src/magi/timeline/__init__.py`
- Modify: `backend/tests/timeline/test_timeline_runtime_bridge.py`

- [ ] **Step 1: Write the failing service tests**

Cover:
- cache hit returns stored projection items without rebuilding
- cache miss builds from `L1 + L3`, stores the items, and returns them
- timeline service no longer depends on timeline-native raw event listing for the page feed

- [ ] **Step 2: Run the focused backend test to verify red**

Run: `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py -v`
Expected: FAIL because the service still exposes timeline-event semantics.

- [ ] **Step 3: Implement the new service flow**

Wire:
- projection store
- projection builder
- window normalization
- cache lookup and lazy regeneration

- [ ] **Step 4: Re-run the focused backend test to verify green**

Run: `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/service.py backend/src/magi/timeline/__init__.py backend/tests/timeline/test_timeline_runtime_bridge.py
git commit -m "refactor: switch timeline service to projections"
```

### Task 4: Replace the timeline API with projection-oriented responses

**Files:**
- Modify: `backend/src/magi/api/routers/timeline.py`
- Modify: `backend/tests/api/test_timeline_api.py`

- [ ] **Step 1: Write the failing API tests**

Cover:
- listing timeline data by time window returns projection items
- returned payload distinguishes `event` and `summary`
- cache rebuild is transparent to the API caller

- [ ] **Step 2: Run the focused API test to verify red**

Run: `cd backend && pytest tests/api/test_timeline_api.py -v`
Expected: FAIL because the router still returns timeline-event feed payloads.

- [ ] **Step 3: Implement the projection API changes**

Update:
- request parameters for time windows
- response schema for projection items
- any detail endpoint assumptions that still expect timeline-native event rows

- [ ] **Step 4: Re-run the focused API test to verify green**

Run: `cd backend && pytest tests/api/test_timeline_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/api/routers/timeline.py backend/tests/api/test_timeline_api.py
git commit -m "feat: expose timeline projection api"
```

### Task 5: Update the frontend page to render projection items

**Files:**
- Modify: `frontend/src/api/modules/timeline.ts`
- Modify: `frontend/src/pages/Timeline.tsx`
- Modify: `frontend/src/components/timeline/TimelineFeed.tsx`
- Test: `frontend/src/__tests__/timelinePage.test.tsx`

- [ ] **Step 1: Write the failing frontend test**

Cover:
- loading a windowed projection response
- rendering both `event` and `summary` items
- preserving empty/loading/error behavior on the new API contract

- [ ] **Step 2: Run the focused frontend test to verify red**

Run: `cd frontend && npm run test -- src/__tests__/timelinePage.test.tsx`
Expected: FAIL because the page still expects timeline-event records.

- [ ] **Step 3: Update the timeline API client and page state model**

Introduce projection-aware types and window query parameters.

- [ ] **Step 4: Refactor `TimelineFeed` to render projection items**

Support:
- event cards backed by `primary_event_id`
- summary cards backed by `source_summary_ids`

- [ ] **Step 5: Re-run the focused frontend test to verify green**

Run: `cd frontend && npm run test -- src/__tests__/timelinePage.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/modules/timeline.ts frontend/src/pages/Timeline.tsx frontend/src/components/timeline/TimelineFeed.tsx frontend/src/__tests__/timelinePage.test.tsx
git commit -m "feat: render timeline projections"
```

## Chunk 3: Remove Timeline-First Fact Semantics

### Task 6: Converge timeline ingest paths onto canonical memory writes

**Files:**
- Modify: `backend/src/magi/timeline/handler.py`
- Modify: `backend/src/magi/timeline/contracts.py`
- Modify: `backend/src/magi/timeline/service.py`
- Modify: `frontend/src/components/timeline/TimelineComposer.tsx`
- Test: `backend/tests/timeline/test_timeline_runtime_bridge.py`

- [ ] **Step 1: Write the failing convergence tests**

Cover:
- new timeline source payload handling writes canonical memory events rather than timeline-native raw facts
- chat no longer needs a timeline-specific copy to appear on the timeline page
- manual timeline creation, if retained, writes a memory-native manual journal event

- [ ] **Step 2: Run the focused backend test to verify red**

Run: `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py -v`
Expected: FAIL because the handler still assumes timeline-first storage.

- [ ] **Step 3: Implement the ingest convergence**

Change the new-path flow so that:
- source payloads become canonical memory writes
- timeline page visibility comes only from later projection building
- any manual entry UI uses the same memory-native write path

- [ ] **Step 4: Re-run the focused backend test to verify green**

Run: `cd backend && pytest tests/timeline/test_timeline_runtime_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/handler.py backend/src/magi/timeline/contracts.py backend/src/magi/timeline/service.py frontend/src/components/timeline/TimelineComposer.tsx backend/tests/timeline/test_timeline_runtime_bridge.py
git commit -m "refactor: remove timeline-first ingest path"
```

### Task 7: Final regression verification

**Files:**
- Test: `backend/tests/api/test_timeline_api.py`
- Test: `backend/tests/timeline/test_timeline_projection_store.py`
- Test: `backend/tests/timeline/test_timeline_projection_builder.py`
- Test: `backend/tests/timeline/test_timeline_runtime_bridge.py`
- Test: `frontend/src/__tests__/timelinePage.test.tsx`

- [ ] **Step 1: Run focused backend timeline coverage**

Run: `cd backend && pytest tests/api/test_timeline_api.py tests/timeline/test_timeline_projection_store.py tests/timeline/test_timeline_projection_builder.py tests/timeline/test_timeline_runtime_bridge.py -v`
Expected: PASS

- [ ] **Step 2: Run focused frontend timeline coverage**

Run: `cd frontend && npm run test -- src/__tests__/timelinePage.test.tsx`
Expected: PASS

- [ ] **Step 3: Run backend full test smoke**

Run: `cd backend && pytest`
Expected: PASS, or only pre-existing unrelated failures documented separately.

- [ ] **Step 4: Run frontend type-check**

Run: `cd frontend && npm run type-check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests frontend/src/__tests__/timelinePage.test.tsx
git commit -m "test: verify timeline projection flow"
```
