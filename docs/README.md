# Magi Documentation

`docs/` is the active documentation home for Magi.

Only current project, product, architecture, and implementation guidance should live here. Historical review notes, scratch plans, and one-off execution prompts should be folded into the main docs or removed once the work is complete.

Local-only working drafts, design spikes, and execution plans belong under `docs/dev/`. That directory is intentionally gitignored and should not be treated as repository documentation.

## Core Source Of Truth

These documents are the first stop before changing product behavior, runtime
ownership, or module boundaries.

1. [Project Overview](./project-overview.md)
  Start here for the current product shape, repository layout, and high-level backend architecture.

2. [Product Configuration Guide](./product-configuration-guide.md)
  Use this for onboarding, settings, localization, memory options, tools, plugins, and timeline-facing product behavior.

3. [Layered Agent Architecture](./layered-agent-architecture.md)
  This is the backend boundary and ownership source of truth.

4. [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
  Read this when working on bootstrap, runtime orchestration, task agents, worker execution, scheduler registration, sensor sync execution, or service and transport boundaries.

5. [Timeline Domain Architecture](./timeline-domain-architecture.md)
  Read this when working on timeline viewport assembly, clustering, state bands, insight extraction, or sensor-to-timeline data flow.

6. [Memory System Design](./memory-system-design.md)
  Maintainer-level implementation design for the lifecycle-based memory model.

7. [Unified Plugin Architecture](./plugin-extension-architecture.md)
  Current design for plugin discovery, contribution registration, marketplace trust,
  install consent, dependency integrity, and settings metadata.

8. [Plugin Development Guide](./plugin-development-guide.md)
  Practical guide for authoring built-in or external plugins.

9. [Backlog](./backlog.md)
  Current development and maintenance follow-ups that are intentionally not mixed into design docs.

## Scoped Architecture References

Use these when a change touches the named subsystem. They are durable root docs,
but they are narrower than the core source-of-truth set.

- [Conversation Rhythm Architecture](./conversation-rhythm-architecture.md)
  Read this when working on multi-bubble assistant turns, chat presentation planning, or rhythm-friendly prompt behavior.

- [Identity Architecture](./identity-architecture.md)
  Read this when working on canonical user identity, self references, or channel identity mapping.

- [Persona Runtime Architecture](./persona-runtime-architecture.md)
  Read this when working on persona schema, persona prompt behavior, relationship-depth layers, dynamic persona state, or per-turn persona planning.

- [MCP Client Integration](./mcp-integration.md)
  Reference for connecting Magi to external Model Context Protocol servers: config format, transports, permission model, and troubleshooting.

- [Persistence & Migrations](./persistence-and-migrations.md)
  Read this when working on SQLite schema, runtime DB layout, Alembic environments, or migration workflow.

- [API Types Codegen Design](./api-types-codegen-design.md)
  Read this when changing the OpenAPI-to-frontend type generation contract.

- [Plugin Suggestion Descriptor](./plugin-suggestion-descriptor.md)
  Reference for plugin suggestion metadata consumed by product surfaces.

## Architecture Records

These root docs are durable decision or migration records. They provide history
and rationale, but new temporary plans should still start in local-only
`docs/dev/` and only graduate to the root when they become lasting reference.

- [Agent Runtime Seam ADR](./agent-runtime-seam-adr.md)
- [Context Decider Routing Redesign ADR](./contextdecider-routing-redesign-adr.md)
- [Control Plane Extraction ADR](./control-plane-extraction-adr.md)
- [Domain Task Agents ADR](./domain-task-agents-adr.md)
- [Tool Taxonomy ADR](./tool-taxonomy-adr.md)

## Audience Guide

- Open source users
  Start with [Project Overview](./project-overview.md).

- New contributors
  Read [Project Overview](./project-overview.md), then [Layered Agent Architecture](./layered-agent-architecture.md), then [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Layered Agent Architecture](./layered-agent-architecture.md) for ownership rules and [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md) for the current bootstrap and runtime wiring, including pull-sync execution and queue recovery.

- Persona and prompt maintainers
  Read [Persona Runtime Architecture](./persona-runtime-architecture.md), then [Product Configuration Guide](./product-configuration-guide.md) for user-facing configuration behavior.

- Memory maintainers
  Read [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md), then [Memory System Design](./memory-system-design.md).

- Schema and storage maintainers
  Read [Persistence & Migrations](./persistence-and-migrations.md) before touching any SQLite DDL or migration file.

- Plugin maintainers
  Read [Unified Plugin Architecture](./plugin-extension-architecture.md) and [Plugin Development Guide](./plugin-development-guide.md).

- Release maintainers
  Start with [Project Overview](./project-overview.md) for the current desktop distribution and GitHub Release automation flow.

## Maintenance Rules

- Keep `docs/` aligned with the current codebase, not historical intent.
- When implementation changes alter runtime ownership or product behavior, update the relevant document in the same change when practical.
- Keep durable architecture in the main docs and keep open work in [Backlog](./backlog.md).
- Put temporary plans, design explorations, and review scratchpads in local-only `docs/dev/`, then fold durable conclusions back into the main docs.
