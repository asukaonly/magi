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

## Refinement (grounded during P1 execution, 2026-06-02)

Grounding P1 against the code refined the Engine/Driver picture into **three concentric rings**, each separated from the next by a dependency-inversion seam:

| Ring | What | Where | Status |
|---|---|---|---|
| **1 — Run Engine** | `FunctionCallingOrchestrator` (`agent/execution`) + `NodeSequenceRunner` + node framework (`agent/run`): a bounded LLM↔tool run | agent core | domain-agnostic; already used headless by worker / subagent / background |
| **2 — Generic handler framework** | `TaskAgent` base, `BaseExecutionHandler`, execution contracts (`ExecutionRequest/Result`), and the handler *algorithms* (`DirectLLMHandler` / `FunctionCallingHandler`) | `agent/task_agents` (generic part) | algorithms are domain-agnostic; drive the engine through **injected services** |
| **3 — Domain drivers** | chat: coordinator + `Chat{Prompt,Planning,History}Service` + postprocess / transcript / session / reply-context + run stores; timeline likewise | their own domain layer (chat L14, timeline L13) | own domain I/O + data |

**Seams:**
- **Ring 1 ↔ Ring 2** — engine request/result contracts + `AttachmentResolverPort` + TYPE_CHECKING-only handler refs (handlers are injected, not runtime-imported by the engine). **Inverted & clean as of P1** (commit `c6cc4841`; the lint ratchet locks it).
- **Ring 2 ↔ Ring 3** — inverted and clean: the handler bundle is typed against ring-2 service Protocols, generic handlers live in `agent/task_agents/handlers/`, and the chat driver lives in `chat/task_agent/`.

**Correction to the original P1 idea:** "relocate the handlers into the engine" was wrong — the handlers are Ring 2 (generic algorithms), not Ring 1 (the engine). P2 instead defined service Protocols, retyped the bundle, moved the generic handlers to their own ring-2 package, and kept the chat implementations in the chat layer.

## Staging
- **P1 — Run Engine is chat-free. ✅ DONE.** Severed the engine's only chat coupling (attachment-payload resolution) behind `AttachmentResolverPort`; the engine + the shared `message_utils` no longer import `magi.chat`; two layers-baseline edges retired (commit `c6cc4841`, lint `2 kept, 0 broken`). Ring 1 is domain-agnostic and lint-locked. (The handler relocation originally imagined here was reassigned to P2 — see Refinement.)
- **P2 — Ring 2↔3 inversion + chat driver descent. ✅ DONE.** Generic handler-service Protocols live in Ring 2; handlers live in `agent/task_agents/handlers/`; the full chat driver, coordinator, and stores live in `chat/task_agent/`; dispatch is injected from the composition root. The `agent → chat` task-agent cluster is retired.
- **P3 — Trigger abstraction. ✅ DONE.** `RunTrigger` lifted out of chat's `SessionRunCoordinator` into a standalone, side-effect-free trigger seam (`agent/run_triggers.py: build_user_message_trigger` / `is_external_source`); built source-aware for every entry (native chat → `user_message`, external channel → `external_inbound`, scheduler → `scheduled`, batch → `batch`). The original P3 implementation checkpointed the foreground trigger in the then-broader L0 workbench. Current ownership is narrower: a live chat run keeps its trigger in process, detached/headless work persists it on the background specification, and restarted foreground chat reconstructs it from the durable delivery envelope. L0 now owns short-term attention only and does not participate in execution recovery. (PRs #31 3a/3c, #34 3b, #35 detach, #36 auto-dispatch.) *Note:* the `RunRequest` projection exists (`BackgroundTaskSpec.as_run_request()`) but is not yet **consumed** — a unified RunRequest-dispatch waits on the P4 driver registry.
- **P4 — Generalize.** Split into two parts; the high-value half landed, the speculative half is parked:
  - **Engine front door. ✅ DONE.** The Run Engine now has a single typed entry — `FunctionCallingOrchestrator.run(EngineRunInput)` — a parameter object mirroring `execute_with_tools` 1:1 (parity-locked by test). All **four** call sites (chat, background, worker, subagent) go through it; the three headless surfaces use `EngineRunInput.headless(...)`, which structurally can't smuggle in chat-only session/control fields. This is the load-bearing seam a future driver builds. (PRs #38 1a, #39 1b.)
  - **Driver registry — ⏸️ DEFERRED (YAGNI).** A full registry (`RunDriver` protocol + dispatch-by-type, with batch/voice/scheduled as registered drivers) is **not justified yet**: voice has zero code, `RunRequest` has no consumer, chat/scheduled are architecturally stable, and "batch as a real driver" is mostly code-movement (the engine runs an LLM↔tool loop from prompt+tools and can't consume structured batch input without gaining batch-awareness — more coupling, not less). Revisit when a **second real driver** (voice, or a heavier scheduled-agent run) actually needs polymorphic dispatch — that is when the registry's "add a surface = add a driver, core unchanged" payoff materializes. Timeline-driver relocation likewise waits on real need.

## Action Items
1. [x] P1: Run Engine made chat-free via `AttachmentResolverPort` (commit `c6cc4841`); engine + `message_utils` no longer import `magi.chat`; baseline −2 edges; lint `2 kept, 0 broken`. (Grounding reassigned the handler relocation to P2.)
2. [x] P2 (= ADR-0003, sharpened) — complete: service Protocol inversion, generic handler relocation, full chat-driver/coordinator descent, and composition-root factory injection all landed. The remaining `agent.* → chat.workspace` consumers belong to a separate working-context boundary.
3. [x] P3: trigger seam — `RunTrigger` lifted to `agent/run_triggers.py`, built per source, propagated to background specs at detach + auto-dispatch, and reconstructed for restarted foreground chat from the delivery envelope; the earlier L0 persistence path was retired when L0 narrowed to short-term attention (PRs #31/#34/#35/#36). `RunRequest` projection exists but is not yet consumed (waits on the registry).
4. [x] P4 (engine front door): single typed `orchestrator.run(EngineRunInput)`; all four call sites (chat/background/worker/subagent) unified, parity-locked (PRs #38/#39).
5. [ ] P4 (driver registry) — **DEFERRED (YAGNI)**: revisit when a second real driver (voice / heavier scheduled-agent) needs polymorphic dispatch. Timeline-driver relocation rides along.
6. [x] Update `layered-agent-architecture.md` with the Engine/Driver/Trigger model — L12 "three rings" now records the trigger seam (P3) + engine front door (P4) + the deferred driver registry.
