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

### 2. Finish the lifecycle-based memory implementation

Status: active

Why it is still open:

- the lifecycle model is documented and partially implemented, but the subsystem plan still contains unfinished phases
- retrieval, prompt integration, API cleanup, and some legacy memory-module removal work are still open in the implementation backlog

Current focus areas:

- complete the remaining L2/L3/L4 implementation work
- finish retrieval and prompt integration against the lifecycle model
- remove superseded legacy memory modules once the new path fully owns production behavior

### 3. Redesign persona runtime around per-turn planning

Status: active

Why it is open:

- the target design is now documented in [Persona Runtime Architecture](./persona-runtime-architecture.md)
- backend prompt assembly, API schemas, AI generation, bundled presets, onboarding defaults, and the main frontend editor now consume the new top-level persona schema; remaining work is planner quality refinement and wider end-to-end regression
- the product needs persona behavior that feels ordinary most of the time, becomes distinctive under relevant triggers, and changes with relationship depth without becoming a constant style performance

Current focus areas:

- harden the new persona schema and `PersonaTurnPlan` contract with wider end-to-end validation and golden behavior checks
- expand the Personality Layer `PersonaTurnPlanner` beyond the MVP heuristics
- keep prompt assembly consuming the plan instead of raw persona fragments
- strengthen bundled preset examples and add golden behavior checks for ordinary, task, emotional, play, and crisis turns
- refine generated/custom persona quality based on real usage samples

Recent progress:

- Direct LLM and function-calling prompt assembly now have tests that lock the persona-planning inputs for scenario, task category, selected tools, and stored persona id.
- Explore dossier rendering and parent orchestration aggregation now route through analysis persona context; synthesis prompts suppress tool catalog rendering where no tool call should happen.
- Seven now has planner and prompt-level golden checks for ordinary chat, task work, emotional support, absurdity/play, crisis, and revealed relationship-layer turns.
- The main personality detail editor now separates quick and expert editing modes and surfaces minimum-field validation for identity, baseline voice, chat register, signature trigger, and quiet-hour coverage.
- Persona generation now supports current draft config context, completes required runtime schema surfaces after sparse LLM output, and keeps bootstrap first-meeting behavior separate from normal registers without requiring false human claims.
- Frontend persona validation is now shared between the editor and save flow, with minimum and expert checks for registers, triggers, quiet hours, examples, layers, and bootstrap content.
- The planner now suppresses non-essential signature triggers during tool execution and uses more reliable Chinese condition overlap for natural-language trigger activation.

### 4. Continue runtime boundary cleanup

Status: active

Open items:

- keep chat task-agent dependencies flowing through lifecycle/factory wiring; the chat read service factory is now injected into `ChatTaskAgent`, history loading, and postprocess notifications, permission gating is passed into function-calling executors through lifecycle-provided gateway providers, and planner todo mirroring receives its control-session store through the task-agent factory
- keep `core/runtime_bindings.py` limited to runtime boundary objects instead of becoming a general-purpose locator
- keep the chat and chat-trace read-service singletons container-owned instead of adding module-scoped service globals back to their implementation modules
- review legacy packages such as `processing/` and other dormant runtime leftovers, then either integrate them into the current layered model or delete them

Recent progress:

- Removed unused runtime binding accessors for message bus, user-message sensor, skill loader, and skill runner; those objects remain lifecycle/container-owned without being public boundary helpers.
- Moved LLM pool, chat store/projector, memory services, plugin/sensor services, skill indexer, runtime trace store, control-plane services, and background task manager access behind domain-owned providers. `core/runtime_bindings.py` now only exposes the runtime command queue and agent runtime boundary accessors.

### 5. Keep service and transport boundaries thin

Status: active

Open items:

- continue consolidating shared write paths so HTTP and websocket entry points do not drift apart again
- keep routers and websocket handlers transport-thin as new product behavior is added
- avoid reintroducing direct runtime-domain lookups in transport code

### 6. Decide whether reusable assets need one shared resolver

Status: active

Current state:

- chat and memory can retain compact `asset_refs` without storing raw local paths
- photo and screenshot plugins record their own resolver tool in those references
- follow-up turns call the recorded source resolver before importing files into chat
- there is no host-owned universal asset resolver today

Open items:

- validate that several independent sources need the same resolver contract before adding a new host abstraction
- if the need is proven, define one SDK contract, host dispatch path, privacy boundary, and migration for existing source-owned resolver tools
- until then, document and test the current source-owned flow rather than presenting a universal resolver as implemented

### 7. Close external conversation delivery gaps

Status: active

Why it is still open:

- local clear barriers reject sessions and messages that have already entered
  the host, but an external platform can deliver an older unseen backlog item
  for the first time after the clear
- ordinary external chat replies and `ask_user` questions have no durable
  per-target delivery intent, so restart recovery cannot resend a missing
  delivery without also risking a duplicate

Open items:

- define an SDK-level clear generation plus provider cursor/time/sequence
  watermark contract for polling and backfill channel plugins
- add a recoverable per-target outbox with stable message identity and
  channel-side idempotency for ordinary external replies and asks; do not reuse
  the proactive-outreach outbox without defining their different lifecycle
  semantics

### 8. Add platform-specific history import adapters

Status: planned

Current state:

- the host supports one-shot Markdown files and folders with preview, speaker
  confirmation, resumable progress, deletion, and ordered memory handoff
- there is no plugin importer contribution type yet

Open items:

- define a narrow importer contribution that converts one platform export into
  normalized sessions, speakers, source order, timestamps, and content
- keep file selection, identity confirmation, progress, deletion, and memory
  writes host-owned
- add supported export adapters only after representative samples lock their
  parsing and privacy behavior

## Maintenance Fixes

### 1. Retire or split oversized legacy modules

Status: active

Recent progress:

- Large Python and frontend modules have been split into domain packages while keeping public facades stable for callers.
- Memory L0-L4, memory API routers, chat trace services, chat read/write helpers, function calling, provider bridge, worker helpers, settings, and LLM config forms now have focused helper modules or packages.
- Focused backend/frontend tests and the backend type gate cover the highest-risk extracted modules.
- The remaining cleanup should shift from file movement to reducing implicit coupling and preventing boundary drift.

Candidates to review next:

- migrate high-count mixin facades toward composition-backed collaborators, starting with the smallest surfaces
- keep `core/runtime_bindings.py` limited to boundary consumers and move internal runtime lookups back to lifecycle/factory injection
- split large Rust gateway API handlers by route family and shared query helpers
- keep the backend type gate directory/package-based instead of listing every extracted file manually

### 2. Expand targeted validation where coverage is still weaker

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
