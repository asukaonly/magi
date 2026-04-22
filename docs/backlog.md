# Magi Backlog

This document tracks current development and maintenance follow-ups that are still open after the latest architecture cleanup.

It is intentionally separate from the stable design docs.

## Active Development

### 1. Persona registry migration and frontend integration

Status: active

Why it is still open:

- The persona registry backend (PersonaRepository, seed service, evolution engine persona_id scoping, `/api/personas/*` routes) is implemented and tested.
- The frontend still uses filename-based persona identity via the old `/api/personality/*` routes.
- Onboarding flow needs to call the seed endpoint and select a persona from the registry instead of copying preset files.

Remaining work:

- Wire onboarding frontend to call `POST /api/personas/seed` and `PUT /api/personas/active` instead of file-copy approach.
- Migrate `PersonalityModern.tsx` and `personalityApi` to use `/api/personas/*` routes with persona_id.
- Add data migration script to import existing file-based personas into the registry for existing installs.
- Retire `current_state.py` filesystem approach once frontend is fully migrated.

### 2. Finish the lifecycle-based memory implementation

Status: active

Why it is still open:

- the lifecycle model is documented and partially implemented, but the subsystem plan still contains unfinished phases
- retrieval, prompt integration, API cleanup, and some legacy memory-module removal work are still open in the implementation backlog

Current focus areas:

- complete the remaining L2/L3/L4 implementation work
- finish retrieval and prompt integration against the lifecycle model
- remove superseded legacy memory modules once the new path fully owns production behavior

### 3. Continue runtime boundary cleanup

Status: active

Open items:

- reduce the surface area of `core/runtime_bindings.py` so it stays a boundary helper instead of becoming a general-purpose locator
- replace the remaining module-scoped shared instances in `api/services/chat_read_service.py` and `api/services/chat_trace_read_service.py` with clearer lifecycle ownership when practical
- review legacy packages such as `processing/` and other dormant runtime leftovers, then either integrate them into the current layered model or delete them

### 4. Keep service and transport boundaries thin

Status: active

Open items:

- continue consolidating shared write paths so HTTP and websocket entry points do not drift apart again
- keep routers and websocket handlers transport-thin as new product behavior is added
- avoid reintroducing direct runtime-domain lookups in transport code

### 5. Retire legacy ``task_id`` alias from permission payload

Status: active

Why it is still open:

- ``PermissionRequest.to_dict()`` currently emits both ``turn_id``
  (canonical) and ``task_id`` (legacy alias) so older consumers keep
  working. The Rust gateway and the frontend already accept
  ``turn_id``; the duplicate field should be removed once no in-tree
  reader relies on the legacy key.

Remaining work:

- Audit gateway + frontend + tests for remaining reads of
  ``task_id`` on permission payloads and migrate them to
  ``turn_id``.
- Drop the ``task_id`` emission from ``PermissionRequest.to_dict()``
  and the fallback in ``_publish_permission_event``.
- Target removal: next release cycle after this commit lands.

## Maintenance Fixes

### 1. Remove current backend warning debt

Status: active

Known items:

- resolve the Pydantic v2 deprecation warnings still reported in the backend test suite
- update the affected response and provider helper code to the current supported API shape

### 2. Retire or split oversized legacy modules

Status: active

Candidates to review next:

- large orchestration or execution modules that still mix multiple concerns
- registry modules that still combine lifecycle, indexing, stats, and execution behavior in one file
- older code paths that predate the current task-agent and bootstrap model

### 3. Expand targeted validation where coverage is still weaker

Status: active

Current candidates:

- websocket and transport boundary behavior
- awareness and sensor boundary behavior
- llm provider edge cases and error handling

## Documentation Follow-Up

### 1. Keep product and plugin docs aligned with implementation changes

Status: ongoing

Open items:

- update the product and extension docs whenever new settings surfaces or plugin contribution types are added
- keep subsystem plans short-lived and fold durable decisions back into the main docs instead of creating a new pile of review and plan files
