# Magi Documentation

This folder is the active documentation home for Magi.

`doc/` is now the single documentation home for project, product, and implementation guidance.

## Recommended Reading Order

1. [Project Overview](/Users/asuka/code/magi/doc/project-overview.md)
   Start here if you are new to the project, evaluating Magi, or trying to understand the product and repository at a high level.

2. [Product Configuration Guide](/Users/asuka/code/magi/doc/product-configuration-guide.md)
   Read this if you are working on onboarding, settings, configuration UX, language behavior, memory options, or tool management.

3. [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md)
   Read this if you are working on the backend agent runtime, task orchestration, worker execution, or internal event flow.

4. Existing topic documents
   - [Tauri Python Sidecar Migration Plan](/Users/asuka/code/magi/doc/tauri-python-sidecar-migration-plan.md)
   - [Backend Code Review Report](/Users/asuka/code/magi/doc/backend-code-review-report.md)

## Audience Guide

- Open source users
  Read [Project Overview](/Users/asuka/code/magi/doc/project-overview.md).

- New contributors
  Read [Project Overview](/Users/asuka/code/magi/doc/project-overview.md), then [Product Configuration Guide](/Users/asuka/code/magi/doc/product-configuration-guide.md), then [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Task-Agent Runtime Architecture](/Users/asuka/code/magi/doc/task-agent-runtime-architecture.md) as the primary implementation guide.

- Product and settings contributors
  Use [Product Configuration Guide](/Users/asuka/code/magi/doc/product-configuration-guide.md) as the primary guide.

## Documentation Rules

- `doc/` is now the preferred place for architecture and contributor-facing docs.
- `doc/` is the only active documentation source in the repository.
- When runtime architecture changes materially, update the relevant document in `doc/` in the same change if practical.
