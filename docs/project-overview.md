# Project Overview

## What Magi Is

Magi is a local-first AI agent framework that runs as a Python backend with either a web frontend or a Tauri desktop shell.

At a high level, Magi combines:

- a backend runtime for bootstrap, orchestration, memory, tools, plugins, scheduling, and transport
- a React frontend for onboarding, settings, chat, inspection, and operational workflows
- a desktop shell that reuses the same backend runtime through a sidecar model

The project is optimized for local deployment and contributor control rather than cloud-first orchestration.

## Core Goals

- local-first deployment and data ownership
- a layered backend with explicit ownership boundaries
- a pragmatic but extensible task-agent runtime
- unified extension loading for built-ins and external packages
- a product surface that makes the runtime operable through onboarding and settings

## Non-Goals

- Magi is not a hosted multi-tenant platform
- Magi is not a fixed end-user assistant product with one hardcoded workflow
- Magi is not built around distributed services as the default deployment model
- Magi does not treat built-in tools as the only extension path

## Product Shape

Magi currently supports two runtime shapes:

- Web mode
  React frontend plus Python backend

- Desktop mode
  Tauri shell plus React WebView plus Python backend sidecar

The same backend runtime serves both targets.

## Backend Shape

The backend uses a thin composition root plus layer-owned runtime modules.

- `bootstrap/`
  The outer composition root. It assembles lifecycle modules, owns bootstrap context slices, and exports initialized runtime services.

- `core/`
  Application infrastructure such as logging, dependency injection, runtime paths, database initialization, and maintenance dependencies.

- `agent/`
  The task-agent runtime, orchestration, worker execution, and task-specific flows.

- `api/` and `websocket/`
  Product-facing services and transport handling.

The backend is described in more detail in [Layered Agent Architecture](./layered-agent-architecture.md) and [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).

## Current Runtime Highlights

### Task-agent runtime

The core runtime is centered on:

- `ChatTaskAgent`
  The main user-facing task agent

- `ExploreTaskAgent`
  A specialized task agent for large exploration-style requests

- `TaskOrchestrator`
  Shared parent-task orchestration for bounded worker plans

- `WorkerAgentManager`
  Leaf worker lifecycle and result publication

### Unified plugin runtime

Plugin packages now contribute three capability families through one registration path:

- tools
- sensors
- actions

Discovery, enablement, and settings metadata are owned by the plugin runtime; execution stays in the owning runtime layers.

### Scheduler runtime

`SchedulerService` is the local persistent scheduler for business-facing runtime work such as:

- timeline source sync
- agent task dispatch
- outbound action dispatch

It is intentionally distinct from housekeeping loops such as `MaintenanceDaemon`.

### Lifecycle-based memory model

Magi uses a lifecycle-based memory model instead of the older feature-stacked framing:

- `L0`
  Working context and checkpointed short-lived execution state

- `L1`
  Normalized long-term event memory

- `L2`
  Structured cognition derived from retained events

- `L3`
  Reflection summaries and durable insights

- `L4`
  Procedural memory and reusable execution heuristics

This separates short-lived runtime state from durable user memory while keeping retrieval and future behavior adaptation connected to the same event pipeline.

Execution observability is now a separate concern from durable memory:

- `L1` keeps canonical memory facts that may participate in recall, cognition, reflection, or procedural learning
- runtime trace spans, tool calls, LLM call metrics, and turn-level execution summaries live in the dedicated runtime trace store

## Persistence Boundaries

- `~/.magi/data/message_queue.db`
  Message-bus queue persistence only

- `~/.magi/data/memories/l1_events.db`
  Canonical L1 fact storage for durable memory events and `chat_sessions` metadata rows

- `~/.magi/data/memories/memory.db`
  Shared L0/L2/L3/L4 storage

- `~/.magi/data/runtime_trace.db`
  Runtime execution trace storage for turn summaries, spans, LLM metrics, tool calls, and intent-resolution details

- `~/.magi/data/scenario_prompts.db`
  Scenario prompt policy and prompt metadata

- `~/.magi/data/llm_usage.db`
  LLM usage metrics and usage-event persistence

Chat session ownership is intentionally split:

- `chat_sessions` rows store durable session metadata such as title, previews, timestamps, and counts
- L1 `fact_events` store the actual durable chat messages keyed by `session_id`
- the frontend owns which session is currently selected and always sends an explicit `session_id`

## Repository Structure

```text
magi/
├── backend/
│   ├── src/magi/
│   │   ├── agent/          # Task-agent runtime, orchestration, workers
│   │   ├── api/            # Product-facing routers and services
│   │   ├── awareness/      # Sensors, actions, action emission
│   │   ├── bootstrap/      # Composition root and lifecycle assembly
│   │   ├── config/         # Runtime and provider config
│   │   ├── context/        # Prompt and recall shaping
│   │   ├── core/           # Infrastructure, DI, logging, runtime paths
│   │   ├── events/         # Message bus and event transport
│   │   ├── llm/            # Provider bridge and scenario model runtime
│   │   ├── memory/         # Lifecycle-based memory stores and retrieval
│   │   ├── personality/    # Personality state and subjective modeling
│   │   ├── plugins/        # Plugin discovery and registration
│   │   ├── processing/     # Legacy processing modules under review
│   │   ├── scheduler/      # Persistent scheduler and target dispatch
│   │   ├── skills/         # Shared skill loading and execution
│   │   ├── timeline/       # Timeline domain and sync workflows
│   │   ├── tools/          # Built-in and provider-backed tools
│   │   └── websocket/      # Connection and websocket transport handling
│   └── tests/
├── frontend/
├── docs/
├── openspec/
├── plugins/
└── scripts/
```

## Explore Flow

Large explore requests currently flow like this:

1. `ChatTaskAgent` classifies a request as explore-style work.
2. It forwards the request to `ExploreTaskAgent`.
3. `ExploreTaskAgent` plans bounded subtasks.
4. Leaf workers execute those subtasks in parallel.
5. The results are aggregated into a Markdown dossier.
6. The dossier flows back to `ChatTaskAgent` for user-facing rendering.

This keeps workers leaf-only while preserving a conversational entry point.

## Technical Principles

- workers stay leaf-only
- parent orchestration is explicit and typed
- internal runtime logic prefers typed contracts over anonymous dictionaries
- transport payloads remain pragmatic at process boundaries
- bootstrap assembly stays thin; business logic stays with the owning layer

## Where To Go Next

- Runtime contributors should read [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).
- Product and settings contributors should read [Product Configuration Guide](./product-configuration-guide.md).
- Extension contributors should read [Unified Plugin Extension Architecture](./plugin-extension-architecture.md) and [Plugin Development Guide](./plugin-development-guide.md).
- Memory contributors should read [Memory System Design](./memory-system-design.md) and [Memory System Execution Plan](./memory-system-execution-plan.md).
