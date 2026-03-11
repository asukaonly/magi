# Personal Knowledge Timeline Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 1 of Personal Knowledge Timeline so Magi can ingest chat, manual journal, browser history, and photo-library activity into a unified timeline, configurable retention pipeline, and user knowledge graph.

**Architecture:** Extend the existing runtime instead of creating a parallel service. Add a `TimelineTaskAgent`, a shared timeline domain package, timeline-aware sensor contracts, a timeline-specific API surface, and a routed timeline UI that reuses the current shell. Persist timeline facts in L1-compatible storage, write normalized user-graph edges into a new L2 user graph store, and keep retention and insight processing as delegated services rather than agent-owned logic.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, aiosqlite, existing Magi runtime/task-agent framework, React 18, TypeScript, React Router 6, Zustand, Vitest, Testing Library.

---

## Spec Reference

- Spec: `docs/superpowers/specs/2026-03-11-personal-knowledge-timeline-design.md`

## Scope Guard

This plan is intentionally limited to Phase 1. Do not include:
- social media connectors
- shopping connectors
- voice journal
- calendar view
- graph-first visualization page
- L2 agent reasoning graph
- full rebuild/delete tooling beyond per-source resync and per-event reanalysis hooks

## File Structure Map

### Backend domain and runtime

- Create: `backend/src/magi/timeline/__init__.py`
- Create: `backend/src/magi/timeline/contracts.py`
- Create: `backend/src/magi/timeline/service.py`
- Create: `backend/src/magi/timeline/retention.py`
- Create: `backend/src/magi/timeline/insight_pipeline.py`
- Create: `backend/src/magi/timeline/sensors/__init__.py`
- Create: `backend/src/magi/timeline/sensors/base.py`
- Create: `backend/src/magi/timeline/sensors/chat.py`
- Create: `backend/src/magi/timeline/sensors/manual_journal.py`
- Create: `backend/src/magi/timeline/sensors/browser_history.py`
- Create: `backend/src/magi/timeline/sensors/photo_library.py`
- Create: `backend/src/magi/agent/task_agents/timeline_task_agent.py`
- Create: `backend/src/magi/agent/task_agents/timeline/__init__.py`
- Create: `backend/src/magi/agent/task_agents/timeline/contracts.py`
- Create: `backend/src/magi/agent/task_agents/timeline/fact_classifier.py`
- Create: `backend/src/magi/agent/task_agents/timeline/coordinator.py`
- Create: `backend/src/magi/memory/l2_user_graph.py`

### Backend integration points

- Modify: `backend/src/magi/core/runtime/types.py`
- Modify: `backend/src/magi/core/runtime/task_agent_manager.py`
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: `backend/src/magi/agent/task_agents/__init__.py`
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/api/routers/config.py`
- Modify: `backend/src/magi/api/routers/memory.py`
- Create: `backend/src/magi/api/routers/timeline.py`
- Modify: `backend/src/magi/api/routers/__init__.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Modify: `backend/src/magi/memory/raw_event_store.py`

### Frontend

- Create: `frontend/src/api/modules/timeline.ts`
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/pages/Timeline.tsx`
- Create: `frontend/src/components/timeline/TimelineFeed.tsx`
- Create: `frontend/src/components/timeline/TimelineComposer.tsx`
- Create: `frontend/src/components/settings/TimelineSourcesSection.tsx`
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/stores/chat-shell.ts`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/api/modules/config.ts`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`

### Tests

- Create: `backend/tests/test_timeline_task_agent.py`
- Create: `backend/tests/test_timeline_api.py`
- Create: `backend/tests/test_timeline_sensors.py`
- Create: `backend/tests/test_user_graph_store.py`
- Modify: `backend/tests/test_memory_layers.py`
- Modify: `backend/tests/test_config_api.py`
- Modify: `backend/tests/test_router_agent_loop.py`
- Create: `frontend/src/__tests__/timelinePage.test.tsx`
- Modify: `frontend/src/__tests__/sidebarNavigation.test.tsx`
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
- Modify: `frontend/src/__tests__/chatShell.test.tsx`

## Chunk 1: Runtime and L1 Foundation

### Task 1: Define the timeline domain contract

**Files:**
- Create: `backend/src/magi/timeline/contracts.py`
- Create: `backend/src/magi/timeline/__init__.py`
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/api/routers/config.py`
- Modify: `frontend/src/api/modules/config.ts`

- [ ] **Step 1: Write the failing backend contract/config tests**

Add tests that assert:
- timeline source config exists in backend config models
- per-source retention mode is serialized
- edge whitelist defaults are source-specific

Run: `python -m pytest backend/tests/test_config_api.py -k timeline -v`
Expected: FAIL because timeline config models do not exist yet.

- [ ] **Step 2: Add backend timeline config models**

Implement source-level config models with fields for:
- `enabled`
- `sync_mode`
- `sync_interval_minutes`
- `default_retention_mode`
- `storage_mode`
- `source_path`
- `fetch_page_content`
- `edge_whitelist`

Add them under `AppConfig` in a dedicated timeline section instead of hiding them in tools or generic memory config.

- [ ] **Step 3: Add frontend config types**

Mirror the backend models in `frontend/src/api/modules/config.ts` and extend `DEFAULT_SYSTEM_CONFIG` with a `timeline` section so forms can render without null checks.

- [ ] **Step 4: Run targeted tests**

Run: `python -m pytest backend/tests/test_config_api.py -v`
Expected: PASS with timeline config included in update paths and template payloads.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/config/models.py backend/src/magi/api/routers/config.py frontend/src/api/modules/config.ts backend/tests/test_config_api.py
git commit -m "feat: add timeline source configuration"
```

### Task 2: Introduce runtime support for TimelineTaskAgent

**Files:**
- Modify: `backend/src/magi/core/runtime/types.py`
- Modify: `backend/src/magi/core/runtime/task_agent_manager.py`
- Modify: `backend/src/magi/runtime/bootstrap.py`
- Modify: `backend/src/magi/agent/task_agents/__init__.py`
- Create: `backend/src/magi/agent/task_agents/timeline_task_agent.py`
- Create: `backend/src/magi/agent/task_agents/timeline/__init__.py`
- Create: `backend/src/magi/agent/task_agents/timeline/contracts.py`
- Create: `backend/src/magi/agent/task_agents/timeline/fact_classifier.py`
- Create: `backend/src/magi/agent/task_agents/timeline/coordinator.py`
- Test: `backend/tests/test_timeline_task_agent.py`
- Test: `backend/tests/test_router_agent_loop.py`

- [ ] **Step 1: Write runtime dispatch tests**

Add tests that assert:
- `TaskAgentType` includes `TIMELINE`
- `TaskAgentManager` can instantiate a timeline agent
- timeline facts route to the timeline agent without affecting chat dispatch

Run: `python -m pytest backend/tests/test_timeline_task_agent.py backend/tests/test_router_agent_loop.py -v`
Expected: FAIL because timeline runtime wiring does not exist.

- [ ] **Step 2: Implement TimelineTaskAgent**

Follow the existing chat/explore structure:
- define a small timeline fact classifier
- add a coordinator that delegates to the timeline service
- keep the task agent orchestration-focused, not source-logic-heavy

Use explicit fact payloads so browser/photo/manual/chat events do not arrive as ad hoc dicts.

- [ ] **Step 3: Wire the agent into bootstrap**

Update runtime bootstrap so:
- a timeline agent factory is available
- `TaskAgentManager` can create timeline instances
- the timeline agent receives shared runtime dependencies such as config, unified memory, and timeline services

- [ ] **Step 4: Re-run runtime tests**

Run: `python -m pytest backend/tests/test_timeline_task_agent.py backend/tests/test_router_agent_loop.py -v`
Expected: PASS with timeline facts dispatching correctly.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/core/runtime/types.py backend/src/magi/core/runtime/task_agent_manager.py backend/src/magi/runtime/bootstrap.py backend/src/magi/agent/task_agents/__init__.py backend/src/magi/agent/task_agents/timeline_task_agent.py backend/src/magi/agent/task_agents/timeline backend/tests/test_timeline_task_agent.py backend/tests/test_router_agent_loop.py
git commit -m "feat: add timeline task agent runtime"
```

### Task 3: Make L1 timeline-aware without breaking existing callers

**Files:**
- Modify: `backend/src/magi/memory/raw_event_store.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Create: `backend/src/magi/timeline/service.py`
- Test: `backend/tests/test_memory_layers.py`

- [ ] **Step 1: Write failing storage tests**

Add tests that store a timeline event and assert:
- `occurred_at` and `captured_at` survive persistence
- `retention_mode`, `raw_payload_ref`, `content_blocks`, and `processing_status` are retrievable
- existing generic event listing still works

Run: `python -m pytest backend/tests/test_memory_layers.py -k timeline -v`
Expected: FAIL because timeline-specific fields are not persisted or surfaced yet.

- [ ] **Step 2: Extend RawEventStore for timeline facts**

Persist timeline-specific payload and metadata in a stable way. Keep the existing event-store table usable by current endpoints, but add a clean serialization path for `TimelineEvent` records so timeline APIs do not parse arbitrary JSON by hand.

- [ ] **Step 3: Add a timeline service facade**

Introduce `backend/src/magi/timeline/service.py` to provide:
- idempotent timeline event upsert
- list/query helpers for timeline APIs
- manual journal creation
- per-event reanalysis entrypoints

- [ ] **Step 4: Run storage tests**

Run: `python -m pytest backend/tests/test_memory_layers.py -v`
Expected: PASS with timeline facts stored in L1-compatible storage.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/raw_event_store.py backend/src/magi/memory/__init__.py backend/src/magi/timeline/service.py backend/tests/test_memory_layers.py
git commit -m "feat: add timeline event storage foundation"
```

## Chunk 2: Sensors, Retention, and Timeline APIs

### Task 4: Build the timeline sensor contract and first-party sensors

**Files:**
- Create: `backend/src/magi/timeline/sensors/base.py`
- Create: `backend/src/magi/timeline/sensors/chat.py`
- Create: `backend/src/magi/timeline/sensors/manual_journal.py`
- Create: `backend/src/magi/timeline/sensors/browser_history.py`
- Create: `backend/src/magi/timeline/sensors/photo_library.py`
- Create: `backend/src/magi/timeline/sensors/__init__.py`
- Create: `backend/tests/test_timeline_sensors.py`

- [ ] **Step 1: Write failing sensor tests**

Cover:
- discover/fetch/build flow for each sensor
- source-specific identity and fingerprint behavior
- browser history secondary fetch gate
- photo library path-scoping validation

Run: `python -m pytest backend/tests/test_timeline_sensors.py -v`
Expected: FAIL because no timeline sensor contract exists yet.

- [ ] **Step 2: Implement the base sensor contract**

Define the shared interface with:
- declared capabilities
- update-key metadata
- `discover_changes`
- `fetch_item`
- `build_timeline_event`
- `resolve_retention_assets`
- `extract_candidates`

- [ ] **Step 3: Implement the four Phase 1 sensors**

Rules:
- chat sensor only forwards normalized conversation facts
- manual journal sensor accepts API-created entries and normalizes them
- browser sensor starts with metadata ingestion and optional secondary fetch
- photo sensor works only against explicitly configured local directories

- [ ] **Step 4: Run sensor tests**

Run: `python -m pytest backend/tests/test_timeline_sensors.py -v`
Expected: PASS with deterministic identities, fingerprints, and source policies.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/sensors backend/tests/test_timeline_sensors.py
git commit -m "feat: add timeline source sensors"
```

### Task 5: Implement retention handling and timeline API routes

**Files:**
- Create: `backend/src/magi/timeline/retention.py`
- Create: `backend/src/magi/api/routers/timeline.py`
- Modify: `backend/src/magi/api/routers/__init__.py`
- Modify: `backend/src/magi/api/routers/memory.py`
- Create: `backend/tests/test_timeline_api.py`

- [ ] **Step 1: Write failing API tests**

Cover endpoints for:
- listing timeline events with filters
- creating manual journal entries
- returning event details with retention metadata
- exposing source status and sync errors

Run: `python -m pytest backend/tests/test_timeline_api.py -v`
Expected: FAIL because timeline endpoints do not exist.

- [ ] **Step 2: Implement the retention service**

Support:
- `retain_raw`
- `analyze_only`
- managed-local-file references
- external-path references
- audit metadata showing what was retained versus skipped

Do not copy large photo assets into the database; keep only file references plus any explicitly retained derived files.

- [ ] **Step 3: Add timeline API routes**

Expose endpoints for:
- timeline feed query
- timeline detail query
- manual entry creation
- source status read
- source sync trigger
- event reanalysis trigger

Keep existing memory endpoints for generic L1-L5 inspection, but add timeline-specific routes instead of overloading `/memory/l1/events` for the new UI.

- [ ] **Step 4: Run API tests**

Run: `python -m pytest backend/tests/test_timeline_api.py backend/tests/test_memory_layers.py -v`
Expected: PASS with timeline API payloads backed by the new service.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/retention.py backend/src/magi/api/routers/timeline.py backend/src/magi/api/routers/__init__.py backend/src/magi/api/routers/memory.py backend/tests/test_timeline_api.py
git commit -m "feat: add timeline api and retention service"
```

## Chunk 3: L2 User Graph and Insight Processing

### Task 6: Replace event-relation assumptions with a user graph store

**Files:**
- Create: `backend/src/magi/memory/l2_user_graph.py`
- Modify: `backend/src/magi/memory/__init__.py`
- Create: `backend/tests/test_user_graph_store.py`
- Modify: `backend/tests/test_memory_layers.py`

- [ ] **Step 1: Write failing graph tests**

Cover:
- node and edge upsert
- edge evidence aggregation
- source-type distribution tracking
- prevention of duplicate evidence on reprocessing
- filtering by edge type

Run: `python -m pytest backend/tests/test_user_graph_store.py -v`
Expected: FAIL because user-graph storage does not exist.

- [ ] **Step 2: Implement `L2UserGraphStore`**

Model:
- typed user-centric nodes
- finite edge types
- evidence arrays keyed by event id
- first/last observed timestamps
- confidence and source distributions

Do not model event-to-event chains here.

- [ ] **Step 3: Integrate unified memory**

Update `UnifiedMemoryStore` so timeline writes can:
- upsert user-graph nodes and edges
- query graph statistics for timeline read APIs
- keep current L3/L4 flow intact

- [ ] **Step 4: Run graph and memory tests**

Run: `python -m pytest backend/tests/test_user_graph_store.py backend/tests/test_memory_layers.py -v`
Expected: PASS with user-graph evidence stable across repeated writes.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2_user_graph.py backend/src/magi/memory/__init__.py backend/tests/test_user_graph_store.py backend/tests/test_memory_layers.py
git commit -m "feat: add timeline user graph memory layer"
```

### Task 7: Add the insight pipeline and event-type edge whitelists

**Files:**
- Create: `backend/src/magi/timeline/insight_pipeline.py`
- Modify: `backend/src/magi/timeline/service.py`
- Modify: `backend/src/magi/timeline/sensors/base.py`
- Modify: `backend/src/magi/timeline/sensors/chat.py`
- Modify: `backend/src/magi/timeline/sensors/manual_journal.py`
- Modify: `backend/src/magi/timeline/sensors/browser_history.py`
- Modify: `backend/src/magi/timeline/sensors/photo_library.py`
- Modify: `backend/tests/test_timeline_sensors.py`
- Modify: `backend/tests/test_timeline_api.py`

- [ ] **Step 1: Write failing pipeline tests**

Add tests that assert:
- candidate relations are normalized into finite edge types
- per-source edge whitelist enforcement blocks invalid edges
- expert-mode override flows through config without allowing unrestricted edges
- event detail responses include graph-evidence references

Run: `python -m pytest backend/tests/test_timeline_sensors.py backend/tests/test_timeline_api.py -k edge -v`
Expected: FAIL because there is no normalization pipeline or whitelist enforcement.

- [ ] **Step 2: Implement the insight pipeline**

Stages:
- entity extraction
- relation candidate extraction
- relation normalization
- whitelist filtering
- L2 upsert
- L3/L4 enqueue/update

Keep the pipeline deterministic at the contract boundary even if downstream extraction uses LLM-backed helpers later.

- [ ] **Step 3: Connect pipeline execution to timeline service**

Ensure:
- manual reanalysis reuses the same pipeline
- partial failures update processing status instead of dropping the event
- event detail APIs return enough evidence to explain inferred relations

- [ ] **Step 4: Run pipeline tests**

Run: `python -m pytest backend/tests/test_timeline_sensors.py backend/tests/test_timeline_api.py backend/tests/test_user_graph_store.py -v`
Expected: PASS with source-specific edge enforcement and explainable evidence.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/timeline/insight_pipeline.py backend/src/magi/timeline/service.py backend/src/magi/timeline/sensors backend/tests/test_timeline_sensors.py backend/tests/test_timeline_api.py backend/tests/test_user_graph_store.py
git commit -m "feat: add timeline insight pipeline"
```

## Chunk 4: Timeline UI, Settings, and Final Verification

### Task 8: Add routed timeline navigation and shell state

**Files:**
- Modify: `frontend/src/router/index.tsx`
- Modify: `frontend/src/stores/chat-shell.ts`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/components/layout/Header.tsx`
- Modify: `frontend/src/pages/Chat.tsx`
- Modify: `frontend/src/__tests__/chatShell.test.tsx`
- Modify: `frontend/src/__tests__/sidebarNavigation.test.tsx`

- [ ] **Step 1: Write failing shell tests**

Add tests that assert:
- `/timeline` resolves to a shell panel state
- sidebar and header render a timeline entry
- opening timeline navigates without opening a drawer or dialog

Run: `cd frontend && npm run test -- chatShell.test.tsx sidebarNavigation.test.tsx`
Expected: FAIL because timeline shell state and navigation do not exist.

- [ ] **Step 2: Add timeline route and shell state**

Implement:
- new `/timeline` route
- `ChatPanelType` extension for `timeline`
- header/sidebar buttons
- `panelByPathname('/timeline') === 'timeline'`

Do not keep timeline inside the chat page dialog system.

- [ ] **Step 3: Update chat page behavior**

Ensure chat-only overlays remain for legacy pages while `/timeline` renders as a proper page in the shell.

- [ ] **Step 4: Run shell tests**

Run: `cd frontend && npm run test -- chatShell.test.tsx sidebarNavigation.test.tsx`
Expected: PASS with timeline navigation behaving like a first-class route.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/router/index.tsx frontend/src/stores/chat-shell.ts frontend/src/components/layout/Sidebar.tsx frontend/src/components/layout/Header.tsx frontend/src/pages/Chat.tsx frontend/src/__tests__/chatShell.test.tsx frontend/src/__tests__/sidebarNavigation.test.tsx
git commit -m "feat: add timeline route to app shell"
```

### Task 9: Build the timeline page and manual journal composer

**Files:**
- Create: `frontend/src/api/modules/timeline.ts`
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/pages/Timeline.tsx`
- Create: `frontend/src/components/timeline/TimelineFeed.tsx`
- Create: `frontend/src/components/timeline/TimelineComposer.tsx`
- Modify: `frontend/src/i18n/locales/en/app.json`
- Modify: `frontend/src/i18n/locales/zh-CN/app.json`
- Create: `frontend/src/__tests__/timelinePage.test.tsx`

- [ ] **Step 1: Write failing page tests**

Cover:
- feed rendering from API data
- inline expansion of event details
- source filters
- manual entry composer for text + image
- event retention badge and derived-evidence section

Run: `cd frontend && npm run test -- timelinePage.test.tsx`
Expected: FAIL because the timeline page and API module do not exist.

- [ ] **Step 2: Implement timeline API bindings**

Add typed client methods for:
- list events
- get event detail
- create manual entry
- request resync
- request reanalysis

- [ ] **Step 3: Build the page and components**

Requirements:
- feed-first layout
- inline detail expansion
- top controls for range/filter/view mode
- no modal-based detail flow
- manual entry uses the same event shape as passive events

- [ ] **Step 4: Run timeline page tests**

Run: `cd frontend && npm run test -- timelinePage.test.tsx`
Expected: PASS with stable rendering and composer interactions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/modules/timeline.ts frontend/src/api/index.ts frontend/src/pages/Timeline.tsx frontend/src/components/timeline frontend/src/i18n/locales/en/app.json frontend/src/i18n/locales/zh-CN/app.json frontend/src/__tests__/timelinePage.test.tsx
git commit -m "feat: add timeline page and journal composer"
```

### Task 10: Add source settings and run final verification

**Files:**
- Create: `frontend/src/components/settings/TimelineSourcesSection.tsx`
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/__tests__/settingsPage.test.tsx`
- Modify: `backend/tests/test_config_api.py`
- Modify: `backend/tests/test_timeline_api.py`
- Modify: `docs/superpowers/specs/2026-03-11-personal-knowledge-timeline-design.md` only if implementation required spec corrections are discovered

- [ ] **Step 1: Write failing settings tests**

Cover:
- per-source enable/disable
- retention mode selection
- interval editing
- browser secondary fetch toggle
- expert-mode edge whitelist controls
- source error/status display

Run: `cd frontend && npm run test -- settingsPage.test.tsx`
Expected: FAIL because timeline source settings are not rendered.

- [ ] **Step 2: Implement settings UI**

Add a dedicated `Timeline & Sources` section instead of scattering controls across memory and tools.

Keep quick mode simple:
- show core toggles and retention defaults

Keep expert mode richer:
- show update-key and edge-whitelist controls

- [ ] **Step 3: Run full targeted verification**

Run:

```bash
python -m pytest backend/tests/test_config_api.py backend/tests/test_timeline_task_agent.py backend/tests/test_timeline_api.py backend/tests/test_timeline_sensors.py backend/tests/test_user_graph_store.py backend/tests/test_memory_layers.py backend/tests/test_router_agent_loop.py -v
cd frontend && npm run test -- chatShell.test.tsx sidebarNavigation.test.tsx settingsPage.test.tsx timelinePage.test.tsx
cd frontend && npm run type-check
```

Expected:
- backend tests PASS
- frontend tests PASS
- type-check PASS

- [ ] **Step 4: Update docs if needed**

Only if implementation clarified a real mismatch, patch the spec and note the change in the final commit body. Do not silently drift from the approved design.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/settings/TimelineSourcesSection.tsx frontend/src/pages/Settings.tsx frontend/src/__tests__/settingsPage.test.tsx backend/tests/test_config_api.py backend/tests/test_timeline_api.py
git commit -m "feat: add timeline source settings"
```

## Notes for the Implementer

- Reuse existing task-agent patterns from chat/explore instead of inventing a third style.
- Keep timeline sensors source-specific and small; do not put browser/photo parsing logic inside `TimelineTaskAgent`.
- Do not add a second timeline-only drawer system in the frontend.
- Keep evidence links first-class in API responses and UI rendering. Explainability is a product requirement, not a nice-to-have.
- Use source-type-specific edge whitelists as a hard filter before writing L2 edges.
- Keep raw asset references out of embedding payloads and out of L1 binary storage.

## Suggested Follow-Up Plans

Create separate plans after this one ships for:
- Phase 2 connectors and data governance
- Phase 3 agent-internal graph
