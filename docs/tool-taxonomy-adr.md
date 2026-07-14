# ADR-0002: Tool Taxonomy — Capability Tools vs Runtime-Control Tools

**Status:** Accepted
**Date:** 2026-06-02
**Deciders:** maintainers (architecture owners)
**Refines:** [ADR-0001 Control-Plane Extraction](./control-plane-extraction-adr.md) (supersedes its Action Items 6–7); builds on the completed Plugin-Boundary Framework A capability ports

## Context

Phase 4 of the control-plane extraction asked: where do the "actuator tools" (`ask_user_question`, `plan_mode`, `todo_write`, `detach_to_background`) live, given they need the control plane (`magi.control`, L4) but currently sit in `magi.tools.builtin` — the plugin-isolation source scope?

The original intent was **uniform tool registration**: every tool (first-party + third-party) is discovered through the plugin runtime; first-party built-ins are wrapped by a `core-tools` plugin. This uniformity is valuable. But forcing *every* tool through the plugin path created a dilemma:

- If built-in tools may import host internals (e.g. `magi.control`) that the plugin contract forbids, built-ins get a **silent privilege** the contract doesn't express — an architectural gap/leak (built-in ≠ external, dishonestly).
- If built-ins are held to the same contract (SDK only), then `plan_mode`/`todo_write` **cannot work** (they intrinsically need control).

This dilemma is the symptom of a **category error**: treating two fundamentally different things as one ("everything is a plugin tool").

## Decision

**Recognize two distinct tool species, unified only at the registry, with capabilities the host chooses to share exposed as SDK ports.**

### 1. Two tool species

| | **Capability tools** | **Runtime-control tools** |
|---|---|---|
| Examples | file, bash, image, memory, web, **ask-user**, **detach** | **plan-mode, todo** |
| Nature | do work in the world | drive the agent's own execution state |
| Contract | inputs + host-granted platform services (SDK ports) → result | manipulate host execution control |
| Substitutability | first-party ≡ third-party; **extensible** | host-owned; **closed, not third-party-extensible** |
| Registration source | plugin discovery (`core-tools` plugin + external plugins) | host runtime (composition root) |
| Import rights | `magi_plugin_sdk` only (never `magi.*` host) | may import `magi.control` directly (first-party) |

The "architectural gap" disappears once runtime-control tools are honestly **outside** the plugin contract — they are not plugins pretending to follow it with secret privileges; they are a small closed host-owned set. The plugin boundary stays honest: **capabilities = sandboxed + extensible; runtime control = host-owned + closed + privileged by design.**

### 2. Single registry, two registration sources

The `ToolRegistry` is **origin-agnostic** — it holds `Tool` instances; the LLM sees and calls all tools uniformly. Unification is preserved where it matters (discovery/invocation). Only the *registration source* differs: the plugin manager registers capability tools; the composition root registers the closed control-tool set. Two sources, one registry. Third parties cannot add to the control-tool set (correct).

### 3. Control-plane capability classification

Capabilities the host chooses to share with plugins are exposed as **SDK ports on `ToolExecutionContext`** (the Phase-2 pattern), NOT by letting plugins import `magi.control`:

| Capability | Class | Mechanism | Plugin-usable |
|---|---|---|---|
| ask-user / interaction | capability | SDK `InteractionPort` (host-mediated: timeouts, user may ignore) | **yes** |
| detach-to-background | capability (request semantics) | SDK port | **yes** |
| risk classification (`RiskLevel`/`command_risk`) | pure logic | already promoted to SDK | **yes** |
| plan-mode | runtime control | host control tool (`magi.control.tools`) | no |
| todo | runtime control | host control tool | no |
| permission gateway/rules (write) | host-internal | host-only; never exposed | no |
| permission (read) | — | NOT a port; the host pushes the relevant authorized scope onto `ToolExecutionContext.permissions` | n/a |

**Permission read is not exposed as a port:** what a plugin legitimately needs to know ("what am I allowed to do") is delivered by the host *onto the context* (`permissions` already exists), rather than the plugin reading the permission gateway. The gateway stays host-exclusive (read and write).

### 4. Enforcement (plugin-isolation contract)

- Forbid the plugin source scope (`tools.builtin`, `tools.code_agent`, `skills`, external) from importing **any** `magi.*` host package, including `magi.control` — uniform, not a special case for control.
- Capability tools (incl. `ask_user`, `detach`) stay in the plugin scope and use SDK ports only.
- Runtime-control tools live in `magi.control.tools` (outside the plugin source scope) and legally import the control plane.

## Options Considered

- **A — keep "everything is a plugin", privilege built-ins:** rejected; this IS the leak (built-in ≠ external, dishonestly).
- **B — hold all tools to the SDK-only contract:** rejected; `plan_mode`/`todo` cannot function.
- **C — two species, single registry, ports for shared capabilities (chosen):** preserves uniformity at the registry, eliminates the gap by honest categorization, and shares exactly the capabilities the host intends (ask/detach) via the established SDK-port mechanism.

## Consequences

**Easier**
- The plugin boundary is honest and uniform: plugins never import host internals; the only "privilege" (control tools) is explicit, closed, and outside the contract — not a hidden hole.
- Plugins *gain* ask-user and detach (via ports) — strictly more capable than "control forbidden entirely".
- `ask_user`/`detach` tools need NO relocation — they become ordinary capability tools using a port (Phase-2 pattern), staying in `tools.builtin`.
- Future tools have a clear decision rule: "does it do work (capability → plugin path + SDK) or drive agent execution state (control → host path)?"

**Harder / implementation follow-through**
- A second registration source (composition root for control tools) — small, justified complexity; the registry model must support host-driven registration (it already supports plugin registration).
- Per-capability judgment is required when new control-ish capabilities appear (classify as shareable-capability vs host-control). This ADR's table is the precedent.
- The skills boundary was resolved by treating `magi.skills` as host execution machinery, injecting the agent execution dependency, and keeping third-party skill content runtime-guarded.

## Action Items (supersede ADR-0001 AI 6–7)

1. [x] Added SDK interaction and detach ports on `ToolExecutionContext`, with host adapters in the capability builder.
2. [x] Migrated `ask_user_question_tool` and `detach_to_background_tool` to injected ports while keeping them as capability tools.
3. [x] Added `magi.control.tools` for plan/todo and `magi.agent.runtime_tools` for agent spawning, with host-side registration.
4. [x] Added `magi.control` to plugin-isolation forbidden modules.
5. [x] Retired the control edges and reduced the plugin-isolation baseline to zero; the rollout exit check passed.
