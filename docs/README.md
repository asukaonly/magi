# Magi Documentation

This folder is the active documentation home for Magi.

`docs/` is now the single documentation home for project, product, and implementation guidance.

## Recommended Reading Order

1. [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
   Start here if you are new to the project, evaluating Magi, or trying to understand the product and repository at a high level.

2. [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md)
   Read this if you are working on onboarding, settings, configuration UX, language behavior, memory options, or tool management.

3. [Layered Agent Architecture](/Users/asuka/code/magi/docs/layered-agent-architecture.md)
   Read this if you need the target layer model, boundary rules, or naming guidance for Magi's backend architecture.

4. [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md)
   Read this if you are working on the backend agent runtime, task orchestration, worker execution, or internal event flow.

5. [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md)
   Read this if you are working on plugin loading, extension registration, timeline sensor registration, or action/tool integration.

6. [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md)
   Read this if you want to build a new built-in or external plugin package.

## Memory Documentation

Memory architecture is split into project-level docs in `docs/` and implementation-level deep dives in `backend/docs/`.

- Project-level baseline (required first):
  - [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
  - [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md)
  - [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md)
- Memory implementation deep dives (backend maintainers):
  - [Memory System Design](/Users/asuka/code/magi/backend/docs/memory-system-design.md)
  - [Memory System Execution Plan](/Users/asuka/code/magi/backend/docs/memory-system-execution-plan.md)

## Audience Guide

- Open source users
  Read [Project Overview](/Users/asuka/code/magi/docs/project-overview.md).

- New contributors
  Read [Project Overview](/Users/asuka/code/magi/docs/project-overview.md), then [Layered Agent Architecture](/Users/asuka/code/magi/docs/layered-agent-architecture.md), then [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md), then [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Layered Agent Architecture](/Users/asuka/code/magi/docs/layered-agent-architecture.md) for target boundaries and [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md) for current implementation details.

- Extension and plugin maintainers
  Read [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md) first, then [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md).

- Product and settings contributors
  Use [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md) as the primary guide.

## Documentation Rules

- `docs/` is the preferred place for project architecture and contributor-facing docs.
- Module-level implementation deep dives can live near code (for example `backend/docs/`) but must stay aligned with `docs/`.
- When runtime architecture changes materially, update the relevant document in `docs/` in the same change if practical.
