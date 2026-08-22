# ADR-0005: ContextDecider Routing Layer — Derive Execution Shape, Layer Tool Injection

**Status:** Accepted
**Date:** 2026-06-04
**Deciders:** maintainers (architecture owners)
**Relates to:** [ADR-0004 Engine/Driver/Trigger Seam](./agent-runtime-seam-adr.md), [ADR-0002 Tool Taxonomy](./tool-taxonomy-adr.md)
**Motivated by:** a real bug — a `memory_query` tool the router *correctly* selected was dropped before reaching the main LLM. Root-cause analysis showed the bug is a symptom of a structural flaw in how the chat driver makes its pre-turn decisions.

## Context

A user asked "what was I looking at in chrome the last 2 days". The router (`ContextDecider`) classified this correctly and selected `memory_query`, but the main LLM received an empty tool catalog and answered from persona alone. Same request, 21ms apart:

```
[ContextDecider] Decision made | Profile: chat | Graph: reply | Tools: ['memory_query'] | ...
[magi.llm.calls.chat]  → Tool Catalog: (no tools available)
```

The tool was discarded *inside the routing layer*, before the main LLM:

```
ContextDecider emits graph_shape="reply" + tools=['memory_query']   ← self-contradictory
 → coordinator.match_intent: effective_graph_shape = "reply"        coordinator.py:362
 → if effective_graph_shape == "reply": selected_tools = []         coordinator.py:365-370  ← tools cleared
 → execution_mode = DIRECT_LLM                                      coordinator.py:379
```

**Root cause (first principles).** `ContextDecider` mixes *semantic judgment* with *execution structure derived from that judgment* into a single LLM output. The same decision then has two sources of truth — one from the LLM, one from code — which must eventually disagree. The `reply` vs `tool_loop` axis is already expressed implicitly by the LLM through the `tools` list ("does this need tools?"), yet the LLM is asked to express it a *second* time as `graph_shape`. When the two disagree, the coordinator resolves the conflict by clearing `tools` — discarding the correct half.

This single root cause has three observable symptoms:

1. **Over-loaded responsibility.** One LLM call emits ~20 fields spanning four unrelated domains: semantic understanding, execution topology, resource policy, and persona routing. ~8 fields currently have no consumer (`capabilities`, `risky_tools`, `needs_workspace`, `needs_external`, `confidence`, `memory_layer`, `background_hint`, `effort`). `route_decision.py` already flags this in its own header: "a SUPERSET ... removing them would require re-architecting persona routing (out of Phase B scope)."
2. **Redundant fields.** `complexity` / `effort` / `thinking_depth` all encode one "how hard / how much effort" dimension; `graph_shape` ↔ `tools` are mutually implied; `needs_external` ↔ "a web tool was selected". `RouteDecision.__post_init__` validates each field's enum in isolation but performs **no cross-field consistency check** (route_decision.py:94-119) — the structural breeding ground for this bug.
3. **`graph_shape` is a derived quantity.** Its three values (spec.py:30-34, 1:1 to same-named nodes) lie on two orthogonal axes: axis A "need tools" (`reply`↔`tool_loop`, ≡ `len(tools)==0`) and axis B "need multi-agent orchestration" (`plan_fanout`). Compressing two booleans into one three-valued enum and asking the LLM to pick it directly is the concrete form of the root cause.

**What the ADRs already settled (and what they didn't).**

| Current design | ADR verdict | This ADR's stance |
|---|---|---|
| reply/tool_loop/plan_fanout as three executors | Deliberate (reuse existing executors + distinct snapshot/detach semantics); but **never asked whether reply is just a degenerate tools=[] tool_loop** | Keep the executors; only stop treating the choice as an LLM field |
| Single ContextDecider call emitting all fields | Deliberate (split routing was rejected to save cost) | Keep the single call; only slim its output |
| LLM picks graph_shape, code derives node sequence | "the routing LLM is never asked 'should we validate?' — that's profile policy" | Move that line one notch further: code derives graph_shape too |
| All registered tools fed to the router for filtering | **No ADR ever justified this** (the one historical accident) | Change: layer by capability/control |
| graph_shape ↔ tools consistency | Not foreseen | Removed: deleting graph_shape as a field dissolves it |

## Decision

Apply ADR-0004's **Engine / Driver / Trigger** philosophy *inside* the chat driver's pre-turn decision layer. Three principles:

1. **The router LLM emits only semantic signals** (single source of truth).
2. **Execution shape is derived by code**, not emitted by the LLM.
3. **Tools are injected in layers** per the ADR-0002 taxonomy.

### 1. Minimal router output contract

**LLM emits** (irreplaceable semantic judgments): `profile`/intent; which **capability** tools; `needs_orchestration` (an initial hint, see §3); `thinking_depth`; `reasoning`; persona-routing signals (kept — see note).

**Derived by code, removed from LLM output:** `graph_shape`, `execution_mode` (§2); `difficulty` (already a function of `thinking_depth`); `complexity`, `effort` (deleted; difficulty uses `thinking_depth`); `situation_strength` (function of register + triggers).

**Deleted (dead fields, pending code re-confirmation of no consumers):** `capabilities`, `risky_tools`, `needs_workspace`, `needs_external`, `confidence`, `memory_layer`, `background_hint`.

`memory_route` stays as-is — it is already rule-derived by `apply_memory_guidance`, not emitted by the LLM.

> **Note — persona routing is NOT split out.** ADR-0004/D6 deliberately unified persona routing into the same call (avoids a duplicate LLM call and routing disagreement); splitting it would touch the persona subsystem and does not serve this goal. We keep it, but **isolate the persona fields into a nested sub-object** so the over-loading is structurally visible and a future split has a seam.

Target: RouteDecision drops from ~20 fields to ~8–10, each with a real consumer.

### 2. `derive_execution` (replaces `graph_shape` as an LLM field)

A pure, code-side function — the single source of truth for execution shape:

```
derive_execution(tools, needs_orchestration, attachments):
    if attachments.has_image:   return reply         # images can't run a tool loop
    if needs_orchestration:     return plan_fanout   # multi-agent orchestration
    if tools:                   return tool_loop      # tool iteration
    return reply                                      # neither tools nor orchestration → single shot
```

- `reply` / `tool_loop` / `plan_fanout` are demoted to **executor implementations** (their streaming / single-shot / snapshot optimizations are retained). "Which executor" moves from "LLM picks graph_shape" to "code reads tools + needs_orchestration".
- The four after-the-fact correction rules in `coordinator.py:355-373` (image→reply, tool_loop+empty→reply, plan_fanout+force_direct→…, reply→clear tools) **all disappear** — there is no longer an independent `graph_shape` input to reconcile.
- **The original bug vanishes by construction**: `tools=['memory_query']` + no orchestration → deterministically `tool_loop`; tools can never be dropped.

### 3. `needs_orchestration`: hybrid (a + b)

Orchestration strength is multi-dimensional but must **not** become an `OrchestrationStrength` enum the LLM picks (that repeats the very mistake of pushing derived structure into LLM output). Instead:

- **(a) Pre-turn initial judgment**: the router emits a `needs_orchestration` boolean (+ optional coarse hint: worker budget / leaf bias) as a *hint only*.
- **(b) In-loop self-escalation**: the main LLM gets a **control-class** tool (`escalate_to_orchestration` / `decompose`) so that, after a step or two, it can promote a `tool_loop` into orchestration once the task's real size is visible.

Strength continues to be expressed by the existing `default_leaf_type` (4 leaves: CodeExplore / Coding / Plan / general-purpose) + `allow_parallel`. **No new strength enum.**

### 4. Tool injection layering (per ADR-0002)

Reuse ADR-0002's established taxonomy, wiring it into the **injection strategy** (ADR-0002 currently uses it only for plugin boundaries and explicitly states "the registry is uniform to the LLM, no injection-strategy distinction" — exactly the gap to close):

- **runtime-control / system tools** (`enter_plan_mode`, `exit_plan_mode`, `todo_write`, `detach_to_background`, `ask_user_question`, the new `escalate_to_orchestration`) → **resident on the main LLM**, never filtered by the router. The LLM switches its own state inside the agentic loop.
- **capability / normal tools** (file / bash / web / memory / weather / …) → router pre-filters and injects.

`find-relevant-tools` was later narrowed from resident to `tool_need=discover`
routes. Keeping discovery on every local tool turn increased schema and tool
selection cost and allowed unrelated capability expansion after the router had
already selected a sufficient concrete tool.

Minimal mechanism: add a `scope` (`system` | `normal`) dimension (or reuse `category == control`); `build_tools_parameter` unconditionally merges system tools; `ContextDecider._get_available_tools` (context_decider.py:195-206) excludes them from the router prompt.

**Knock-on benefit:** (1) fixes a current reliability gap — `enter_plan_mode` / `detach_to_background` / `ask_user_question` today must be router-selected to be usable, so a miss leaves the main LLM unable to switch mode / background / ask; (2) the router prompt shrinks to capability tools only, weakening the very premise ("the tool universe must be in the prompt") behind ADR's earlier rejection of split routing.

## Options Considered

- **A — Patch the symptom**: in `coordinator`, when `graph_shape=reply` + tools non-empty, upgrade to `tool_loop` instead of clearing tools. Rejected — fixes this one bug but leaves the two-sources-of-truth flaw (the next inconsistent field pair reappears).
- **B — Derive execution shape + layer tools (chosen)**: remove `graph_shape` as an LLM field, derive it from semantic signals; slim the schema; layer tool injection. Dissolves the bug class, not just the bug.
- **C — Split routing into multiple LLM calls**: rejected here for the same reason ADR-0004 rejected it (doubles cost without latency/token savings while the tool universe is in the prompt). Note §4 weakens that premise, but a split is still out of scope.

## Consequences

**Easier**
- The bug class is gone: execution shape has one source of truth; a selected tool can never be silently dropped.
- The router prompt and schema shrink; every field has a consumer; routing decisions become auditable.
- System tools (plan-mode / detach / ask-user) are always available to the main LLM in-loop — a reliability fix.

**Harder / staged**
- `derive_execution` must cover every case the four correction rules handled today (including the `force_direct_external` path) — the existing rules must be enumerated as test cases before migration.
- Resident system tools may add per-turn tokens; partly offset by the lighter router prompt — measure.
- Deleting fields requires confirming no consumer remains (serialization / self-memory / observability paths).

## Scope & Phasing

In scope for this ADR (one connected unit, one PR):

- **P0** — `graph_shape` → `derive_execution`; delete the four correction rules; **fixes the original bug** (reply+tools can never drop a tool).
- **P1** — RouteDecision slimming: delete dead fields, fold `complexity`/`effort` into `thinking_depth`, isolate persona fields into a sub-object.
- **P2** — Tool layering: capability/control injection split, system tools resident.
- **P3** — Agentic upgrade: `needs_orchestration` in-loop `escalate_to_orchestration`.

## Out of Scope

- **P4 — driver convergence** (explore↔chat scaffold dedup; register `batch` as a standard driver) belongs to **ADR-0004's** Engine/Driver/Trigger line. The trigger seam and typed engine front door are built; only the deferred driver registry remains. Tracked there, not here.

## Validation

- **Bug regression**: the memory-query (and weather) case no longer drops tools; end-to-end the main LLM receives a non-empty tool catalog.
- **Invariant**: "LLM selected a tool but it was discarded" becomes impossible — assertable in tests.
- **Field audit**: RouteDecision field count drops from ~20 to ~8–10, each with a named consumer.
- **Reliability**: plan-mode / detach / ask-user are callable in the main loop without being router-selected.
