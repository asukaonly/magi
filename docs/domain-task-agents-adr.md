# ADR-0003: Domain Task-Agents Belong in Their Domain Layer

**Status:** Accepted
**Date:** 2026-06-02
**Deciders:** maintainers (architecture owners)
**Related:** [Layered Agent Architecture](./layered-agent-architecture.md); [ADR-0001 Control-Plane Extraction](./control-plane-extraction-adr.md) (same dependency-inversion pattern). Addresses the `agent → chat` / `agent → timeline` layers-debt cluster ("A bucket").

## Context

First-principles directionality: **the agent runtime is the core capability; chat (and timeline, Telegram, CLI, …) are surfaces that drive it.** The agent does not need chat to exist. So the intended layering is *agent-then-chat*: surfaces sit ABOVE the agent and depend down on it (`chat` L14 → `agent` L12). The current layer numbering already reflects this.

But the agent layer hosts **domain-specific task agents** — `agent/task_agents/chat/*` (the `ChatTaskAgent` + history/postprocess/reply-context/transcript-summarizer) and `agent/task_agents/timeline/*` — and these reach **up** into their domains (`agent.task_agents.chat.* → magi.chat`, `agent → magi.timeline.handler`). That is the foundation reaching up into a surface — the inversion that produces the bulk of the `→ chat` / `→ timeline` layers-debt (~18 + several edges).

Inspection confirms the conflation: `agent/task_agents/` contains a **generic framework** (`common/`, `default_task_agent.py`, the router, `workers/`, `runtime/`) plus **domain specializations** (`chat/`, `timeline/`, `explore/`). `ChatTaskAgent` is ~80% generic agent-runtime mechanics (29 intra-agent imports: `common`, `runtime.contracts`, `orchestration`) and ~20% chat-domain access (6 imports of `chat`). It encodes *how chat drives the agent* — a chat-domain policy built on the generic runtime.

## Decision

**A task-agent lives in the layer of the highest domain it depends on. The agent layer is a domain-agnostic runtime that dispatches task-agents through a registry; domain surfaces own their task-agent specialization and register it.**

1. **Relocate domain task-agents to their domains:**
   - `ChatTaskAgent` (+ its chat/* support) → the **chat** layer (L14). There it imports the generic agent runtime (`agent.common`, `agent.runtime`, `agent.orchestration` — all L14→L12 *downward*) and the chat store (intra-L14). Every dependency becomes downward or intra — zero layer violations, zero baseline.
   - `TimelineTaskAgent` → the **timeline** layer (L13), same way.
   - `explore`/`default` task-agents stay in `agent/` — they use only the agent runtime + lower layers, with no upward reach into a domain.
2. **Registry-based dispatch (the inversion):** the agent runtime exposes a **task-agent registry** ("register a factory for task-agent type `chat`"). Domains register their factories (e.g. `chat` registers `create_chat_agent_factory`) at startup / via the composition root. The agent router selects by type from the registry and **never imports a domain task-agent implementation**. This is the same hook/registration shape as `magi.hooks` and the existing `create_*_agent_factory` functions — now *pushed* by the domain rather than *pulled* by the agent.
3. **Result:** `agent → chat` and `agent → timeline` disappear (become `chat/timeline → agent`, downward, plus registry registrations). The agent core is genuinely domain-agnostic.

## Options Considered

### A — Keep task-agents in `agent`, inject domain data via ports/hooks
Define ports (history-provider, transcript-persister, reply-context, …); chat implements them; the in-`agent` ChatTaskAgent uses the ports.
- **Pros:** smaller move; ChatTaskAgent stays put.
- **Cons:** the agent layer still *hosts chat-domain policy* ("how to run a chat turn"); requires defining many ports for something inherently chat's; doesn't express "chat is a surface". Half-measure.

### B — Relocate domain task-agents to their domains + registry dispatch (chosen)
- **Pros:** matches the agent-then-chat principle exactly; agent becomes truly domain-agnostic; eliminates (not legalizes) the inversion; one clean rule generalizing to timeline and future surfaces; all moved deps are downward (no baseline).
- **Cons:** largest move (ChatTaskAgent is central, ~29 agent deps); requires inverting dispatch to a registry (the router must not hard-import domain task-agents).

### C — Lower the chat *store* to a substrate (earlier idea)
Extract chat's transcript store down so `agent → store` is downward.
- **Pros:** smaller; reuses the control-extraction pattern.
- **Cons:** only *legalizes* the agent's dependency on chat data; the agent still depends on chat — it doesn't honor "agent is the core, chat is a surface". Superseded by B.

## Trade-off Analysis

The decisive principle is directionality: if chat is a surface on top of the agent, the agent must not depend on chat — not even on a lowered chat store (Option C legalizes the wrong direction). Option B inverts the dependency at its source: the chat-specific runtime composition is chat's, so it belongs in chat, consuming the generic agent runtime downward. The cost is concentrated in one place (dispatch must become registry-based), which is a well-understood pattern already partially present (`create_*_agent_factory`, `magi.hooks`).

## Consequences

**Easier**
- The agent core is domain-agnostic and independently reasonable/testable; new surfaces (a future channel) add a task-agent in their own layer and register it — no agent changes.
- `agent → chat` (~18) and `agent → timeline` edges are retired (downward after the move); the layers baseline shrinks meaningfully.
- Clear rule for any future task-agent: it lives in its highest domain.

**Harder / to watch**
- Largest refactor in this line: `ChatTaskAgent` + chat/* support move into `chat`; the router/dispatch must be inverted to a registry with NO hard import of domain task-agents (the key risk — verify the router selects purely by type).
- Many `chat → agent` downward edges appear (legal, no baseline) — honest: the chat-task-agent genuinely consumes the agent runtime heavily.
- `read_service → agent.orchestration` and other cross-domain reads are separate, smaller questions (not in this ADR's scope).

## Action Items

1. [ ] Verify the agent router/dispatch selects task-agents by type via a factory/registry and does not hard-import `ChatTaskAgent`; if it does, that import is what inverts.
2. [ ] Add/confirm a task-agent **registry** in the agent runtime (register factory by type; router looks up by type).
3. [ ] Relocate `agent/task_agents/chat/*` + `chat_task_agent.py` → the `chat` layer (template). Fix imports (agent runtime → downward; chat store → intra). Register `create_chat_agent_factory` from chat (composition root / chat lifecycle).
4. [ ] Confirm `agent → chat` edges are gone and lint stays `2 kept, 0 broken`; remove the retired edges from the layers baseline.
5. [ ] Generalize to `TimelineTaskAgent` → `timeline`.
6. [ ] Leave `explore`/`default` in `agent` (no domain reach). Document the "task-agent lives in its highest domain" rule in `layered-agent-architecture.md`.
