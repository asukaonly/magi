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
- selected infrastructure helpers in `bootstrap/exports.py`

Notes:

- the scheduler engine is infrastructure, even if bootstrap starts it later in dependency order
- bootstrap order and ownership layer are not the same thing
- `runtime_trace/` stores execution observability data; it is not durable memory and does not participate in L6 recall
- workspace storage is an infrastructure facade: `core` owns workspace identity, path safety, generated directory creation, and state manifests; upper layers receive scoped paths instead of constructing `<workspace>/.magi` paths directly

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

### L4. Plugin Registration Layer

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

### L5. LLM Runtime

Responsibilities:

- provider routing
- scenario-specific model selection
- chat and generation adapters
- usage-event publication

Primary packages:

- `llm/`

### L6. Memory Layer

Responsibilities:

- `L0` working context
- `L1` event memory
- `L2` structured cognition
- `L3` reflection summaries
- `L4` procedural memory
- retrieval across those layers

Primary packages:

- `memory/`

### L7. Tools And Skills Layer

Responsibilities:

- built-in tools
- provider-backed tools
- built-in and external skills

Primary packages:

- `tools/`
- `skills/`

### L8. Personality Layer

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

- L8 owns `PersonaTurnPlanner` and the `PersonaTurnPlan` contract described in [Persona Runtime Architecture](./persona-runtime-architecture.md).
- L8 may consume task/runtime hints from L11 and profile/memory state from lower layers, but persona-specific trigger interpretation must not be duplicated in chat handlers, context rendering, or post-processing.
- post-processing may update future relationship and dynamic state; it should not be the primary place where the already emitted turn's persona mode is chosen.

### L9. Sensors Layer

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
- `SensorIngestionGateway` routes outputs to memory (L6), timeline (L12), and knowledge graph

### L10. Context Layer

Responsibilities:

- prompt-context assembly
- recall shaping
- prompt rendering from typed context inputs, including the `PersonaTurnPlan` produced by L8

Primary packages:

- `context/`

Notes:

- L10 consumes the persona behavior plan and renders it into the final system prompt.
- L10 should not classify registers, activate persona triggers, or evaluate relationship layers itself.
- scenario prompt storage should not become a second source of persona behavior truth; persona registers and trigger behavior belong in L8 persona config.

### L11. Agent Runtime

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
- `agent/task_orchestrator.py`

Notes:

- `agent/runtime/` is the correct L11 home for runtime control flow
- it is not a replacement for infrastructure and should not be described as a second `core/`

### L12. Timeline Domain

Responsibilities:

- timeline read models (`TimelineEvent` is L12-internal, not exported)
- scale-aware viewport and context-bundle read models
- timeline adapter (`TimelineAdapter`) stores host-rendered `TimelineEvent` objects
- timeline normalization and insight extraction
- scheduled source sync policy

Primary packages:

- `timeline/`

Notes:

- `TimelineEvent` is an L12-internal view model; sensors produce `SensorOutput` (L9)
- host projection is the sole owner of timeline display rendering from `SensorOutput.activity` + `SensorOutput.narration`
- `TimelineAdapter` is the sole entry point for rendered timeline events into the timeline read model

### L13. External Services

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

### L14. Connection And Transport

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

- sensors (L9) produce domain-neutral `SensorOutput` with per-sensor `SensorMemoryPolicy`
- `SensorIngestionGateway` (L9) routes each output to memory (L6) and optionally to timeline (L12)
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
- `plugins/` -> L4 plugin registration
- `llm/` -> L5 LLM runtime
- `memory/` -> L6 memory
- `tools/`, `skills/` -> L7 tools and skills
- `personality/` -> L8 personality
- `awareness/`, event emitter -> L9 sensors
- `context/` -> L10 context
- `agent/` -> L11 agent runtime
- `timeline/` -> L12 timeline domain
- `api/`, `chat/`, `tasks/`, `channels/` -> L13 external services
- `ipc/`, `transport/` and `crates/magi-gateway/` -> L14 connection and transport

The boundary rules above should remain stable even as package internals evolve.
