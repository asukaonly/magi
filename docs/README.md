# Magi Documentation

This folder is the active documentation home for Magi.

`docs/` is now the single documentation home for project, product, and implementation guidance.

## Recommended Reading Order

1. [Project Overview](/Users/asuka/code/magi/docs/project-overview.md)
   Start here if you are new to the project, evaluating Magi, or trying to understand the product and repository at a high level.

2. [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md)
   Read this if you are working on onboarding, settings, configuration UX, language behavior, memory options, or tool management.

3. [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md)
   Read this if you are working on the backend agent runtime, task orchestration, worker execution, or internal event flow.

## Audience Guide

- Open source users
  Read [Project Overview](/Users/asuka/code/magi/docs/project-overview.md).

- New contributors
  Read [Project Overview](/Users/asuka/code/magi/docs/project-overview.md), then [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md), then [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md).

- Runtime and orchestration maintainers
  Use [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md) as the primary implementation guide.

- Product and settings contributors
  Use [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md) as the primary guide.

## Documentation Rules

- `docs/` is now the preferred place for architecture and contributor-facing docs.
- `docs/` is the only active documentation source in the repository.
- When runtime architecture changes materially, update the relevant document in `docs/` in the same change if practical.
