# Magi Backlog

This document tracks concrete, code-backed engineering work that remains open.
Every item must describe a current failure mode or boundary violation and have
an independently verifiable completion condition.

Product choices, speculative abstractions, permanent engineering principles,
and completed migration history do not belong here. Local decision drafts and
implementation spikes belong under `docs/dev/`; durable decisions must be
folded into the relevant source-of-truth document before implementation.

## Active Engineering

### 1. Add durable per-target external conversation delivery

Status: active

Current failure mode:

- ordinary external replies are delivered before their receipts are persisted
- external `ask_user` delivery has only process-local deduplication and performs
  a single attempt
- a restart after provider acceptance but before local acknowledgement cannot
  safely distinguish a missing delivery from a duplicate retry

Required outcome:

- persist one delivery intent per target before invoking the channel provider
- give every final reply and ask a stable host delivery identity
- lease and retry unfinished intents after restart without reusing the
  proactive-outreach lifecycle
- extend the channel contract so capable providers can apply the stable identity
  as an idempotency key
- expire or cancel asks that are no longer actionable
- cover the provider-accepted/local-acknowledgement crash window, partial fanout,
  retry, expiry, and clear/delete behavior with focused tests

### 2. Finish runtime dependency-ownership cleanup

Status: active

Current failure mode:

- `core/runtime_bindings.py` exposes domain services beyond the two runtime
  boundary roots described by the earlier cleanup
- chat runtime construction still creates a `ChatTraceReadService` directly
  instead of using the container-owned instance
- some API dependency helpers reach through `runtime_bootstrap_context` as a
  service locator

Required outcome:

- obtain chat-trace reads from the container-owned provider
- move domain-service lookups to their owning domain providers or inject them
  through lifecycle/factory wiring
- keep `core/runtime_bindings.py` limited to genuine API/transport boundary
  objects with explicit ownership
- remove API-layer bootstrap-context traversal where a typed domain dependency
  can be injected
- add architecture tests that reject direct reconstruction and new locator
  access from migrated consumers

### 3. Keep operator memory tooling out of quick mode

Status: active

Current failure mode:

- the quick-mode sidebar still exposes Memory Governance
- direct navigation to `/memory/governance` is not guarded by user mode
- that page exposes L0-L4 records, replay/reconcile controls, destructive
  maintenance, and diagnostics intended for expert/operator use

Required outcome:

- hide operator-only memory navigation in quick mode
- guard direct operator routes and redirect quick-mode users to the ordinary
  memory overview
- keep all operator surfaces available in expert mode
- cover sidebar visibility, direct navigation, mode changes, and expert access
  with frontend tests

### 4. Remove stale memory configuration and compatibility paths

Status: active

Current failure mode:

- `MemoryIntegrationConfig` mirrors layer switches
  that do not govern ingestion behavior in that module
- `UnifiedMemoryStore.store_event()` and `add_event()` are compatibility wrappers
  around `ingest_event()`
- `legacy_user_content.py` and its clear hooks exist only to remove retired
  pre-release storage locations

Required outcome:

- remove passive integration-config mirrors that do not own behavior
- migrate remaining test callers to `ingest_event()` and delete the wrapper APIs
- remove retired-store cleanup code and its call sites rather than preserving a
  pre-release compatibility path
- verify configuration round trips, lifecycle startup, ingestion, and full-clear
  behavior after the clean cut

### 5. Extract application services from oversized memory routers

Status: active

Current failure mode:

- `memory/l2/experiences_routes.py` and `memory/manual_entries_routes.py` still
  own substantial business orchestration
- `memory/l2/correction_history.py` performs storage queries inside the API
  package
- memory router dependency helpers contain repeated runtime/domain resolution
  logic

Required outcome:

- move experience and manual-entry orchestration into domain/application
  services with explicit inputs and outputs
- move correction-history persistence and privacy filtering behind a
  repository/application boundary
- make HTTP handlers responsible only for request validation, dependency
  resolution, status/error translation, and response serialization
- reuse the same application paths from any non-HTTP entry point
- preserve public API contracts with focused service, router, and reachability
  tests
