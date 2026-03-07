# Magi Documentation

This folder is the active documentation home for Magi.

The older `openspec/` material was useful during the early design phase, but the project has now moved to implementation-led documentation in `doc/`.

## Recommended Reading Order

1. [Project Overview](/Users/asuka/code/magi/doc/project-overview.md)
   Start here if you are new to the project, evaluating Magi, or trying to understand the product and repository at a high level.

2. [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md)
   Read this if you are working on the backend agent runtime, task orchestration, worker execution, or internal event flow.

3. Existing topic documents
   - [Tauri Python Sidecar Migration Plan](/Users/asuka/code/magi/doc/tauri-python-sidecar-migration-plan.md)
   - [Backend Code Review Report](/Users/asuka/code/magi/doc/backend-code-review-report.md)

## Audience Guide

- Open source users
  Read [Project Overview](/Users/asuka/code/magi/doc/project-overview.md).

- New contributors
  Read both [Project Overview](/Users/asuka/code/magi/doc/project-overview.md) and [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md) as the primary implementation guide.

## Documentation Rules

- `doc/` is now the preferred place for architecture and contributor-facing docs.
- `openspec/` can still be kept for historical reference, but it is no longer the primary source of day-to-day implementation guidance.
- When runtime architecture changes materially, update the relevant document in `doc/` in the same change if practical.
