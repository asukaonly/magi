# Magi Backlog

This document tracks current development and maintenance follow-ups that are still open after the latest architecture cleanup.

It is intentionally separate from the stable design docs.

## Active Development

### 1. Alpha product focus: Chat with Memory + Evidence Trace

Status: active

Why it matters now:

- The Alpha product path should make the desktop app useful quickly: finish onboarding, configure an LLM, chat, recall memory explicitly, and inspect the evidence behind memory-informed answers.
- Product work that does not improve this path should stay supported but lower-priority until the core flow is reliable.

Current focus areas:

- Keep quick onboarding short and centered on language, LLM setup, and persona selection.
- Quick onboarding now separates provider/API-key setup from a recommended model confirmation step before completion.
- Make explicit memory recall in chat reliable and evidence-backed.
- Keep ordinary memory views user-facing, with layer-specific L0-L4 workbench surfaces reserved for expert/operator mode.
- Quick-mode settings now keep memory configuration to the general section; L0-L4 tuning remains available in expert mode.
- Quick-mode sidebar memory navigation now points users to the overview instead of layer-specific workbench pages.
- Preserve timeline browsing, plugin management, and advanced runtime inspection, but do not make them Alpha polish blockers.

Deferred unless profiling or product validation says otherwise:

- Deep personality evolution engine investment.
- Memory pipeline process isolation.
- Repository-wide backend typing strictness.

### 2. Persona registry migration and frontend integration

Status: active

Why it is still open:

- The persona registry backend (PersonaRepository, seed service, evolution engine persona_id scoping, `/api/personas/*` routes) is implemented and tested.
- The main frontend personality surface and onboarding flow now use the persona registry path.
- Quick onboarding now selects the default persona from locale-aware seed metadata instead of a hardcoded seed slug.
- Existing file-based persona JSON configs can be imported into the registry with `scripts/migrate-personas-to-registry.py`.
- The old in-memory `current_state.py` bridge has been retired; active persona runtime state lives in `active_persona.py`.
- Legacy `/api/personality` slug/list reads now stay registry-backed; bundled JSON preset reads remain isolated behind `/api/personalities/*`.

Remaining work:

- Audit remaining legacy personality/config routes and remove any routes that no longer match the registry-backed product path.

### 3. Finish the lifecycle-based memory implementation

Status: active

Why it is still open:

- the lifecycle model is documented and partially implemented, but the subsystem plan still contains unfinished phases
- retrieval, prompt integration, API cleanup, and some legacy memory-module removal work are still open in the implementation backlog

Current focus areas:

- complete the remaining L2/L3/L4 implementation work
- finish retrieval and prompt integration against the lifecycle model
- remove superseded legacy memory modules once the new path fully owns production behavior

### 4. Continue runtime boundary cleanup

Status: active

Open items:

- keep chat task-agent dependencies flowing through lifecycle/factory wiring; the chat read service factory is now injected into `ChatTaskAgent`, history loading, and postprocess notifications, permission gating is passed into function-calling executors through lifecycle-provided gateway providers, and planner todo mirroring receives its control-session store through the task-agent factory
- reduce the surface area of `core/runtime_bindings.py` so it stays a boundary helper instead of becoming a general-purpose locator
- keep the chat and chat-trace read-service singletons container-owned instead of adding module-scoped service globals back to their implementation modules
- review legacy packages such as `processing/` and other dormant runtime leftovers, then either integrate them into the current layered model or delete them

### 5. Keep service and transport boundaries thin

Status: active

Open items:

- continue consolidating shared write paths so HTTP and websocket entry points do not drift apart again
- keep routers and websocket handlers transport-thin as new product behavior is added
- avoid reintroducing direct runtime-domain lookups in transport code

### 6. Retire legacy ``task_id`` alias from permission payload

Status: done — ``turn_id`` is now the only permission payload runtime-turn identifier.

Completed:

- ``PermissionRequest.to_dict()`` emits ``turn_id`` only.
- Frontend permission polling and modal projection read ``turn_id``
  directly.
- Backend/frontend tests cover the canonical payload shape.

## Maintenance Fixes

### 1. Remove current backend warning debt

Status: done — provider configuration helpers now use Pydantic v2 `model_config`.

Completed:

- resolved the Pydantic v2 deprecation warning from `ProviderConfig`.
- updated the provider helper code to the current supported API shape.

### 2. Retire or split oversized legacy modules

Status: active

Recent progress:

- `function_calling.py` no longer owns permission-gateway formatting/resolution logic directly; it delegates that slice to `function_calling_permission.py`.
- The backend type gate now covers extracted function-calling execution helpers in addition to LLM and L2 support modules.
- Function-calling callback and runtime-trace persistence helpers now live in `function_calling_tracing.py`.
- Function-calling LLM request/response helpers now live in `function_calling_llm.py`.
- Provider bridge thinking-option and concurrency helpers now live in `provider_bridge_options.py`.
- L2 snapshot evolution and ToM reconciliation helpers now live in `store_reconcile.py`.
- L2 graph-conflict resolution and rule reload helpers now live in `store_graph_conflicts.py`.
- L2 SQLite row-to-dict helpers now live in `store_rows.py`.
- L2 knowledge-graph schema backfills now live with the other store migrations.
- L2 graph `fact_kind` admission rules now live in `store_fact_kind.py`.
- L2 rule-based candidate extraction now lives in `store_candidates.py`.
- L2 contradiction hint application now lives in `store_contradictions.py`.
- L2 ToM snapshot persistence now lives in `store_snapshots.py`.
- L2 ToM assertion upsert flow now lives in `store_assertions.py`.
- L2 user rejection and forgetting helpers now live in `store_forgetting.py`.
- L2 user assertion feedback and correction helpers now live in `store_feedback.py`.
- L2 assertion/snapshot/relationship read queries now live in `store_queries.py`.
- L2 edge embedding status and vector search helpers now live in `store_edge_embeddings.py`.
- L2 knowledge-graph upsert and corroboration helpers now live in `store_graph_writes.py`.
- Provider bridge non-streaming request implementations now live in `provider_bridge_requests.py`.
- Provider bridge plain chat streaming now lives in `provider_bridge_streaming.py`.
- Provider bridge tool-call streaming now lives in `provider_bridge_streaming.py`.
- Chat post-processing session-run finalization helpers now live in `postprocess_session.py`.
- Chat post-processing tool event helpers now live in `postprocess_tool_events.py`.
- Chat post-processing outcome writer helpers now live in `postprocess_outcomes.py`.
- Chat post-processing background completion helpers now live in `postprocess_background.py`.
- Chat post-processing memory/reflection helpers now live in `postprocess_memory.py`.
- Worker prompt and tool-profile helpers now live in `worker_prompting.py`.
- Worker status, await, and run-state serialization helpers now live in `worker_status.py`.
- Worker tool schema definition now lives in `worker_schema.py`.
- Worker public action validation and dispatch now lives in `worker_actions.py`.
- Worker launch/start/batch lifecycle helpers now live in `worker_launch.py`.
- Worker fact, bus-event, and trace-notification publication helpers now live in `worker_publication.py`.
- L1 event/entity linkage helpers now live in `event_store_entities.py`.
- L1 event-store schema migration helpers now live in `event_store_schema.py`.
- L1 event-store row serialization and timeline projection helpers now live in `event_store_rows.py`.

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
