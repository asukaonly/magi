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
  Read this when working on bootstrap, runtime orchestration, task agents, worker execution, scheduler registration, or service and transport boundaries.

5. [Sensor Sync Execution Architecture](./sensor-sync-execution-architecture.md)
  Read this when changing pull-sync scheduling, durable sensor execution, queue recovery, or scheduler isolation from sensor work.

6. [Memory System Design](./memory-system-design.md)
  Maintainer-level implementation design for the lifecycle-based memory model.

7. [Unified Plugin Extension Architecture](./plugin-extension-architecture.md)
  Current design for plugin discovery, contribution registration, and settings metadata.

8. [Plugin Development Guide](./plugin-development-guide.md)
  Practical guide for authoring built-in or external plugins.

9. [Backlog](./backlog.md)
  Current development and maintenance follow-ups that are intentionally not mixed into the design docs.

## Audience Guide

- Open source users
  Start with [Project Overview](./project-overview.md).

- New contributors
  Read [Project Overview](./project-overview.md), then [Layered Agent Architecture](./layered-agent-architecture.md), then [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Layered Agent Architecture](./layered-agent-architecture.md) for ownership rules, [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md) for the current bootstrap and runtime wiring, and [Sensor Sync Execution Architecture](./sensor-sync-execution-architecture.md) for pull-sync isolation and queue recovery.

- Memory maintainers
  Read [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md), then [Memory System Design](./memory-system-design.md).

- Extension and plugin maintainers
  Read [Unified Plugin Extension Architecture](./plugin-extension-architecture.md) and [Plugin Development Guide](./plugin-development-guide.md).

## Maintenance Rules

- Keep `docs/` aligned with the current codebase, not historical intent.
- When implementation changes alter runtime ownership or product behavior, update the relevant document in the same change when practical.
- Keep durable architecture in the main docs and keep open work in [Backlog](./backlog.md).
- Put temporary plans, design explorations, and review scratchpads in local-only `docs/dev/`, then fold durable conclusions back into the main docs.
