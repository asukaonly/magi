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

Status: done

Why it is still open:

- The persona registry backend (PersonaRepository, seed service, evolution engine persona_id scoping, `/api/personas/*` routes) is implemented and tested.
- The main frontend personality surface and onboarding flow now use the persona registry path.
- Quick onboarding now selects the default persona from locale-aware seed metadata instead of a hardcoded seed slug.
- Existing file-based persona JSON configs can be imported into the registry with `scripts/migrate-personas-to-registry.py`.
- The old in-memory `current_state.py` bridge has been retired; active persona runtime state lives in `active_persona.py`.
- Legacy `/api/personality` slug/list reads now stay registry-backed; bundled JSON preset reads remain isolated behind `/api/personalities/*`.

Completed:

- Legacy slug/list/current personality routes are no longer part of the public API surface; registry-backed product flows use `/api/personas/*` and bundled preset reads use `/api/personalities/*`.

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

Recent progress:

- Removed unused runtime binding accessors for message bus, user-message sensor, skill loader, and skill runner; those objects remain lifecycle/container-owned without being public boundary helpers.

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

- `function_calling.py` no longer owns permission-gateway formatting/resolution logic directly; it delegates that slice to `function_calling/permission.py`.
- The backend type gate now covers extracted function-calling execution helpers in addition to LLM and L2 support modules.
- Function-calling callback and runtime-trace persistence helpers now live in `function_calling/tracing.py`.
- Function-calling LLM request/response helpers now live in `function_calling/llm.py`.
- Provider bridge thinking-option and concurrency helpers now live in `provider_bridge/options.py`.
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
- L2 store mixins now live in domain packages (`storage/`, `graph/`, `assertions/`, `entities/`, `episodes/`, `projection/`, `extraction/`, `retrieval/`, `governance/`), with `store.py` kept as the public store facade and transaction coordinator.
- Provider bridge non-streaming request implementations now live in `provider_bridge/requests.py`.
- Provider bridge plain chat streaming now lives in `provider_bridge/streaming.py`.
- Provider bridge tool-call streaming now lives in `provider_bridge/streaming.py`.
- Function-calling fallback final-response and rescue-pass logic now lives in `function_calling/fallback.py`.
- Function-calling concrete tool and skill execution now lives in `function_calling/tool_execution.py`.
- Function-calling orchestrator helpers now live under the `function_calling/` package, with `magi.agent.execution.function_calling` kept as the public facade.
- Chat post-processing session-run finalization helpers now live in `postprocess_session.py`.
- Chat post-processing tool event helpers now live in `postprocess_tool_events.py`.
- Chat post-processing outcome writer helpers now live in `postprocess_outcomes.py`.
- Chat post-processing intent-routing trace helpers now live in `postprocess_intent.py`.
- Chat post-processing background completion helpers now live in `postprocess_background.py`.
- Chat post-processing memory/reflection helpers now live in `postprocess_memory.py`.
- Chat post-processing mixins now live under the `postprocess/` package, with `postprocess_service.py` kept as the public orchestration facade.
- LLM provider bridge helpers now live under the `provider_bridge/` package, with `magi.llm.provider_bridge` kept as the public facade.
- Settings page navigation and sub-selection state now lives in `useSettingsNavigation.ts`.
- Settings page tool config loading and draft mutation state now lives in `useSettingsTools.ts`.
- Settings page config/control draft loading and mutation state now lives in `useSettingsConfig.ts`.
- Settings page plugin package and timeline source draft state now lives in `useSettingsPluginsTimeline.ts`.
- Settings page save/discard persistence orchestration now lives in `useSettingsPersistence.ts`.
- Settings page navigation sidebar rendering now lives in `SettingsNavigationSidebar.tsx`.
- Settings page tools and skills section rendering/loading now lives in `SettingsToolsSection.tsx`.
- Shared settings section primitives now live in `SettingsSectionPrimitives.tsx`.
- Settings page preferences section rendering now lives in `SettingsPreferencesSection.tsx`.
- Settings page conversation section rendering now lives in `SettingsConversationSection.tsx`.
- Settings page personality runtime settings now lives in `SettingsPersonalityRuntimeSection.tsx`.
- Settings page LLM provider/model branches now live in `SettingsLlmSection.tsx`.
- Settings page control branch now lives in `SettingsControlSection.tsx`.
- Settings page memory branches now route through `SettingsMemorySection.tsx`.
- Settings page plugin/channel integration branches now route through `SettingsIntegrationsSection.tsx`.
- LLM provider workbench model helpers now live in `llm-provider-workbench-models.ts`.
- LLM provider list pane rendering now lives in `LLMProviderListPane.tsx`.
- LLM provider API key reveal/input control now lives in `LLMProviderApiKeyField.tsx`.
- LLM provider connection test model menu now lives in `LLMProviderTestMenu.tsx`.
- LLM provider detail header/actions now live in `LLMProviderDetailHeader.tsx`.
- LLM provider connection test status banners now live in `LLMProviderTestStatus.tsx`.
- LLM provider builtin/custom connection fields now live in `LLMProviderConnectionFields.tsx`.
- LLM provider model kind/manual-add toolbar now lives in `LLMProviderModelToolbar.tsx`.
- LLM provider workbench model list pane now lives in `LLMProviderModelListPane.tsx`.
- LLM provider model editor header/actions now live in `LLMProviderModelEditorHeader.tsx`.
- LLM provider chat model capability/limit fields now live in `LLMProviderChatModelFields.tsx`.
- LLM provider embedding model dimensions/concurrency fields now live in `LLMProviderEmbeddingModelFields.tsx`.
- LLM provider image model runtime hint now lives in `LLMProviderImageModelFields.tsx`.
- LLM provider model editor shell now lives in `LLMProviderModelEditor.tsx`.
- LLM form cloning, registry, normalization, and runtime override helpers now live in `llm-form-state.ts`.
- LLM embedding dimension confirmation dialog now lives in `LLMEmbeddingDimensionConfirmDialog.tsx`.
- LLM model selection local embedding/reranker download state now lives in `llm-model-download-hooks.ts`.
- LLM model selection reranker panel now lives in `LLMRerankerModelPanel.tsx`.
- LLM model selection advanced/max-concurrency panel now lives in `LLMScenarioAdvancedSettings.tsx`.
- LLM model selection local embedding panel now lives in `LLMLocalEmbeddingModelPanel.tsx`.
- LLM model selection remote embedding model/dimension selector now lives in `LLMRemoteEmbeddingModelSelector.tsx`.
- LLM model selection chat scenario panel now lives in `LLMChatScenarioPanel.tsx`.
- LLM model selection image generation scenario panel now lives in `LLMImageGenerationScenarioPanel.tsx`.
- Dynamic tool config spec normalization now lives in `dynamic-config-specs.ts`.
- Dynamic config field rendering now lives in `DynamicConfigField.tsx`.
- Chat execution trace DTOs now live in `api/services/chat_trace/models.py`.
- Chat execution trace pure helpers now live in `api/services/chat_trace/utils.py`.
- Chat normalized trace builders now live in `api/services/chat_trace/builders/normalized.py`.
- Chat legacy trace fallback builders now live in `api/services/chat_trace/builders/legacy.py`.
- Chat runtime trace row-to-node helpers now live in `api/services/chat_trace/builders/rows.py`.
- Chat read-side DTOs now live in `chat/read/models.py`.
- Chat read-side serialization helpers now live in `chat/read/serialization.py`.
- Chat read-store schema helpers now live in `chat/read/schema.py`.
- Chat write-store serialization helpers now live in `chat/storage/serialization.py`.
- Chat write-store schema helpers now live in `chat/storage/schema.py`.
- L0 working-memory checkpoint schema helpers now live in `l0/working/schema.py`.
- L0 working-memory checkpoint serialization helpers now live in `l0/working/serialization.py`.
- L0 memory session display helpers now live in `api/routers/memory/l0/display.py`.
- Memory API clear response helpers now live in `api/routers/memory/clear.py`.
- Memory API statistics helpers now live in `api/routers/memory/statistics.py`.
- Memory API L0 session list helpers now live in `api/routers/memory/l0/sessions.py`.
- Memory API L1 event list helpers now live in `api/routers/memory/l1/events.py`.
- Memory API L2 status and pending helpers now live in `api/routers/memory/l2/status.py`.
- Memory API procedure response helpers now live in `api/routers/memory/l4/procedures.py`.
- Memory eval answer synthesis helpers now live in `api/routers/memory/eval/answering.py`.
- Memory route utility helpers now live in `api/routers/memory/helpers.py`.
- Memory API Pydantic schemas now live in `api/routers/memory/schemas.py`.
- Config API Pydantic schemas now live in `config_schemas.py`.
- Personality API Pydantic schemas now live in `personality_config_schemas.py`.
- Chat planning request-profile and seed-subtask heuristics now live in `planning_heuristics.py`.
- L4 procedural memory schema constants and initialization now live in `l4/storage/schema.py`.
- L4 procedural memory serialization, trace row, and skill identity helpers now live in `l4/storage/serialization.py`.
- L4 procedural memory tool advisory helpers now live in `l4/advisory/tools.py`.
- L4 procedural memory execution trace merge and recovery helpers now live in `l4/traces/analysis.py`.
- L4 procedural memory record write helpers now live in `l4/storage/records.py`.
- L4 procedural memory execution trace write helpers now live in `l4/traces/store.py`.
- L4 procedural memory search result helpers now live in `l4/retrieval/search.py`.
- L4 procedural memory record update-state helpers now live in `l4/learning/updates.py`.
- L4 procedural memory embedding and chunk persistence helpers now live in `l4/embeddings/skills.py`.
- L3 summary store schema helpers now live in `l3/storage/schema.py`.
- L3 summary store serialization helpers now live in `l3/storage/serialization.py`.
- L3 summary evidence link helpers now live in `l3/evidence/links.py`.
- L3 summary store search result helpers now live in `l3/retrieval/search.py`.
- L3 summary store embedding and chunk persistence helpers now live in `l3/embeddings/summaries.py`.
- Hybrid retrieval intent time parsing helpers now live in `intent_time.py`.
- Hybrid retrieval default summary routing and graph assertion fallback behavior are covered by focused tests.
- L2 retrieval time filtering, global-scan gating, and trace helpers now live in `l2_handler_utils.py`.
- Hybrid retrieval service backstop, count, score, and bundle policy helpers now live in `service_policy.py`.
- Context decider prompt rendering helpers now live in `context_decider_prompt.py`.
- Worker prompt and tool-profile helpers now live in `worker_prompting.py`.
- Worker status, await, and run-state serialization helpers now live in `worker_status.py`.
- Worker tool schema definition now lives in `worker_schema.py`.
- Worker public action validation and dispatch now lives in `worker_actions.py`.
- Worker launch/start/batch lifecycle helpers now live in `worker_launch.py`.
- Worker fact, bus-event, and trace-notification publication helpers now live in `worker_publication.py`.
- Chat execution guidance, UX-plan, and workspace helpers now live in `handler_helpers.py`.
- Chat trace runtime tree reshape helpers now live in `api/services/chat_trace/tree.py`.
- L1 event/entity linkage helpers now live in `l1/entities/links.py`.
- L1 event-store schema migration helpers now live in `l1/storage/schema.py`.
- L1 event-store row serialization and timeline projection helpers now live in `l1/storage/rows.py`.
- L1 event-store FTS/BM25 helpers now live in `l1/retrieval/fts.py`.
- L1 event-store embedding, chunk, and vector-search helpers now live in `l1/embeddings/events.py`.
- L1 event-store read/query helpers now live in `l1/retrieval/queries.py`.
- L2 pipeline flow helpers now live under `pipeline/` by role: `staging.py`, `projection.py`, `context.py`, `workers.py`, `lifecycle.py`, `persistence.py`, `utils.py`, and `conflict.py`.
- L2 pipeline validation helpers now live under `pipeline/validation/` by candidate domain: `structured_hints.py`, `graph.py`, and `assertions.py`.
- L2 entity maintenance helpers now live under `entities/maintenance/` by domain: `assertions.py`, `embeddings.py`, `edges.py`, `catalog.py`, `ghosts.py`, `predicates.py`, and `episodes.py`.
- L2 episode dataclass contracts now live in `episode_models.py` with old `models.py` exports preserved.
- L2 phase/structured/reconciled outcome dataclass contracts now live in `phase_models.py` with old `models.py` exports preserved.
- L2 Phase 1, Phase 2, and auxiliary dataclass contracts now live in focused phase model modules with old `phase_models.py` and `models.py` exports preserved.
- L2 entity/reconcile dataclass contracts now live in `entities/models.py` with `models.py` kept as the aggregate contract facade.
- L2 candidate/unified extraction dataclass contracts now live in `candidate_models.py` with old `models.py` exports preserved.
- L2 batch/window/job/request dataclass contracts now live in `batch_models.py` with old `models.py` exports preserved.
- L2 extraction and auxiliary workflow prompt renderers now live under `pipeline/prompts/`.
- L2 LLM JSON-mode generation/retry helpers now live in `llm_json_client.py` with old `L2LLMService` method access preserved.
- L2 entity catalog embedding rebuild/search helpers now live in `entities/catalog/embeddings.py`.
- L2 entity catalog read/query helpers now live in `entities/catalog/queries.py`.
- L2 projection queue ready-claim batching now lives in `projection/claiming.py`, with queue defaults owned by `projection/queue.py`.
- L2 pipeline entity resolution helpers now live under `pipeline/entities/` by responsibility: `id_resolution.py`, `helpers.py`, `side_effects.py`, and `resolution.py`.

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
