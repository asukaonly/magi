# ADR-0001: Extract the Control Plane into a Low Layer

**Status:** Accepted
**Date:** 2026-05-31
**Deciders:** maintainers (architecture owners)
**Related:** [Layered Agent Architecture](./layered-agent-architecture.md), [Plugin Extension Architecture](./plugin-extension-architecture.md); Plugin-Boundary Framework A (Phase 2 capability ports, in progress)

> This is the first ADR in the repo. It establishes the `docs/control-plane-*` / `docs/<topic>-adr.md` convention: numbered, status-tracked decision records for cross-cutting architecture changes.

## Context

The Framework A plugin-boundary work (move plugin implementations behind `magi_plugin_sdk` so they never import host internals) surfaced a recurring shape: a set of built-in **tools** at L7 (`ask_user_question`, `plan_mode`, `todo_write`, `detach_to_background`, `agent_tool`) reach **up** into the agent runtime's *control* internals at L11 (`magi.agent.control.*`, `magi.agent.run_control`, `magi.agent.workers`, `magi.agent.execution`). The same is true of `magi.skills`.

We have been resolving most plugin→host inversions with **injected capability ports** (`ToolExecutionContext.capabilities`), and that is correct for genuine *capability* tools (file IO, bash, image generation, memory query — done in Phase 2 clusters A–H). But applying the port pattern to the **control** cluster would treat a symptom. A first-principles review (and a code probe) shows the control plane is **mislayered**, not merely "reached by tools."

Facts established by inspection of `backend/src/magi/agent/control/` (19 files):

- Its external dependencies are almost entirely **L1 infrastructure**: `core` (logger, DI container, `sqlite_connection_async`), `runtime_trace`, `runtime_defaults` — plus **L3 `events`** (it publishes control events). It does **not** depend on `agent` runtime internals, `llm`, `memory`, `plugins`, `tools`.
- The **only** file that reaches *upward* is `chat_state_persister.py`, which imports `chat` (`ChatMessageRecord`, `get_chat_store`) and `transport.chat_events`. These exact edges already sit in the **layers contract's debt baseline** (`agent.control.chat_state_persister -> magi.chat` / `-> magi.transport.chat_events`) — i.e. the mislayering is already recorded as debt.
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

**To revisit**
- Whether `magi.skills` execution belongs in the agent layer wholesale (K), decided in the K sub-plan once control is extracted.
- Whether the background task manager (`BackgroundPort`, Phase 2 D) should also fold into the control plane or stay a capability service (currently a port — leave unless a reason emerges).
- Doc L-numbering: `events` stays L3; control becomes L4; old L4–L14 shift +1. Update `layered-agent-architecture.md` accordingly.

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

1. [ ] Update `layered-agent-architecture.md`: add **L4 Control Plane** (`magi.control`), renumber old L4–L14 → L5–L15, document the "everything depends down on control" rule and the chat-subscribes-to-control-events contract.
2. [ ] Move `magi.agent.control/*` → `magi.control/*` (faithful, identity-preserving; host `magi.agent.control` left as thin re-export shims during migration, or all importers updated).
3. [ ] Fold `magi.agent.run_control` (detach signal + `current_detach_signal`) into `magi.control`.
4. [ ] Invert `chat_state_persister`: remove `chat`/`transport` imports from control; add a `chat`-side subscriber that renders plan/todo/ask state from control events. Verify produced transcript messages are identical (tests).
5. [ ] Move `InteractionBroker` answer-delivery to a downward `transport → control` call; preserve timeout/`InteractionTimeoutError` semantics.
6. [ ] Relocate runtime-actuator tools (`ask_user_question`, `plan_mode`, `todo_write`, `detach_to_background`) and `agent_tool` out of `magi.tools.builtin` into a first-party location (agent/control-adjacent); register them via the composition root so the L7 registry does not import upward. They then import `magi.control` / `magi.agent` directly.
7. [ ] Relocate the skill-execution core (`skills.subagent` orchestrator construction) into the agent layer (K); decide per-symbol port-vs-relocate for `skills → llm` / `chat.workspace`.
8. [ ] import-linter: insert `control` layer above `events`; remove the now-downward control edges from both contracts' baselines; confirm the relocated actuator tools are no longer in `plugin-isolation` source scope; keep `magi.control` forbidden for genuine capability plugins.
9. [ ] Clear the straggler `find_relevant_tools_tool -> magi.memory.provider` (reuse `MemoryQueryPort` or a small accessor) — unrelated to control, fold in opportunistically.
10. [ ] Exit check: `plugin-isolation` baseline reaches 0 and layers-debt loses the `control → chat/transport` edges, with `2 kept, 0 broken`.
