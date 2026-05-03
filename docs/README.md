# Magi Documentation

`docs/` is the active documentation home for Magi.

Only current project, product, architecture, and implementation guidance should live here. Historical review notes, scratch plans, and one-off execution prompts should be folded into the main docs or removed once the work is complete.

Local-only working drafts, design spikes, and execution plans belong under `docs/dev/`. That directory is intentionally gitignored and should not be treated as repository documentation.

## Recommended Reading Order

1. [Project Overview](./project-overview.md)
  Start here for the current product shape, repository layout, and high-level backend architecture.

2. [Product Configuration Guide](./product-configuration-guide.md)
  Use this for onboarding, settings, localization, memory options, tools, plugins, and timeline-facing product behavior.

3. [Layered Agent Architecture](./layered-agent-architecture.md)
  This is the backend boundary and ownership source of truth.

4. [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md)
  Read this when working on bootstrap, runtime orchestration, task agents, worker execution, scheduler registration, sensor sync execution, or service and transport boundaries.

5. [Conversation Rhythm Architecture](./conversation-rhythm-architecture.md)
  Read this when working on multi-bubble assistant turns, chat presentation planning, or rhythm-friendly prompt behavior.

6. [Persona Runtime Architecture](./persona-runtime-architecture.md)
  Read this when working on persona schema, persona prompt behavior, relationship-depth layers, dynamic persona state, or per-turn persona planning.

7. [Timeline Domain Architecture](./timeline-domain-architecture.md)
  Read this when working on timeline viewport assembly, clustering, state bands, insight extraction, or sensor-to-timeline data flow.

8. [Memory System Design](./memory-system-design.md)
  Maintainer-level implementation design for the lifecycle-based memory model.

9. [Unified Plugin Architecture](./plugin-extension-architecture.md)
  Current design for plugin discovery, contribution registration, and settings metadata.

10. [Plugin Development Guide](./plugin-development-guide.md)
  Practical guide for authoring built-in or external plugins.

11. [MCP Client Integration](./mcp-integration.md)
  Reference for connecting Magi to external Model Context Protocol servers — config format, transports, permission model, and troubleshooting.

12. [Unified Asset Resolver Architecture](./unified-asset-resolver-architecture.md)
  Read this when working on reusable `asset_refs`, source-specific asset
  resolution, chat attachments, or follow-up routing from memory recall to
  plugin-owned evidence.

12. [Backlog](./backlog.md)
  Current development and maintenance follow-ups that are intentionally not mixed into the design docs.

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

- Plugin maintainers
  Read [Unified Plugin Architecture](./plugin-extension-architecture.md), [Plugin Development Guide](./plugin-development-guide.md), and [Unified Asset Resolver Architecture](./unified-asset-resolver-architecture.md) when contributing reusable local assets.

- Release maintainers
  Start with [Project Overview](./project-overview.md) for the current desktop distribution and GitHub Release automation flow.

## Maintenance Rules

- Keep `docs/` aligned with the current codebase, not historical intent.
- When implementation changes alter runtime ownership or product behavior, update the relevant document in the same change when practical.
- Keep durable architecture in the main docs and keep open work in [Backlog](./backlog.md).
- Put temporary plans, design explorations, and review scratchpads in local-only `docs/dev/`, then fold durable conclusions back into the main docs.
