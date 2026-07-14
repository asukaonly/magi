# ADR-0001: Extract the Control Plane into a Low Layer

**Status:** Accepted
**Date:** 2026-05-31
**Deciders:** maintainers (architecture owners)
**Related:** [Layered Agent Architecture](./layered-agent-architecture.md), [Plugin Extension Architecture](./plugin-extension-architecture.md); Plugin-Boundary Framework A (Phase 2 capability ports, complete)

> This is the first ADR in the repo. It establishes the `docs/control-plane-*` / `docs/<topic>-adr.md` convention: numbered, status-tracked decision records for cross-cutting architecture changes.

## Context

The Framework A plugin-boundary work (move plugin implementations behind `magi_plugin_sdk` so they never import host internals) surfaced a recurring shape: a set of built-in **tools** at L7 (`ask_user_question`, `plan_mode`, `todo_write`, `detach_to_background`, `agent_tool`) reach **up** into the agent runtime's *control* internals at L11 (`magi.agent.control.*`, `magi.agent.run_control`, `magi.agent.workers`, `magi.agent.execution`). The same is true of `magi.skills`.

We have been resolving most plugin→host inversions with **injected capability ports** (`ToolExecutionContext.capabilities`), and that is correct for genuine *capability* tools (file IO, bash, image generation, memory query — done in Phase 2 clusters A–H). But applying the port pattern to the **control** cluster would treat a symptom. A first-principles review (and a code probe) shows the control plane is **mislayered**, not merely "reached by tools."

Facts established by inspection of the original `backend/src/magi/agent/control/`
package, now moved to `backend/src/magi/control/`:

- Its external dependencies are almost entirely **L1 infrastructure**: `core` (logger, DI container, `sqlite_connection_async`), `runtime_trace`, `identity` — plus **L3 `events`** (it publishes control events). It does **not** depend on `agent` runtime internals, `llm`, `memory`, `plugins`, `tools`.
- At the time of this ADR, the **only** file that reached *upward* was `chat_state_persister.py`, which imported `chat` (`ChatMessageRecord`, `get_chat_store`) and transport chat notification helpers. That debt was later retired by moving transcript projection into `chat` and keeping runtime notifications with their owning domains.
- The agent runtime **consumes** control: `agent.execution.function_calling.permission` imports it (permission gating). So the dependency is fundamentally *agent → control*, not the reverse.

**Who reads/writes control state** (plan-mode? todos? pending user question? detach requested? permissions?):
- **tools** — *write* (they are control **actuators**),
- **agent runtime** — *read & drive* (permission gating, plan/detach checks),
- **chat / transport (UI)** — *read* (render plan/todo/ask state) and *write* (deliver user answers).

A substrate read and written by three different layers is **shared infrastructure**, like the event bus (L3) or config (L2) — not domain logic owned by the agent. It belongs **low**, depended on **downward** by everyone, not high at L11.

A second, related observation: `magi.tools.builtin` is not homogeneous. It mixes **capability tools** (file/bash/image/memory — genuine plugin surface) with **runtime-actuator tools** (`ask_user`, `plan_mode`, `todo_write`, `detach_to_background`, `agent_tool` — first-party features wearing a tool costume). The plugin-isolation contract currently polices both identically, which is why the actuators look like "violations."

## Decision

**Extract the control plane out of the agent layer into a new low layer, and make all dependencies on it point downward.** Concretely:

1. **New layer "Control Plane"**, package `magi.control` (moved from `magi.agent.control`), positioned **directly above the message bus (`events`) and below the plugin/llm/memory/tools/agent band**. It owns: the session control-state store, the state machines (ask / plan / todo / detach), the interaction-registry core (`InteractionBroker`'s pending-future table), permission gateway/rules/state, and control-event emission. `magi.agent.run_control` (the detach signal + `current_detach_signal` ContextVar) folds into `magi.control` as well — it is control state, not runtime mechanics.

2. **Invert the one upward coupling.** The logic in `chat_state_persister` (rendering plan/todo/ask state into the transcript) **moves out of control**: `chat` (high layer) **subscribes to control events** and writes the transcript itself (`chat → control`, downward). Control keeps emitting `publish_control_event`; it no longer imports `chat`/`transport`. This retires the existing layers-debt edges.

3. **Interaction answers flow downward.** The `InteractionBroker` core (registry of pending interactions + futures) lives in `magi.control` (low). `transport` (L14) delivers user answers **down** into it (`control.resolve_interaction(id, answer)`), instead of the tool reaching up into a transport-coupled broker.

4. **Distinguish capability tools from runtime-actuator tools.** The control-actuator tools (`ask_user`, `plan_mode`, `todo_write`, `detach_to_background`) and `agent_tool` are **first-party runtime features, not plugins**. They are **relocated out of `magi.tools.builtin`** (the plugin-isolation source scope) into a first-party location that may legitimately depend on `magi.control` and `magi.agent`. After relocation they import `magi.control` directly (downward, legal) — **no capability port is needed for control.**

5. **`agent_tool` and the skill-execution core go to the agent layer.** "A tool that spawns a sub-agent / runs the function-calling orchestrator" is the agent runtime depending on itself — legitimate **inside** the agent layer. These relocate into `magi.agent.*` (out of `magi.tools.builtin` / `magi.skills` plugin scope), not behind a port.

6. **Capability ports stay as built.** The Phase 2 ports for genuine capabilities (trace, delegation-events, background, session-cache, chat, memory-query, image-gen) are the correct pattern for those and are unchanged. The plugin-isolation contract continues to forbid genuine capability plugins from importing `magi.control` (and `magi.agent`, etc.) — control is substrate the *host* may use freely, but a third-party file/bash plugin must not silently drive plan-mode or todos.

## Options Considered

### Option A: Extract control to a new low layer (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | High (one-time): move 19-file package, invert one I/O file, relocate ~5 tools |
| Correctness | Highest — dependencies point down; matches what control *is* (substrate) |
| Net debt | Negative — also retires the existing `control → chat/transport` layers-debt |
| Enforcement | Structural (import-linter layer order); no per-tool exceptions needed |
| Reversibility | Medium — package move is mechanical but touches many import sites |

**Pros:** root-cause fix; J cluster needs **zero ports** (tools import control downward); inverts chat/transport coupling the right way; cleanly separates capability tools from runtime actuators; control becomes independently testable and reusable.
**Cons:** larger one-time refactor than ports; requires renumbering the doc's L4–L14; touches the I/O inversion (chat subscriber) which is behavior-bearing and needs careful tests.

### Option B: Keep control at L11, inject `ControlPort` + `InteractionPort`

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium (incremental, matches Phase 2 pattern) |
| Correctness | Low — enshrines the mislayering; control stays "agent-owned" though it is substrate |
| Net debt | Neutral-to-negative — leaves `control → chat/transport` debt in place |
| Enforcement | Works, but needs wide ports (store+broker+persister+events) and per-tool wiring |
| Reversibility | Easy |

**Pros:** incremental; reuses the established capability-port machinery; no layer renumber.
**Cons:** treats a symptom; the widest ports in the project (4 host objects behind 2 ports); does nothing for the chat/transport inversion; perpetuates "everything in tools.builtin is a plugin."

### Option C: Do nothing (leave control edges frozen in the baseline)

| Dimension | Assessment |
|-----------|------------|
| Complexity | None |
| Correctness | Lowest |
| Net debt | Frozen (12 plugin-isolation + the layers-debt edges remain) |

**Pros:** zero effort.
**Cons:** the plugin-isolation baseline never reaches 0 for the control cluster; the mislayering and the runtime-tools-as-plugins confusion persist.

## Trade-off Analysis

The decisive factor is **what the control plane is**, not how tools happen to reach it. The evidence is unusually clear: control already depends only on L1+L3 (one file excepted), and the agent runtime depends *on* control — so control is already, in practice, a low substrate sitting in the wrong package. Option B would inject a substrate into its own consumers, which is backwards; the ports would be the widest in the codebase precisely because they are wrapping something that should simply be a lower layer.

Option A costs more up front but is strictly better on correctness and *reduces* total debt (it also closes the pre-existing `control → chat/transport` layer violations, which Option B leaves untouched). The renumber and the chat-subscriber inversion are the real risks; both are mechanical/well-scoped and covered by the action items.

The tools dichotomy (capability vs runtime-actuator) is the connective insight: once control is low and the actuators are recognized as first-party, J and K stop being "port or not" questions and become "move to the right layer" — which is the same kind of mechanical, identity-preserving relocation already proven in Phase 2 PROMOTEs (`atomic_io`, `workspace_cache`, permission types).

## Consequences

**Easier**
- J cluster: actuator tools import `magi.control` downward — no ports, no `ToolExecutionContext` plumbing.
- Control plane becomes independently unit-testable (no agent runtime needed) and reusable by transport/CLI.
- The layers contract gets *simpler* (the `control → chat/transport` debt edges are deleted, not ported).
- Clear home for future control concerns (new interaction kinds, new execution modes).

**Harder / behavior-bearing**
- The `chat_state_persister` → chat-subscriber inversion changes *where* transcript state messages are produced; must be verified to produce identical messages (event-driven instead of direct-call).
- Interaction-answer delivery becomes transport→control; the broker's await/resolve path must preserve timeout semantics (`InteractionTimeoutError`).
- Tool registration: relocated first-party tools must be registered without the registry (L7) importing agent/control (L11/L4) upward — registration happens at the composition root / agent layer, not via `magi.tools.core_tools`.

**Resolved during implementation**
- `magi.skills` is a host execution engine rather than plugin implementation code; its agent execution dependency is injected, and third-party skill content remains runtime-guarded.
- The background task manager stays behind `BackgroundPort`; no control-plane move was needed.
- Layer numbering was updated: `events` remains L3 and `control` is L4.

## Target Layering

```
   L14  transport | ipc          ─┐ deliver answers down; render control events
   L13  api | chat | channels    ─┤ chat SUBSCRIBES to control events (no upward reach)
   ...
   L11→ agent                    ─┤ permission gating; reads plan/detach state
   ...
   L7 → tools | skills           ─┤ capability tools (SDK + ports). actuator tools RELOCATED out
        memory / llm / plugins   ─┤ (independent of control)
   L4   control plane  (NEW: magi.control)   ◀── session state · interaction registry · permission · control events
   L3   events                   ─┤ control emits here (downward)
   L2   config
   L1   core | scheduler | runtime_trace
```
import-linter `layers` contract: insert `control` between `plugins` and `events` (positional; no other reorder).

## Action Items

1. [x] Updated `layered-agent-architecture.md` with the L4 Control Plane, revised layer numbering, and the chat-owned control-event transcript projection.
2. [x] Move `magi.agent.control/*` → `magi.control/*`; all importers now use the canonical package and the temporary `magi.agent.control` shims are removed.
3. [x] Fold `magi.agent.run_control` (detach signal + `current_detach_signal`) into `magi.control.run_control`; all importers now use the canonical module and the temporary shim is removed.
4. [x] Replaced `chat_state_persister` with the chat-side `ControlTranscriptSubscriber`; parity tests cover plan/todo/ask transcript output.
5. [x] Moved interaction answers to direct API/channel ingress calls into `InteractionBroker.resolve`; timeout semantics remain covered by broker and permission tests.
6. [x] Resolved by ADR-0002: plan/todo live in `magi.control.tools`, the agent tool lives in `magi.agent.runtime_tools`, and ask/detach remain capability tools behind injected SDK ports.
7. [x] Resolved the skills boundary by treating `magi.skills` as a host execution engine, injecting its agent execution dependency, and excluding only host skill machinery—not third-party content—from plugin implementation scope.
8. [x] Added `control` to the layer/import rules, removed retired control edges, and kept `magi.control` forbidden to plugin implementation code.
9. [x] Removed the direct memory-provider dependency from `find_relevant_tools_tool`; discovery now uses the tool index and injected capabilities.
10. [x] The migration exit check reached a zero-edge plugin-isolation baseline and removed the control-to-chat/transport debt. Later unrelated layer checks are outside this ADR.
