# Layered Agent Architecture

## Purpose

This document is the backend boundary source of truth for Magi.

Use it to answer three questions:

- which layer owns a piece of code or runtime behavior
- which dependencies are allowed across layers
- where lifecycle assembly stops and business logic begins

Read it together with [Project Overview](./project-overview.md), [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md), and [Unified Plugin Extension Architecture](./plugin-extension-architecture.md).

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
- database initialization
- maintenance dependencies
- shared infrastructure exports

Primary packages:

- `core/`
- selected infrastructure helpers in `bootstrap/exports.py`

Notes:

- the scheduler engine is infrastructure, even if bootstrap starts it later in dependency order
- bootstrap order and ownership layer are not the same thing

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
- tools, sensors, and actions return to their owning runtime layers after registration

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

- personality state
- subjective user interpretation from the personality perspective
- tone and style behavior

Primary packages:

- `personality/`

### L9. Sensors And Actions Layer

Responsibilities:

- inbound sensors
- outbound actions
- action emission and action-target registration

Primary packages:

- `awareness/`

Notes:

- plugin-contributed sensors and actions are registered in `plugins/`, but runtime execution belongs here

### L10. Context Layer

Responsibilities:

- prompt-context assembly
- recall shaping
- scenario prompt composition

Primary packages:

- `context/`

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

- timeline ingestion
- timeline queries
- timeline normalization and insight extraction
- scheduled source sync policy

Primary packages:

- `timeline/`

### L13. External Services

Responsibilities:

- product-facing routers
- application services
- read and write service contracts

Primary packages:

- `api/routers/`
- `api/services/`

### L14. Connection And Transport

Responsibilities:

- websocket connection lifecycle
- websocket protocol handling
- transport-side push and session handling
- thin HTTP app and middleware wiring

Primary packages:

- `websocket/`
- thin app wiring in `backend_app.py` and related transport setup modules

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
- timeline, agent, and action layers own scheduling policy and target registration
- scheduled execution should enter the owning layer through typed target handlers rather than scattered ad hoc loops

### Plugin contract

- plugins own discovery, package lifecycle, and contribution registration
- registries expose the registered capability surfaces
- plugin registration must not become a place where domain behavior is reimplemented

### Tool versus action contract

- tools are agent-callable capabilities
- actions are outbound side effects
- an action may expose a tool adapter, but the concepts remain distinct

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

### Timeline Versus Memory Contract

- timeline is the primary domain for user behavior and event-bearing history
- memory is the lifecycle system that retains, derives, summarizes, and retrieves durable knowledge from runtime and timeline inputs
- raw behavioral facts should enter timeline or event memory first, then flow into downstream memory processing where appropriate

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

## Suggested Package Mapping

The current codebase already roughly maps to this target model:

- `bootstrap/` -> outer composition root, not a numbered layer
- `core/`, parts of `utils/` -> L1 application infrastructure
- `config/` -> L2 configuration
- `events/` -> L3 message bus
- `plugins/` -> L4 plugin registration
- `llm/` -> L5 LLM runtime
- `memory/` -> L6 memory
- `tools/`, `skills/` -> L7 tools and skills
- `personality/` -> L8 personality
- `awareness/`, action registries and handlers -> L9 sensors and actions
- `context/` -> L10 context
- `agent/` -> L11 agent runtime
- `timeline/` -> L12 timeline domain
- `api/` -> L13 external services
- `websocket/` and connection-specific API glue -> L14 connection and transport

`runtime/` should enter the deletion path as refactors land. The target package model is `bootstrap/` for the outer composition root plus `core/` for L1 infrastructure. If a module belongs to one of the numbered layers, it should eventually live there instead of remaining in a generic runtime package.

This mapping is approximate and may continue to evolve during refactors, but the boundary rules above should remain stable.
