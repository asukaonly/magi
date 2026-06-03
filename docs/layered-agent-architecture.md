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

## Current Package Mapping

The current codebase maps to the layered model like this.

### Composition root

- `bootstrap/`
	Thin assembly boundary for lifecycle orchestration, bootstrap context slices, and exported runtime bindings

This package is not a numbered business layer.

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
- selected infrastructure helpers in `bootstrap/exports.py`

Notes:

- the scheduler engine is infrastructure, even if bootstrap starts it later in dependency order
- bootstrap order and ownership layer are not the same thing
- `runtime_trace/` stores execution observability data; it is not durable memory and does not participate in L7 recall
- workspace storage is an infrastructure facade: `core` owns workspace identity, path safety, generated directory creation, and state manifests; upper layers receive scoped paths instead of constructing `<workspace>/.magi` paths directly
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
- interaction answers flow downward: `transport` delivers user answers into the control interaction registry (`transport → control`)
- `run_control` (detach signal / `current_detach_signal`) belongs here, not in the agent runtime
- the four "actuator tools" split by species (ADR-0002): `ask_user` + `detach` are shareable capabilities exposed to ALL tools (incl. plugins) as SDK ports on `ToolExecutionContext` (`InteractionPort`/`DetachPort`), so they stay capability tools in `tools/builtin`; `plan_mode` + `todo_write` are host runtime-control tools in `control/tools/`; `agent_tool` (spawn sub-agent) is a runtime-control tool in the agent layer (`agent/runtime_tools/`, L12). The host runtime-control tools are closed and NOT plugin-contributable.

### L5. Plugin Registration Layer

Responsibilities:

- plugin discovery
- plugin loading
- contribution registration
- plugin package settings metadata

Primary packages:

- `plugins/`

Notes:

- this layer owns package lifecycle only
- tools and sensors return to their owning runtime layers after registration

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

- `L0` working context
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

Notes:

- **Tool taxonomy (ADR-0002):** two tool species share one origin-agnostic registry — **capability tools** (do work; depend only on `magi_plugin_sdk` + host-injected capability ports; first-party ≡ third-party; extensible) and **runtime-control tools** (drive agent execution state; host-owned, closed; live in `control/tools/` (L4) and `agent/runtime_tools/` (L12), registered via the composition root). The `plugin-isolation` contract governs only capability-tool code (`tools/builtin`, `tools/code_agent`): SDK-only, never host internals.
- **Capability ports:** the host hands capabilities to tools via a `ToolCapabilities` bundle on `ToolExecutionContext` (SDK Protocols the host implements): trace, delegation-events, background, session-cache, chat, memory-query, image-gen, interaction (ask), detach. A tool depends on the Protocol, never the host package.
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
- L9 may consume task/runtime hints from L12 and profile/memory state from lower layers, but persona-specific trigger interpretation must not be duplicated in chat handlers, context rendering, or post-processing.
- post-processing may update future relationship and dynamic state; it should not be the primary place where the already emitted turn's persona mode is chosen.

### L10. Sensors Layer

Responsibilities:

- inbound sensors (domain-neutral `SensorBase` and `SensorOutput`)
- sensor memory policy (`SensorMemoryPolicy`) controlling L0–L4 routing
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

1. **Run Engine** — `FunctionCallingOrchestrator` (`agent/execution/`) + `NodeSequenceRunner` + the node framework (`agent/run/`): a bounded LLM↔tool run. Domain-agnostic and **chat-free** — already used headless by worker / subagent / background. The engine does not runtime-import handlers (they are injected; only TYPE_CHECKING refs exist).
2. **Generic handler framework** — `TaskAgent` base, `BaseExecutionHandler`, execution contracts, and the handler *algorithms* (`DirectLLMHandler` / `FunctionCallingHandler`) in `agent/task_agents/handlers/`. Domain-agnostic; drives the engine through **injected service Protocols** (`agent/task_agents/common/service_protocols.py`). Generic across drivers (chat today; voice / batch / scheduled next).
3. **Domain drivers** — the surface-specific composition, in `chat/task_agent/` (L14): `ChatTaskAgent` + factory + the `Chat{Prompt,Planning,History}Service` + postprocess / transcript / reply-context + the run/session state machine (`ChatExecutionCoordinator` / `session_run_*` / `run_store*`) + conversational services (fact-classifier / interruption / rhythm / streaming). A driver lives in its **highest domain layer**, implements the ring-2 Protocols, and is dispatched by type via an injected factory the agent runtime never hard-imports (ADR-0003). The chat driver is constructed via `create_chat_agent_factory` injected from the composition root (`bootstrap/`), so `agent/lifecycle.py` does not import chat.

Seam status: **both seams are inverted & clean.** Ring 1 ↔ 2 — engine request/result contracts + `AttachmentResolverPort` (`agent/run/ports.py`, ADR-0004 P1). Ring 2 ↔ 3 — handler bundle typed against ring-2 Protocols; the **entire** chat driver (incl. `ChatExecutionCoordinator` + the run/session machine) relocated to `chat/task_agent/`; the generic ring-2 package renamed `agent/task_agents/chat/` → `agent/task_agents/handlers/`; factory wiring inverted to the composition root (ADR-0004 P2 / ADR-0003). The `agent → chat` task-agent debt is retired. *Remaining (separate concerns, not the descent):* `TimelineTaskAgent` → `timeline` (same rule, by-need); a few `agent.* → chat.workspace` consumers (a different subsystem — the agent working-context store).

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

Notes:

- the Rust gateway (`crates/magi-gateway/`) handles static database reads, config file I/O, and session/task mutations natively
- requests requiring the Python runtime are dispatched via IPC `api.forward` to FastAPI routers running as an in-memory ASGI app
- `chat/` owns transcript truth (`chat.db`), attachment storage, and session workspace; it is not the memory layer
- `channels/` provides bidirectional adapters for external messaging platforms; each channel routes messages into the standard chat pipeline

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

### Personality versus memory contract

- memory should stay relatively factual and traceable
- personality may carry subjective or relational interpretation
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
- `core/`, `scheduler/`, `runtime_trace/`, parts of `utils/` -> L1 application infrastructure
- `config/` -> L2 configuration
- `events/` -> L3 message bus
- `control/` (incl. `control/tools/` host runtime-control tools plan/todo) -> L4 control plane
- `plugins/` -> L5 plugin registration
- `llm/` -> L6 LLM runtime
- `memory/` -> L7 memory
- `tools/`, `skills/` -> L8 tools and skills (`skills/` is the host skill-execution engine; `mcp/` bridges MCP servers — both are host tool-source integrations like `plugins/`, NOT plugin-implementation code)
- `personality/` -> L9 personality
- `awareness/`, event emitter -> L10 sensors
- `context/` -> L11 context
- `agent/` (incl. `agent/runtime_tools/` host runtime-control tool agent_tool) -> L12 agent runtime
- `timeline/` -> L13 timeline domain
- `api/`, `chat/`, `tasks/`, `channels/` -> L14 external services
- `ipc/`, `transport/` and `crates/magi-gateway/` -> L15 connection and transport

The boundary rules above should remain stable even as package internals evolve.
