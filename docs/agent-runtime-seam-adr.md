# ADR-0004: Unified Agent Run Seam

**Status:** Accepted and implemented
**Date:** 2026-06-02
**Revised:** 2026-08-24
**Deciders:** maintainers (architecture owners)
**Subsumes:** [ADR-0003 Domain Task-Agents Belong in Their Domain Layer](./domain-task-agents-adr.md)

## Context

Magi has multiple ways to start work: native chat, external channels,
background continuation, scheduled work, and child delegation. Historically,
ordinary chat was divided by a semantic pre-router into direct, tool, explore,
and orchestration executors. Session-bound chat also had a separate loop from
headless work.

That structure gave predicted intent too much control over execution topology:

- a wrong classification could remove tools or select the wrong executor
- direct and tool turns duplicated model-facing control flow
- orchestration had its own graph, state, and persistence vocabulary
- interruption policy was tied to chat-specific loop branches
- observability had to reconstruct one conceptual run from incompatible events

Modern models can decide whether to answer, inspect, call tools, plan, or
delegate after seeing the real context. Code still needs to govern permissions,
side effects, budgets, cancellation, validation, persistence, and recovery.

## Decision

All agent work uses one typed run seam:

```text
trigger
  -> domain admission / driver
  -> AgentRunRequest
  -> AgentRunHandler
  -> FunctionCallingOrchestrator
  -> FunctionCallingLoopRunner
  -> final result + durable run events
```

### 1. Trigger

Every run carries a typed `RunTrigger`, such as `user_message`,
`external_inbound`, `scheduled`, or `batch`. A trigger identifies why work
started; it does not choose an execution profile.

### 2. Domain driver

The owning domain performs deterministic admission and owns its I/O semantics.
For chat this includes slash-command parsing, session state, attachments,
history, streaming, safe-boundary input, and transcript projection. The driver
constructs `AgentRunRequest` and injects domain ports; it does not semantically
classify ordinary requests into separate model-facing chains.

### 3. Unified run engine

`AgentRunHandler` is the single ordinary model-facing handler.
`FunctionCallingOrchestrator` and `FunctionCallingLoopRunner` run the bounded
model/tool loop. A direct response is the zero-tool path through the same loop,
not a separate executor.

The request carries explicit capabilities, reasoning policy, bounds,
cancellation, journal/checkpoint services, and optional domain collaborators.
Headless constructors omit chat-only fields by construction.

One canonical `run_id` owns journal events, tool context, versioned plans,
checkpoints, and child parent links. Background scheduling has a separate
`task_id`; detach resumes the same run and verifies the checkpoint's plan ID and
version through an injected run-bound plan reader.

### 4. Runtime governance

The main model owns semantic decisions inside the loop. Runtime code owns:

- tool visibility and authorization through capability policy
- side-effect classification, approval, and effect recording
- bounded iteration, token, time, repair, and child-run budgets
- validation and completion gates
- reasoning-depth limits and evidence-driven escalation
- cancellation and safe-boundary input application
- durable lifecycle events and recovery checkpoints

This is the governing rule: **the model decides meaning; code enforces policy.**

### 5. Child runs

Delegation is a bounded child run through `ChildRunCoordinator`, using the same
engine with a restricted preset. Parent/child lifecycle is recorded in the run
journal. There is no separate orchestration graph, orchestration identifier, or
worker-specific completion protocol.

### 6. Durable event seam

Each run appends canonical lifecycle events to the run journal. Current plan,
child, validation, repair, reasoning, effect, and terminal state are projections
of those events. UI trace state and runtime metrics use the same source rather
than parallel transcript-only state.

The durable seam records context fingerprints and provenance, not a replay copy
of raw prompts, history, attachment bytes, or rendered memory/persona context.
Run manifests are insert-once; a second writer for the same run identity is an
integrity failure rather than an overwrite.

## Consequences

### Benefits

- ordinary chat has no serial semantic-router call
- simple turns take the shortest path without losing tool availability
- complex turns can discover their real shape after execution begins
- chat and headless work share control, budget, cancellation, and journal rules
- delegation, planning, validation, and reasoning escalation are visible as one
  run rather than unrelated subsystems
- obsolete direct/explore/orchestration state can be deleted

### Costs

- the main model always receives the governed tool/control surface appropriate
  to the run, so schema size must be managed by capability policy
- loop policy is now load-bearing and requires focused tests around effects,
  completion, cancellation, recovery, and bounds
- domain drivers must respect the typed seam instead of reaching into loop
  internals

## Rejected Alternatives

### Keep semantic routing and only improve its labels

Rejected. Better labels cannot remove the extra call, disagreement between
predicted route and real execution needs, or duplicated executors.

### Keep a separate direct-response executor

Rejected. It optimizes a path already represented by a unified loop with no
tool calls and creates a second place for prompt, streaming, and cancellation
behavior to drift.

### Keep a special orchestration graph

Rejected. Bounded child runs express delegation without a second lifecycle,
state machine, persistence model, and frontend vocabulary.

### Add a speculative driver registry

Deferred until two domain drivers need runtime polymorphic dispatch. The typed
request seam and dependency direction are required now; a registry is not.

## Verification

Architecture tests must enforce:

- agent-core packages do not import chat-domain implementations
- all ordinary chat work enters through `AgentRunRequest`
- headless requests cannot carry chat-only control services
- child runs use the unified engine and restricted capability presets
- cancellation, planning, validation, and terminal states append canonical run
  events

The complete current runtime contract is documented in
[Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).
