# Layered Agent Architecture

## Purpose

This document is the backend boundary source of truth for Magi.

Use it to answer three questions:

- which layer owns a piece of code or runtime behavior
- which dependencies are allowed across layers
- where lifecycle assembly stops and business logic begins

Read it together with [Project Overview](./project-overview.md), [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md), and [Unified Plugin Architecture](./plugin-extension-architecture.md).

## Core Rules

The default dependency rule is:

- upper layers may depend on lower layers
- lower layers must not depend on upper layers
- same-layer modules should communicate through typed contracts, registries, or the message bus rather than ad hoc reach-through

The composition root is a special case:

- it may assemble all layers
- it should stay thin
- it should not absorb business logic on behalf of the layers

One practical rule follows from that:

- `bootstrap/` is outside the numbered layer stack
- layer-owned lifecycle logic should live in the owning package
- `core/` should stay focused on infrastructure concerns
- runtime-domain code should prefer explicit collaborator injection over service-locator style access

## Enforcement & debt status

These rules are **CI-enforced**, not conventional. `backend/.importlinter` defines two contracts (a `lint-imports` gate, `2 kept, 0 broken`):

- **`layers`** — the L1–L15 ordering above. Adopted as a **baseline + ratchet**: a frozen snapshot of pre-existing cross-layer imports that may only *shrink*; any *new* lower→upper import fails CI.
- **`plugin-isolation`** — `tools/builtin` + `tools/code_agent` (capability-tool code) may import the SDK only, never host layers.

Outcome of the layering cleanup (ADRs 0001–0004):

- **`plugin-isolation` baseline = 0** — capability tools are fully SDK-isolated (Framework A). Runtime-control tools (`agent_tool`, batch tools, plan/todo) live in host layers and are composition-root-registered, never in the plugin surface (ADR-0002).
- **`layers` baseline: 115 → 2.** Retired: the `agent → chat` task-agent cluster (the chat-driver descent, ADR-0003/0004 P2), `agent → timeline`, `runtime_trace → events` (layer repositioned above events), `awareness → timeline` (subscribers inverted into timeline), the `tools ↔ skills` cycle (ordered + `ToolRegistryPort`), `chat.workspace` / `chat_trace` (lowered), the old `chat → channels` delivery-router reach-through (now injected as a channel-owned delivery dispatcher), the API/messages surface-to-chat reach-through, the command transcript-write reach-through, and the wrong-direction tail (permission-shim repoint, plus `core→config` / `memory→api` / `skills→engine` / `plugins→tools/awareness` injected, and the `message_text` util lowered).
- **Root runtime modules retired.** Runtime entrypoints and process-role constants live under `bootstrap/`; the runtime namespace default lives under `core/`; the canonical local user lives under `identity/`. `backend/tests/architecture/test_root_module_boundaries.py` keeps the `magi/` root free of runtime modules.
- **Remaining 2 edges are intentionally left** — `api.routers.commands → commands` for the product command endpoint and `api.routers.memory.dependencies → chat` for the memory read-side facade. The high-churn ingress and transcript-write work now enters through chat-owned services: user-message persistence/attachment preparation/queueing live in `chat.ingress`, command/background/bootstrap transcript rows live behind `chat.surface_writes`, external channel session creation lives behind a chat-owned provisioner, and channel inbound attachments are stored by a chat-owned attachment service. Revisit the remaining carry only if a concrete need makes the coupling bite.

When adding code, keep both contracts green. A new lower→upper import is a design smell — inject the dependency from the composition root, lower a shared contract/util, or register via the origin-agnostic registry instead.

## Current Package Mapping

The current codebase maps to the layered model like this.

### Composition root

- `bootstrap/`
	Thin assembly boundary for lifecycle orchestration, bootstrap context slices, and exported runtime bindings

This package is not a numbered business layer.

The `magi/` package root should only contain `__init__.py`. Runtime
code belongs in an owned package so import-linter and the root-module
boundary test can see its architectural position.

### L1. Application Infrastructure

Responsibilities:

- logging
- dependency injection container
- runtime paths
- workspace path overlays and private workspace buckets
- database initialization
- maintenance dependencies
- shared infrastructure exports
- persistent scheduler engine (timing, target dispatch, durable execution bookkeeping)
- runtime trace persistence (spans, LLM calls, tool calls, execution observability)

Primary packages:

- `core/`
- `scheduler/`
- `runtime_trace/`
- `identity/`
- `db/` — Alembic migration environments + runner for the runtime SQLite databases (owned by `DatabaseMigrationModule`, which runs migrations after `core` initializes runtime paths and directories)
- `utils/` — shared leaf helpers (runtime paths, packaged-path resolution, message text); imported across every layer, imports none

All Python log sinks share one leaf-level redaction helper under `utils/`,
configured by L1 logging. Configuration loading and MCP transport setup
register currently known credential values with that boundary. The desktop
sidecar also protects direct standard output before Rust persists it, and the
frontend protects browser and desktop console output before forwarding it.
The diagnostics setting controls only whether higher layers may include full
textual content. Secret redaction and binary-payload omission remain active
regardless of that user preference.
- `hooks/` — hook registry, gateway, and shell-hook handlers; a low cross-cutting substrate consumed by `agent`/`api`/`plugins`, depending only on `core`/`config`
- `location/` — location sample store, geocode cache, WiFi/IPGeo sources, and the read-side resolver (`LocationModule`); a low provider whose write (pollers) and read (viewport) sides are both driven by `timeline` (L13)
- `media/` — media source registry; a low provider consumed by `timeline` (L13)
- selected infrastructure helpers in `bootstrap/exports.py`

Notes:

- the scheduler engine is infrastructure, even if bootstrap starts it later in dependency order
- bootstrap order and ownership layer are not the same thing
- `runtime_trace/` stores execution observability data; it is not durable memory and does not participate in L7 recall
- workspace storage is an infrastructure facade: `core` owns workspace identity, path safety, generated directory creation, and state manifests; upper layers receive scoped paths instead of constructing `<workspace>/.magi` paths directly
- code-delegation path validation and exact filesystem/git cleanup are shared
  infrastructure, but chat owns the durable artifact registry and decides when
  a message, turn, session, history clear, or full conversation clear releases
  that private state. Tool code reaches that registry only through the SDK
  delegation-artifact port.
- `db`, `location`, `media`, and `hooks` are structurally L1 (they depend only on `core`/`scheduler`/`config`) even though their *consumers* live higher — `db` is driven by the composition root, `location`/`media` feed `timeline` (L13), and `hooks` is actuated by `agent`/`api`. Layer = dependency position, not consumer position.
- `identity/` owns the canonical user-id authority (`MagiUserID`, `IdentityResolver`, the `user_identity_bindings` table). Every upper-layer ingress site (channels dispatcher, api dispatch, sensor_hub, session_mapper) canonicalizes external identifiers through it before downstream stores see them; see [Identity Architecture](./identity-architecture.md) for the boundary contract

### L2. Configuration

Responsibilities:

- application config
- provider config
- memory config
- personality selection config
- plugin scan paths and tool and skill config

Primary packages:

- `config/`
- `i18n/` — localization string catalogs and lookup; depends only on `config`

### L3. Message Bus

Responsibilities:

- event transport
- event persistence
- retry and replay coordination

Primary packages:

- `events/`

### L4. Control Plane

Responsibilities:

- session execution-control state (ask/question, plan-mode, todo, detach) and its store
- interaction registry (pending-interaction futures; the `InteractionBroker` core) and timeout semantics
- permission gateway, rules, and risk state (execution gating)
- control-event emission (state changes published on the message bus)

Primary packages:

- `control/`
- `control/tools/` (host runtime-control tools: `plan_mode`, `todo_write`)

Notes:

- the control plane is shared substrate: tools (L8) actuate it, the agent runtime (L12) reads/drives it, and chat/transport (L14/L15) observe and feed it — so it lives low, depended on downward by all of them
- it depends only on L1 infrastructure and L3 events; it must NOT import upward (no `chat`, `transport`, `agent`, `tools`, `llm`, `memory`)
- transcript rendering of control state is the CHAT layer's job: `chat` subscribes to control events and writes state messages itself (downward); the control plane does not reach into `chat`/`transport`
- ask-user lifecycle is the CONTROL layer's job: `ControlAskService` opens asks, waits on `InteractionBroker`, handles timeout/cancel/answer, and emits control events. The composition root's SDK `InteractionPort` adapter only delegates to that service.
- external ask delivery is the CHANNEL layer's job: channels subscribe to `CONTROL_ASK_REQUESTED` and fan out pending asks to the origin channel; control does not call channel delivery directly.
- external ask delivery is attempted once and publishes an explicit failure event when it cannot confirm a receipt. One active subscriber suppresses repeated pending events with a bounded, expiry-aware in-process LRU and skips asks that are already expired; completed delivery entries stay until expiry or capacity eviction instead of being removed immediately. This protection is intentionally not durable across restart. Until channel delivery has a stable idempotency key and a durable egress intent, restart recovery or a missing receipt must not trigger an automatic retry that could duplicate the question.
- interaction answers flow downward: `transport` delivers user answers into the control interaction registry (`transport → control`)
- `run_control` (detach signal / `current_detach_signal`) belongs here, not in the agent runtime
- the four "actuator tools" split by species (ADR-0002): `ask_user` + `detach` are shareable capabilities exposed to ALL tools (incl. plugins) as SDK ports on `ToolExecutionContext` (`InteractionPort`/`DetachPort`), so they stay capability tools in `tools/builtin`; `plan_mode` + `todo_write` are host runtime-control tools in `control/tools/`; `agent_tool` (spawn sub-agent) is a runtime-control tool in the agent layer (`agent/runtime_tools/`, L12). The host runtime-control tools are closed and NOT plugin-contributable.

### L5. Plugin Registration Layer

Responsibilities:

- plugin discovery
- plugin install, update, upload, and uninstall orchestration
- plugin loading
- contribution registration
- plugin package settings metadata

Primary packages:

- `plugins/`

Notes:

- this layer owns package lifecycle only
- tools and sensors return to their owning runtime layers after registration
- plugin install/update decisions are owned by `PluginInstallService`, while API routes and background jobs only submit install commands
- plugin-provided memory summary and recall hooks are exposed through `PluginProjectionService`, not through the lifecycle manager

### L6. LLM Runtime

Responsibilities:

- provider routing
- scenario-specific model selection
- chat and generation adapters
- usage-event publication

Primary packages:

- `llm/`

### L7. Memory Layer

Responsibilities:

- `L0` short-term conversation attention
- `L1` event memory
- `L2` structured cognition
- `L3` reflection summaries
- `L4` procedural memory
- retrieval across those layers

Primary packages:

- `memory/`

### L8. Tools And Skills Layer

Responsibilities:

- built-in tools
- provider-backed tools
- built-in and external skills

Primary packages:

- `tools/`
- `skills/`
- `mcp/` — MCP server bridge; registers MCP-backed tools into the shared registry. A host integration (like `plugins`/`skills`), NOT plugin-implementation code — see the "Tool sources are host integrations" note below

Notes:

- **Tool taxonomy (ADR-0002):** two tool species share one origin-agnostic registry — **capability tools** (do work; depend only on `magi_plugin_sdk` + host-injected capability ports; first-party ≡ third-party; extensible) and **runtime-control tools** (drive agent execution state; host-owned, closed; live in `control/tools/` (L4) and `agent/runtime_tools/` (L12), registered via the composition root). The `plugin-isolation` contract governs only capability-tool code (`tools/builtin`, `tools/code_agent`): SDK-only, never host internals.
- **Capability ports:** the host hands capabilities to tools via a `ToolCapabilities` bundle on `ToolExecutionContext` (SDK Protocols the host implements): trace, delegation-events, delegation-artifacts, background, session-cache, chat, memory-query, image-gen, interaction (ask), detach. A tool depends on the Protocol, never the host package. The delegation-artifact port registers the exact chat/session/workspace cleanup identity before a code tool creates logs, diffs, branches, or a temporary worktree; the capability tool must not import chat persistence to do this itself.
- **Tool sources are host integrations:** the plugin manager (`plugins/`, L5), the MCP bridge (`mcp/`), and the skill-execution engine (`skills/`) all register their tools into the single registry. These integration packages are HOST code (`magi.skills` runs sub-agents via the orchestrator, like `magi.mcp` and `magi.plugins`) — so NONE are in the `plugin-isolation` source scope. Only third-party *content* (plugin / skill / MCP-server code) follows the plugin contract; it is loaded dynamically and runtime-guarded, not statically import-checked.

### L9. Personality Layer

Responsibilities:

- persona schema, presets, registry-facing persona config, and persona generation contracts
- personality state
- subjective user interpretation from the personality perspective
- relationship depth, milestones, and persona-specific dynamic state
- persona runtime planning: selecting register, quiet-hour clamps, signature triggers, layer modifiers, and dynamic-state modulations for a turn
- tone and style behavior as an output of a structured per-turn plan, not as a global prompt filter

Primary packages:

- `personality/`

Notes:

- L9 owns `PersonaTurnPlanner` and the `PersonaTurnPlan` contract described in [Persona Runtime Architecture](./persona-runtime-architecture.md).
- L9 owns reference-research policy and its search/fetch ports; runtime-tool adapters live in the L14 application-service layer and are injected into those ports.
- L9 may consume task/runtime hints from L12 and profile/memory state from lower layers, but persona-specific trigger interpretation must not be duplicated in chat handlers, context rendering, or post-processing.
- post-processing may update future relationship and dynamic state; it should not be the primary place where the already emitted turn's persona mode is chosen.

### L10. Sensors Layer

Responsibilities:

- inbound sensors (domain-neutral `SensorBase` and `SensorOutput`)
- sensor memory policy (`SensorMemoryPolicy`) controlling durable event routing,
  cognition eligibility, and retention; sensors do not write L0 attention
- sensor ingestion gateway (`SensorIngestionGateway`) for memory/timeline/graph routing
- sensor state management (cursors, fingerprint dedup)
- runtime event emission

Primary packages:

- `awareness/`

Notes:

- plugin-contributed sensors are registered in `plugins/`, but runtime execution belongs here
- all sensor plugins inherit from `SensorBase` and produce `SensorOutput`
- `SensorIngestionGateway` routes outputs to memory (L7), timeline (L13), and knowledge graph

### L11. Context Layer

Responsibilities:

- prompt-context assembly
- recall shaping
- prompt rendering from typed context inputs, including the `PersonaTurnPlan` produced by L9

Primary packages:

- `context/`
- `user_profile/` — user-profile read model assembled from `memory`/`identity`; consumed by `context` prompt assembly and the API

Notes:

- L11 consumes the persona behavior plan and renders it into the final system prompt.
- L11 should not classify registers, activate persona triggers, or evaluate relationship layers itself.
- scenario prompt storage should not become a second source of persona behavior truth; persona registers and trigger behavior belong in L9 persona config.

### L12. Agent Runtime

Responsibilities:

- task-agent lifecycle
- router and dispatch
- execution-mode coordination
- task orchestration
- worker execution management

Primary packages:

- `agent/runtime/`
- `agent/task_agents/`
- `agent/workers/`
- `agent/runtime_tools/`
- `agent/task_orchestrator.py`

Notes:

- `agent/runtime/` is the correct L12 home for runtime control flow
- it is not a replacement for infrastructure and should not be described as a second `core/`
- `agent/runtime_tools/` holds host runtime-control tools that need the agent runtime itself (e.g. `agent_tool`, which spawns sub-agents via `WorkerAgentManager`). The L8 tool registry cannot import L12, so these are registered by the composition root (`bootstrap/`), not via the plugin/core-tools path (ADR-0002).

#### Agent runtime — three rings (ADR-0004)

The run-execution stack is three concentric rings, each separated by a dependency-inversion seam. Rings 1–2 are the domain-agnostic agent runtime (L12); ring 3 is the per-surface driver, which lives in *its own domain layer*, not in `agent/`:

1. **Run Engine** — `FunctionCallingOrchestrator` (`agent/execution/`) + `TaskAgentExecutionEngine`, `NodeSequenceRunner`, and the node framework (`agent/run/`): a bounded LLM↔tool run. Domain-agnostic and **chat-free** — already used headless by worker / subagent / background. The engine does not runtime-import handlers (they are injected; only TYPE_CHECKING refs exist).
2. **Generic handler framework** — `TaskAgent` base, `BaseExecutionHandler`, execution contracts, and the handler *algorithms* (`DirectLLMHandler` / `FunctionCallingHandler`) in `agent/task_agents/handlers/`. Domain-agnostic; drives the engine through **injected service Protocols** (`agent/task_agents/common/service_protocols.py`). Generic across drivers (chat today; voice / batch / scheduled next).
3. **Domain drivers** — the surface-specific composition, in `chat/task_agent/` (L14): `ChatTaskAgent` + factory + the `Chat{Prompt,Planning,History}Service` + postprocess / transcript / reply-context + the run/session state machine (`ChatExecutionCoordinator` / `session_run_*` / `run_store*`) + conversational services (fact-classifier / interruption / rhythm / streaming / turn UX planning / chat tool selection / foreground-background run placement). A driver lives in its **highest domain layer**, implements the ring-2 Protocols, and is dispatched by type via an injected factory the agent runtime never hard-imports (ADR-0003). The chat driver is constructed via `create_chat_agent_factory` injected from the composition root (`bootstrap/`), so `agent/lifecycle.py` does not import chat.

Seam status: **both seams are inverted & clean.** Ring 1 ↔ 2 — engine request/result contracts + `AttachmentResolverPort` (`agent/run/ports.py`, ADR-0004 P1). Ring 2 ↔ 3 — handler bundle typed against ring-2 Protocols; the **entire** chat driver (incl. `ChatExecutionCoordinator` + the run/session machine) relocated to `chat/task_agent/`; the generic ring-2 package renamed `agent/task_agents/chat/` → `agent/task_agents/handlers/`; factory wiring inverted to the composition root (ADR-0004 P2 / ADR-0003). The `agent → chat` task-agent debt is retired. *Remaining (separate concerns, not the descent):* `TimelineTaskAgent` → `timeline` (same rule, by-need); a few `agent.* → chat.workspace` consumers (a different subsystem — the agent working-context store).

Driver rule: domain drivers may choose intent, own surface state, and call the engine front door, but they must not assemble graph builders, node registries, node adapters, or sequence runners directly. Those details stay inside `agent/run/` behind `TaskAgentExecutionEngine`.

**Triggers & engine front door (ADR-0004 P3 / P4).** Every run carries a typed `RunTrigger` (`agent/run_triggers.py` — built per source: native chat → `user_message`, external channel → `external_inbound`, scheduler → `scheduled`, batch → `batch`), lifted out of chat's coordinator into a standalone, side-effect-free seam. A live chat run retains its trigger in process; detached and headless work persists the trigger on its background specification, while restarted foreground chat reconstructs it from the durable delivery envelope. L0 does not own execution recovery. The Run Engine exposes the typed `FunctionCallingOrchestrator.run(EngineRunInput)` entry, a parameter object mirroring `execute_with_tools` 1:1 (parity-locked by test). Background, worker, subagent, and non-checkpoint chat execution use it; session-bound chat function calling still applies its checkpoint boundary policy in the handler layer. That path shares the registered `RunControl`, task budget, and monotonic iteration count, but moving the policy behind the engine entry remains the unfinished part of P4. The three headless surfaces use `EngineRunInput.headless(...)`, which structurally cannot carry chat-only session/control fields. The full **driver registry** (a `RunDriver` protocol + dispatch-by-type, with batch / voice / scheduled as registered drivers, plus timeline-driver relocation) is **deferred (YAGNI)** until a *second real driver* needs polymorphic dispatch; the `RunRequest` projection (`BackgroundTaskSpec.as_run_request()`) exists but has no consumer yet.

### L13. Timeline Domain

Responsibilities:

- timeline read models (`TimelineEvent` is L13-internal, not exported)
- scale-aware viewport and context-bundle read models
- timeline adapter (`TimelineAdapter`) stores host-rendered `TimelineEvent` objects
- timeline normalization and insight extraction
- scheduled source sync policy

Primary packages:

- `timeline/`

Notes:

- `TimelineEvent` is an L13-internal view model; sensors produce `SensorOutput` (L10)
- host projection is the sole owner of timeline display rendering from `SensorOutput.activity` + `SensorOutput.narration`
- `TimelineAdapter` is the sole entry point for rendered timeline events into the timeline read model

### L14. External Services

Responsibilities:

- product-facing routers (dispatched via IPC from the Rust gateway)
- application services
- read and write service contracts
- chat domain persistence (sessions, turns, messages, attachments)
- task domain persistence (user-facing task tracking)
- external messaging channel adapters (Telegram and other platforms)

Primary packages:

- `api/routers/`
- `api/services/`
- `chat/`
- `tasks/`
- `channels/`
- `commands/` — slash-command handlers dispatched by the API surface; transcript writes are delegated through the chat-owned surface write service
- `outreach/` — proactive-messaging orchestration over `agent`/`chat`/`channels`; the top surface orchestrator (sits above the `api` line in the contract ordering)
- `system_suggestions/` — API-facing suggestion generation (uses `llm`)
- `notifications/` — API-facing notification helpers
- `availability/` — leaf availability read model exposed by the API
- `chat_preview/` — leaf chat-preview helper exposed by the API

Notes:

- the Rust gateway (`crates/magi-gateway/`) handles static database reads,
  config file I/O, task CRUD, and only lightweight chat-session creation and
  presentation updates such as title and workspace. Message, session, and
  history deletion cross memory, trace, file, delivery, and runtime
  boundaries, so those operations are forwarded to the Python chat-forgetting
  service rather than implemented as native soft-deletes
- requests requiring the Python runtime are dispatched via IPC `api.forward` to FastAPI routers running as an in-memory ASGI app
- `chat/` owns transcript truth (`chat.db`), attachment storage, session
  workspace, code-delegation ownership references, and deletion-recovery
  registries; it is not the memory layer
- inbound user-message handling is chat-owned: API and channel surfaces should hand off to the active user-message dispatcher instead of assembling chat turns, attachments, and runtime queue commands themselves
- API and command surfaces must not assemble chat transcript rows directly; command, background-task, label/delete, and bootstrap assistant rows go through the chat-owned surface write service
- `chat/portrait/` owns persona-voiced portrait cards shown in the chat rail; it
  may consume neutral memory snippets but memory must not assemble chat/persona
  presentation
- `channels/` provides bidirectional adapters for external messaging platforms; each channel routes messages into the standard chat pipeline, while chat owns creation of chat sessions and storage of inbound chat attachments; channel-owned dispatchers own chat egress fanout, delivery preferences, delivery receipts, and delivered-message retraction
- `outreach/` owns proactive intent identity, policy, durable pending work, and
  delivery convergence. It reads the current channel registry and session
  mapper through injected live views, but it does not own channel adapters or
  ordinary chat/`ask_user` delivery. The proactive outbox must not be reused as
  a shortcut for those paths: ordinary replies and asks need their own
  per-target recovery contract

### L15. Connection And Transport

Responsibilities:

- IPC server and command dispatch for the Python sidecar
- IPC transport app assembly and middleware
- HTTP and WebSocket serving (owned by the Rust gateway, not Python)

Primary packages:

- `ipc/` (Python-side IPC server, dispatcher, protocol, handlers)
- `transport/` (Python-side in-memory ASGI app wiring and middleware)
- `crates/magi-gateway/src/api/` (Rust-side HTTP/WebSocket handling)
- `crates/magi-gateway/src/ipc/` (Rust-side IPC client and protocol)

Notes:

- the Python process runs no public HTTP server; external traffic arrives through the Rust gateway and crosses into Python over IPC (Unix Domain Socket on Unix-like systems, loopback TCP on Windows)
- the Rust gateway owns desktop request authentication, exact WebView-origin checks, and short-lived access tickets for DOM-loaded private resources
- the desktop session credential is host-owned, memory-only connection state; Python, plugins, and business layers must not receive, persist, log, or place it in resource URLs
- resource tickets are transport grants only; chat, timeline, and personality owners still decide whether the referenced resource exists, is active, and may be read
- future browser or collector ingress must use a separate paired capability with explicit route scope rather than sharing the WebView credential
- `ipc/` owns the server, NDJSON protocol parsing, and method-to-handler routing
- `transport/` owns the in-memory FastAPI/ASGI app used for IPC request dispatch

## Boundary Contracts

### Bootstrap contract

- `bootstrap/` may assemble all layers, but it should not own business behavior from those layers
- lifecycle modules should live with the owning layer whenever possible
- exported runtime bindings are a boundary convenience, not a license for domain code to reach back into bootstrap

### Runtime binding contract

- `core/runtime_bindings.py` is for boundary-facing consumers such as routers, transport handlers, and exported services
- runtime-domain code should prefer explicit constructor or lifecycle injection
- adding a new runtime binding requires a clear ownership reason, not just convenience

### Scheduler contract

- the scheduler engine is infrastructure
- timeline and agent layers own scheduling policy and target registration
- scheduled execution should enter the owning layer through typed target handlers rather than scattered ad hoc loops

### Plugin contract

- plugins own discovery, package lifecycle, and contribution registration
- registries expose the registered capability surfaces
- plugin registration must not become a place where domain behavior is reimplemented

### Tool contract

- tools are agent-callable capabilities
- if outbound side effects are needed in the future, they should be modeled as channels or runtime pipeline hooks rather than a separate action abstraction
- concrete host tool-capability adapters are assembled by `bootstrap/tool_capabilities.py`, but runtime packages must not import that bootstrap module directly; they should call the tools-layer `tools/capabilities.py` provider, which bootstrap configures during runtime exports

### Personality versus memory contract

- memory should stay relatively factual and traceable
- personality may carry subjective or relational interpretation
- chat/persona presentation may turn memory snippets into persona-voiced cards,
  but the memory layer should expose only neutral retrieval/projection material
- configuration code should not reach through personality state when the same information can be read from owned config or runtime paths

## Practical Guidance

When placing new code, use this sequence:

1. decide which layer owns the behavior
2. put lifecycle logic in the owning layer or bootstrap assembly, not in a generic helper module
3. prefer typed contracts and injected collaborators over runtime lookups
4. only add a new boundary helper if multiple external-facing consumers genuinely need it
- the memory layer owns neutral or traceable event retention, cognition extraction, reflection, and retrieval
- the two layers may both describe the user, but they should not collapse into one undifferentiated profile store

### Sensor → Timeline → Memory Contract

- sensors (L10) produce domain-neutral `SensorOutput` with per-sensor `SensorMemoryPolicy`
- `SensorIngestionGateway` (L10) routes each output to memory (L7) and optionally to timeline (L13)
- timeline is a downstream consumer that builds its own read model (`TimelineEvent`) from sensor outputs
- memory is the lifecycle system that retains, derives, summarizes, and retrieves durable knowledge from runtime and sensor inputs
- raw behavioral facts enter memory via `SENSOR_EVENT` classification and enter timeline via `TimelineAdapter`

### Context Assembly Contract

- prompt and context assembly should have a clear home in the context layer
- personality, memory, and agent runtime may contribute inputs, but prompt construction should not fragment across many layers without an explicit contract

## Naming Guidance

To reduce future ambiguity, prefer the following terminology:

- `Actions` instead of `Executors` when referring to outbound side-effect capabilities
- `Tools and Skills` instead of `LLM Tools`
- `Connection and Transport` instead of a vague external-connection label
- `Timeline queries` or `read models` instead of `data display`
- `Memory layers` for lifecycle/storage structure, and `memory content categories` for things like preference, tool experience, or persona-adjacent facts

## Package Mapping

The current codebase maps to the layered model like this:

- `bootstrap/` -> outer composition root, not a numbered layer
- `core/`, `scheduler/`, `runtime_trace/`, `identity/`, `db/`, `utils/`, `hooks/`, `location/`, `media/` -> L1 application infrastructure
- `config/`, `i18n/` -> L2 configuration
- `events/` -> L3 message bus
- `control/` (incl. `control/tools/` host runtime-control tools plan/todo) -> L4 control plane
- `plugins/` -> L5 plugin registration
- `llm/` -> L6 LLM runtime
- `memory/` -> L7 memory
- `tools/`, `skills/` -> L8 tools and skills (`skills/` is the host skill-execution engine; `mcp/` bridges MCP servers — both are host tool-source integrations like `plugins/`, NOT plugin-implementation code)
- `personality/` -> L9 personality
- `awareness/`, event emitter -> L10 sensors
- `context/`, `user_profile/` -> L11 context
- `agent/` (incl. `agent/runtime_tools/` host runtime-control tool agent_tool) -> L12 agent runtime
- `timeline/` -> L13 timeline domain
- `api/`, `chat/`, `tasks/`, `channels/`, `commands/`, `outreach/`, `system_suggestions/`, `notifications/`, `availability/`, `chat_preview/` -> L14 external services
- `ipc/`, `transport/` and `crates/magi-gateway/` -> L15 connection and transport

The boundary rules above should remain stable even as package internals evolve.
