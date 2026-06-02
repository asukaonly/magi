# ADR-0004: Agent Runtime — Engine / Driver / Trigger Seam

**Status:** Accepted
**Date:** 2026-06-02
**Deciders:** maintainers (architecture owners)
**Subsumes:** [ADR-0003 Domain Task-Agents Belong in Their Domain Layer](./domain-task-agents-adr.md) (its "relocate the chat driver" is component **P2** here)
**Motivated by:** the Batch Orchestrator design (`docs/superpowers/specs/2026-06-02-batch-orchestrator-design.md`) + upcoming voice and scheduled-background scenarios — all are "drive the agent differently."

## Context

First principles (ADR-0003): the **agent runtime is the core capability; chat, voice, batch, scheduled tasks, channels are *surfaces / drivers* that invoke it.** The agent must not depend on any one surface.

Today chat is effectively baked into the agent core: the chat task-agent lives in `agent/`, the generic run-loop handlers (`DirectLLMHandler`, `FunctionCallingHandler`) are mis-filed under `agent/task_agents/chat/` yet used by the generic `agent/run/nodes/`, and `agent/lifecycle.py` wires the agent runtime with chat collaborators (`chat_store`, `chat_projector`, `chat_read_service`). Result: `agent → chat` debt, and **the agent cannot be driven for non-chat work without dragging chat's machinery.**

Three imminent scenarios are all the **same shape** — trigger + drive the agent, differing only in *how they're triggered, their turn semantics, and where I/O goes*:
- **Batch orchestrator** (now): manifest-driven, per-item bounded runs, no transcript.
- **Voice** (next): streaming / barge-in turn semantics, TTS I/O.
- **Scheduled background tasks** (next): scheduler-triggered, headless, no session, store result.

Each will hit the chat entanglement. The pieces to build a clean seam already exist but are scattered/entangled: the run engine (`FunctionCallingOrchestrator.execute_with_tools`, `NodeSequenceRunner.run`), the trigger contract (`RunTrigger` / `IncomingEvent` — already in `magi_plugin_sdk.run_trigger`, but assembled inside chat's `session_run_coordinator`), the background substrate (`BackgroundManager.enqueue`), and scheduler typed-target dispatch.

## Decision

**Structure the agent runtime as three clean concerns: a domain-agnostic Run Engine, pluggable Drivers (one per surface), and pluggable Triggers (one per source).**

### 1. Run Engine (agent core, domain-agnostic, reusable)
Runs a **bounded LLM↔tool run** and emits a generic **event stream**. Input is a `RunRequest { instructions, input, tools, context(capabilities/permissions/cancellation), bounds }`; output is events (`started · tool_call · needs_review · token · completed · failed`). Built from `FunctionCallingOrchestrator` + `NodeSequenceRunner` + the generic run-loop handlers. **Knows nothing about chat / voice / batch.** The bounded run is the reusable unit OpenClaw/Hermes converge on ("a sub-agent that runs its own session and reports back" ≠ "one long thread").

### 2. Drivers (one per surface, each in its own domain layer)
A driver **owns its turn semantics + I/O + domain data**. It builds `RunRequest`s (from a trigger + domain data), consumes the engine's event stream, and lands the output. It registers with the engine's **driver registry** (dispatch by type, no core import). Examples: `chat` (transcript + UI stream), `voice` (TTS + barge-in), `batch` (per-item, manifest), `scheduled-task` (headless, store result), `timeline`.

### 3. Triggers (one per source, pluggable)
A trigger source turns an external signal into a `RunRequest` for a driver: user-message, **scheduler tick** (typed target — already exists), **inbound event** (`RunTrigger`/`IncomingEvent` — already an SDK contract), **item-queue** (batch self-enqueue). Triggers are decoupled from drivers and from the engine.

**End-state:** the `agent` package contains only Engine + Driver registry + Trigger abstraction + the control plane (`magi.control`). Drivers live in their domains and register. Adding a surface = a new Driver (+ maybe a Trigger); **the engine and core do not change.** `agent → chat` / `agent → timeline` disappear.

## Options Considered
- **A — keep chat baked into the agent core (status quo):** every new surface (batch/voice/scheduled) either drags chat's machinery or forks it. Rejected — it's the debt that bites exactly now.
- **B — Engine / Driver / Trigger seam (chosen):** one reusable engine; surfaces are pluggable drivers; sources are pluggable triggers. Serves all three scenarios with zero core change; matches the agent-then-surface principle; reuses the already-present pieces (RunTrigger SDK contract, scheduler targets, BackgroundManager).
- **C — lower the chat store (ADR-0001 pattern applied to chat):** only legalizes the wrong direction; doesn't give a reusable headless engine. Rejected (superseded reasoning from ADR-0003).

## Consequences
**Easier**
- Batch, voice, scheduled-background each become a Driver (+ Trigger) on a clean engine — no chat baggage, no core change.
- The agent core is independently testable/reusable (headless); `agent → chat`/`timeline` retired.
- A single mental model ("trigger → driver → engine") for every present and future surface.

**Harder / staged**
- Real refactor of the agent core's most central area; must preserve chat behavior exactly. Done in stages (below), lowest-risk first.
- The Engine/Driver/Trigger contracts must be defined carefully (the `RunRequest` + event stream is the load-bearing seam).

## Staging (P1 first — motivated by the batch orchestrator)
- **P1 — Extract the Run Engine.** Pull the generic run-loop (handlers `DirectLLMHandler`/`FunctionCallingHandler` + the bounded-run + the generic background completion handshake) out of `agent/task_agents/chat/` into the generic agent runtime; define the `RunRequest` + event-stream contract. **Low-risk, and the batch orchestrator rides it immediately** (a chat-free bounded run, no chat postprocess). No driver moves yet.
- **P2 — Driver registry + relocate the chat driver** (this is ADR-0003's body): formalize driver registration (dispatch by type, no core import); move the chat task-agent into the `chat` layer as the "chat" driver. Retires `agent → chat`.
- **P3 — Trigger abstraction:** lift `RunTrigger`/`IncomingEvent` out of chat's coordinator into a standalone trigger seam; unify scheduler / inbound / item-queue as trigger sources producing `RunRequest`s. **Foundation for scheduled-background and voice.**
- **P4 — Generalize:** relocate the timeline driver; land batch / voice / scheduled-task as drivers+triggers on the seam.

## Action Items
1. [ ] P1: define `RunRequest` + event-stream contract; extract generic run-loop handlers + bounded-run + generic background completion from `chat/` to the agent runtime; verify chat behavior parity + lint `2 kept, 0 broken`; batch orchestrator delegates to the extracted engine.
2. [ ] P2 (= ADR-0003): driver registry + chat driver → `chat` layer; retire `agent → chat` baseline edges.
3. [ ] P3: trigger seam (RunTrigger out of chat; scheduler/inbound/item-queue as sources).
4. [ ] P4: timeline driver relocation; batch/voice/scheduled drivers on the seam.
5. [ ] Update `layered-agent-architecture.md` with the Engine/Driver/Trigger model as each stage lands.
