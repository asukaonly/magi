# API And Runtime Process Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the current single-process backend into an API/WebSocket process and a background runtime worker process so L2/L3/L4 and agent execution cannot starve API responsiveness.

**Architecture:** Keep FastAPI as the user-facing transport and read-side surface, and move agent runtime, scheduler execution, memory integration, and background pipelines into a dedicated runtime worker. Replace the current in-process subscriber model with explicit cross-process queue/command channels so delivery semantics stay correct when processes are separated.

**Tech Stack:** FastAPI, Uvicorn, asyncio, aiosqlite, APScheduler, Tauri sidecar packaging, existing Magi bootstrap/runtime modules.

---

## File Structure

**Existing files to modify**
- `backend/src/magi/backend_app.py`
  API app assembly and lifespan ownership.
- `backend/src/magi/bootstrap/backend.py`
  Runtime bootstrap entrypoints; likely split into API-safe and runtime-worker-safe initialization paths.
- `backend/src/magi/bootstrap/builder.py`
  Current all-in-one module graph; needs role-aware builders.
- `backend/src/magi/events/sqlite_backend.py`
  Current subscriber model is process-local and must be replaced or wrapped for cross-process delivery.
- `backend/src/magi/core/runtime_bindings.py`
  Current bindings assume one in-process runtime.
- `backend/src/magi/api/services/message_dispatch_service.py`
  User message dispatch should target the runtime worker explicitly.
- `backend/src/magi/websocket/bridge_lifecycle.py`
  WebSocket push path must no longer depend on local runtime subscriptions.
- `backend/src/magi/memory/integration.py`
  Must run only in runtime worker.
- `backend/src/magi/agent/lifecycle.py`
  Must run only in runtime worker.
- `backend/run_server.py`
  Current launcher only starts the unified app.
- `scripts/build-sidecar.sh`
  Packaging needs to choose which Python entrypoints are bundled.
- `scripts/build-sidecar.ps1`
  Windows sidecar packaging equivalent.

**New files to create**
- `backend/src/magi/process_roles.py`
  Shared enum/config for `api` vs `runtime_worker`.
- `backend/src/magi/backend_runtime_worker.py`
  Dedicated runtime worker entrypoint and lifespan.
- `backend/src/magi/bootstrap/api_builder.py`
  API-safe module builder with no background runtime modules.
- `backend/src/magi/bootstrap/runtime_worker_builder.py`
  Runtime-only module builder.
- `backend/src/magi/events/contracts.py`
  Explicit cross-process queue envelope and command/notification types.
- `backend/src/magi/events/runtime_queue.py`
  Cross-process queue abstraction used by API and runtime worker.
- `backend/src/magi/api/services/runtime_status_service.py`
  Health/readiness surface that reflects runtime worker state.
- `backend/tests/runtime/test_process_role_bootstrap.py`
  Verifies module ownership per process role.
- `backend/tests/events/test_runtime_queue.py`
  Verifies cross-process delivery semantics.
- `backend/tests/api/test_runtime_split_dispatch.py`
  Verifies API dispatches to runtime worker without local runtime bindings.

**Design rules**
- API process owns: HTTP routes, WebSocket connections, static assets, read-side queries, enqueue-only commands, readiness/health endpoints.
- Runtime worker owns: message consumption, router agent, task agents, worker agents, memory integration, scheduler execution, background pipelines, action emission.
- Cross-process interfaces must use explicit persisted queues or commands, not in-memory subscriber lists.

## Chunk 1: Separate Process Roles

### Task 1: Introduce process-role configuration

**Files:**
- Create: `backend/src/magi/process_roles.py`
- Modify: `backend/run_server.py`
- Test: `backend/tests/runtime/test_process_role_bootstrap.py`

- [ ] Define `ProcessRole` with at least `API` and `RUNTIME_WORKER`.
- [ ] Add a small resolver for role selection from CLI/env without changing existing default behavior.
- [ ] Add a failing test that verifies unknown roles are rejected and default role stays API-compatible.
- [ ] Implement the resolver and role enum.
- [ ] Run: `cd backend && pytest tests/runtime/test_process_role_bootstrap.py -v`
- [ ] Commit: `git commit -m "feat: add backend process roles"`

### Task 2: Split bootstrap builders by ownership

**Files:**
- Create: `backend/src/magi/bootstrap/api_builder.py`
- Create: `backend/src/magi/bootstrap/runtime_worker_builder.py`
- Modify: `backend/src/magi/bootstrap/backend.py`
- Modify: `backend/src/magi/bootstrap/builder.py`
- Test: `backend/tests/runtime/test_process_role_bootstrap.py`

- [ ] Write a failing test that asserts the API role does not start agent runtime, memory integration, or scheduler execution modules.
- [ ] Write a failing test that asserts the runtime worker role does start those modules.
- [ ] Implement role-aware module builders instead of one shared all-in runtime graph.
- [ ] Keep existing docs-aligned module ordering inside each role-specific builder.
- [ ] Run: `cd backend && pytest tests/runtime/test_process_role_bootstrap.py -v`
- [ ] Commit: `git commit -m "refactor: split bootstrap by process role"`

## Chunk 2: Replace In-Process Delivery Assumptions

### Task 3: Introduce explicit cross-process runtime queue contracts

**Files:**
- Create: `backend/src/magi/events/contracts.py`
- Create: `backend/src/magi/events/runtime_queue.py`
- Modify: `backend/src/magi/api/services/message_dispatch_service.py`
- Test: `backend/tests/events/test_runtime_queue.py`
- Test: `backend/tests/api/test_runtime_split_dispatch.py`

- [ ] Write a failing test for enqueue/dequeue of a user-message command with explicit target role metadata.
- [ ] Write a failing test proving API dispatch works even when local `require_agent_runtime()` is unavailable.
- [ ] Define queue envelopes for:
  user message command, runtime status heartbeat, worker progress notification, trace notification.
- [ ] Implement a persisted queue abstraction on top of current storage first; do not keep process-local subscriber semantics in the new path.
- [ ] Update API dispatch to enqueue runtime commands instead of requiring in-process runtime bindings.
- [ ] Run: `cd backend && pytest tests/events/test_runtime_queue.py tests/api/test_runtime_split_dispatch.py -v`
- [ ] Commit: `git commit -m "feat: add cross-process runtime queue"`

### Task 4: Remove WebSocket dependence on local runtime subscriptions

**Files:**
- Modify: `backend/src/magi/websocket/bridge_lifecycle.py`
- Modify: `backend/src/magi/websocket/connection_manager.py`
- Modify: `backend/src/magi/api/services/runtime_status_service.py`
- Test: `backend/tests/api/test_runtime_split_dispatch.py`

- [ ] Add a failing test that WebSocket/API process can receive runtime notifications without local task agents running.
- [ ] Refactor bridge lifecycle to consume runtime notifications from the explicit cross-process queue or notification table.
- [ ] Add runtime heartbeat/status surface so `/ready` can reflect API ready and runtime worker ready separately.
- [ ] Run: `cd backend && pytest tests/api/test_runtime_split_dispatch.py -v`
- [ ] Commit: `git commit -m "refactor: decouple websocket bridge from local runtime"`

## Chunk 3: Move Heavy Modules Into Runtime Worker

### Task 5: Create dedicated runtime worker entrypoint

**Files:**
- Create: `backend/src/magi/backend_runtime_worker.py`
- Modify: `backend/run_server.py`
- Modify: `backend/src/magi/backend_app.py`
- Test: `backend/tests/runtime/test_process_role_bootstrap.py`

- [ ] Write a failing test that API process starts without runtime modules and runtime worker starts without transport routes.
- [ ] Implement runtime worker entrypoint with its own lifespan and role-specific bootstrap.
- [ ] Keep API app focused on transport/read side only.
- [ ] Run: `cd backend && pytest tests/runtime/test_process_role_bootstrap.py -v`
- [ ] Commit: `git commit -m "feat: add runtime worker entrypoint"`

### Task 6: Restrict background modules to runtime worker only

**Files:**
- Modify: `backend/src/magi/agent/lifecycle.py`
- Modify: `backend/src/magi/memory/integration.py`
- Modify: `backend/src/magi/scheduler/service.py`
- Modify: `backend/src/magi/core/runtime_bindings.py`
- Test: `backend/tests/runtime/test_process_role_bootstrap.py`

- [ ] Add failing tests that `MemoryIntegrationModule`, `AgentRuntimeModule`, and scheduler execution are not initialized in API role.
- [ ] Move ownership checks into bootstrap/build layer, not scattered ad hoc route guards.
- [ ] Ensure runtime bindings exposed in API role are read-side safe and do not require local task-agent state.
- [ ] Run: `cd backend && pytest tests/runtime/test_process_role_bootstrap.py -v`
- [ ] Commit: `git commit -m "refactor: isolate background modules in runtime worker"`

## Chunk 4: Protect Responsiveness And Packaging

### Task 7: Add runtime heartbeat and degraded-mode UX hooks

**Files:**
- Create: `backend/src/magi/api/services/runtime_status_service.py`
- Modify: `backend/src/magi/websocket/http_app.py`
- Modify: `backend/src/magi/api/routes.py`
- Test: `backend/tests/api/test_runtime_split_dispatch.py`

- [ ] Write a failing test for separate API readiness and runtime readiness states.
- [ ] Expose health fields that distinguish:
  API alive, runtime worker connected, queue backlog healthy.
- [ ] Ensure API can return actionable errors when runtime worker is unavailable instead of timing out.
- [ ] Run: `cd backend && pytest tests/api/test_runtime_split_dispatch.py -v`
- [ ] Commit: `git commit -m "feat: add runtime worker health reporting"`

### Task 8: Update packaging and local dev scripts

**Files:**
- Modify: `scripts/build-sidecar.sh`
- Modify: `scripts/build-sidecar.ps1`
- Modify: `scripts/dev-tauri-hot.sh`
- Modify: `README.md`

- [ ] Decide whether desktop package bundles:
  one supervisor binary launching both roles, or two sidecar binaries.
- [ ] Update build scripts to package the selected topology explicitly.
- [ ] Update local dev scripts so API and runtime worker can be started together.
- [ ] Document startup topology and troubleshooting notes.
- [ ] Validate by building the sidecar package once on the current platform.
- [ ] Commit: `git commit -m "chore: package split backend processes"`

## Open Questions To Resolve Before Implementation

- Should the cross-process queue stay on SQLite for the first cut, or should runtime commands move directly to Redis/PostgreSQL?
- Does the desktop Tauri host supervise both Python roles, or should one Python process supervise the other?
- Should worker progress and trace notifications be queue-based, poll-based, or table-tail based for the first iteration?

## Recommended First Cut

- Keep the first split single-machine only.
- Use one API process and one runtime worker process.
- Reuse SQLite-backed persisted command/notification storage for the first cut, but remove local subscriber assumptions from the new path.
- Do not introduce multiple API workers yet.
- Do not migrate to PostgreSQL in the same project unless queue/write contention remains a measured problem after the split.

## Validation Checklist

- API remains responsive while synthetic L2 workload is running.
- User message POST only enqueues work and does not require local runtime bindings.
- Runtime worker can be restarted independently without killing API availability.
- WebSocket clients still receive worker progress and final responses.
- Desktop sidecar packaging launches the intended process topology successfully.

Plan complete and saved to `docs/superpowers/plans/2026-03-21-api-runtime-split.md`. Ready to execute?
