# Layered Agent Architecture

## Purpose

This document defines the target layered architecture for Magi's backend runtime.

It exists to make layer boundaries, naming, and dependency rules explicit before or during implementation work. It is the conceptual source of truth for the architecture diagram and should be read together with:

- [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
- [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md)
- [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md)

This document describes the target model. Current implementation details may lag behind it during refactors.

## Architecture Intent

Magi is not a single chat loop with a pile of attached utilities. It is a layered agent system with:

- infrastructure layers for configuration, transport, scheduling, and reliability
- capability layers for models, memory, tools, sensors, and actions
- behavior layers for personality, context assembly, and agent orchestration
- business-domain layers for timeline and external application services

The main design goal is to keep registration, execution, orchestration, and business semantics separate so the system can evolve without collapsing into one large runtime module.

One more rule follows from that goal:

- the system composition root is not itself a business layer
- startup and shutdown assembly should live in a thin outer bootstrap boundary
- layer-owned lifecycle logic should live with the owning layer, not in a central runtime package

## Dependency Rules

The default dependency rule is:

- upper layers may depend on lower layers
- lower layers must not depend on upper layers
- same-layer modules should communicate through typed contracts, registries, or the message bus rather than direct ad hoc coupling

The layer stack describes default structural dependency, not every runtime data flow. Some business flows cross layers through events, registries, or scheduled dispatch.

The composition root is a special case:

- it may assemble all layers
- it should stay thin
- it should not become a new "super-layer" that owns business logic on behalf of the layers

## Layer Stack

The target backend architecture has fourteen layers, ordered from low-level infrastructure to external-facing connection handling.

### L1. Application Infrastructure

Responsibilities:

- logging
- DI container and runtime wiring
- health checks
- connection pools and shared resource management
- scheduler engine bootstrap
- database initialization

Notes:

- the scheduler engine belongs here because it is shared infrastructure
- this layer provides scheduling capability, but it does not own domain scheduling policy
- `core/` should converge toward this layer only; non-L1 runtime or business logic should move out

### L2. Configuration

Responsibilities:

- application configuration
- LLM configuration
- plugin configuration
- personality configuration
- tool configuration
- memory configuration

Notes:

- configuration is a first-class layer because most runtime behavior is product-configurable
- global host config and plugin-owned config should remain distinct

### L3. Message Bus

Responsibilities:

- event transport
- consumer offsets or progress tracking
- replay support
- failure recovery and retry coordination

Notes:

- this layer is the default decoupling point for asynchronous cross-layer communication
- message persistence is infrastructure, not memory

### L4. Plugin Registration Layer

Responsibilities:

- plugin discovery
- plugin loading
- contribution registration
- plugin lifecycle management
- plugin settings metadata exposure

Contribution families currently include:

- tools
- sensors
- actions
- future domain-specific extensions such as memory or personality contributions

Notes:

- this layer is a registration layer, not a business execution layer
- plugin-contributed capabilities belong to their owning layers after registration
- a plugin may contribute multiple capability families without collapsing those concepts into one runtime surface

### L5. LLM Runtime

Responsibilities:

- text generation
- streaming generation
- embeddings
- image generation
- audio generation
- video generation
- provider and model routing

Notes:

- this layer owns model invocation capability, not prompt business logic
- capability-specific contracts should stay explicit because not every model supports every mode

### L6. Memory Layer

Responsibilities:

- working memory
- event memory
- structured cognition
- reflection summaries
- procedural memory
- memory retrieval interfaces

Recommended conceptual framing:

- `L0`: working context and checkpoint state
- `L1`: event memory and canonical factual history
- `L2`: structured cognition derived from retained events
- `L3`: reflective summaries and durable insights
- `L4`: procedural memory and reusable execution heuristics

Notes:

- memory types such as preferences, tool experience, or user facts should be treated as memory content categories, not as independent storage layers
- the memory layer is responsible for neutral or traceable memory representations unless explicitly delegated elsewhere

### L7. Tools And Skills Layer

Responsibilities:

- built-in tools
- built-in skills
- plugin-provided tools
- third-party skills

Notes:

- these are agent-callable capabilities
- this layer should not be named as if tools belong to the LLM itself; they belong to the agent runtime

### L8. Personality Layer

Responsibilities:

- personality maintenance
- state transitions
- style and companionship behavior
- behavior evolution
- emotional or affective state handling
- long-term subjective user modeling from the personality perspective

Notes:

- this layer includes system-prompt-level behavior, state machine behavior, and long-term personality-driven interpretation
- personality memory is intentionally distinct from neutral memory-layer cognition
- if both layers describe a user, memory should stay relatively factual while personality may maintain subjective or relational interpretation

### L9. Sensors And Actions Layer

Responsibilities:

- built-in sensors
- plugin sensors
- built-in actions
- plugin actions

Definitions:

- sensors observe or collect information from the environment or user-facing sources
- actions produce external effects such as notifying the user, sending email, or calling a webhook

Notes:

- actions are outbound capabilities and should be named as such to avoid confusion with executor internals
- sensors and actions are peer modules in the same layer
- this layer provides capability surfaces to higher layers but does not own task orchestration

### L10. Context Layer

Responsibilities:

- prompt-context assembly
- long-context compression
- scenario prompt composition
- recall shaping for downstream agent execution

Notes:

- this should be the primary prompt assembly boundary
- higher layers may request context, but should avoid assembling prompts ad hoc in multiple places

### L11. Agent Runtime

Responsibilities:

- task-agent management
- routing and dispatch
- execution mode selection
- function calling orchestration
- task decomposition and worker coordination

Notes:

- this layer owns agent control flow
- it consumes tools, memory, personality, context, sensors, and actions, but should not absorb their internal logic

### L12. Timeline Domain

Responsibilities:

- timeline ingestion
- timeline queries and read models
- timeline insight extraction
- timeline tasks and scheduled sync workflows

Notes:

- timeline is a core business domain, not an optional accessory module
- timeline is the primary domain for user behavior capture and event-bearing history
- timeline facts may feed memory lifecycle processing, but timeline and memory are not identical concepts

### L13. External Services

Responsibilities:

- API routers
- application services
- read and write endpoints
- backend product-facing service orchestration

Notes:

- this layer exposes product capabilities to clients
- it should not be treated as raw transport plumbing

### L14. Connection And Transport Layer

Responsibilities:

- HTTP transport handling
- WebSocket connection management
- protocol session lifecycle
- connection-oriented event push

Notes:

- this layer handles transport and connection concerns only
- business decisions should remain below this layer

## Boundary Contracts

The following boundary statements are part of the target architecture and should be preserved during implementation.

### Scheduler Contract

- the scheduler engine belongs to application infrastructure
- domain layers do not own the scheduler engine itself
- if a layer needs scheduled work, it should register schedules into the scheduler through a defined contributor contract
- scheduling policy belongs to the owning domain layer, while trigger execution belongs to the scheduler engine

### Composition Root Contract

- backend startup and shutdown assembly should live in a thin outer bootstrap package or boundary
- bootstrap may collect lifecycle modules from all layers, but should not own layer-specific business logic
- layer lifecycle definitions should live in the owning layer package
- `core/` is the target home for L1 infrastructure concerns
- `runtime/` should not remain a second pseudo-infrastructure package if `core/` already represents L1 infrastructure
- if a module is not part of the outer composition root and does not belong to L1 infrastructure, it should move into its owning numbered layer instead of staying under `runtime/`

### Plugin Contract

- the plugin system owns package lifecycle and contribution registration
- tools, sensors, actions, and future contribution types still belong to their runtime layers after registration
- plugin architecture must not be used as an excuse to move domain behavior into the registration layer

### Tool Versus Action Contract

- tools are agent-callable capabilities, typically exposed to the LLM through function-calling or equivalent orchestration
- actions are outbound side-effect capabilities that affect the outside world
- an action may expose a tool adapter so the LLM can call it, but that does not turn the action into a tool conceptually

### Personality Versus Memory Contract

- the personality layer owns style, companionship, state transitions, and subjective long-term interpretation
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
