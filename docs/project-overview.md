# Project Overview

## What Magi Is

Magi is a local-first AI agent framework for building controllable agent systems that can run with a web frontend or a desktop shell.

At a high level, Magi combines:

- A Python backend runtime for agent execution, orchestration, memory, and tools
- A React frontend for configuration, chat, inspection, and operational workflows
- A desktop target based on Tauri with a Python sidecar backend

The project focuses on making agent infrastructure practical for local development instead of treating cloud-only orchestration as the default.

## Core Goals

- Local-first deployment and data control
- A lightweight but extensible agent runtime
- Clear boundaries between orchestration, execution, memory, and tools
- Support for multiple model providers and local or remote model backends
- A usable UI for interacting with and operating the runtime

## Non-Goals

- Magi is not trying to be a hosted multi-tenant cloud platform
- Magi is not trying to ship one fixed end-user agent product
- Magi is not built around distributed microservices as a baseline requirement
- Magi does not treat built-in tools as the only extension path

## Current Product Shape

Magi currently supports two main runtime shapes:

- Web mode
  React frontend + Python backend

- Desktop mode
  Tauri shell + React WebView + Python backend sidecar

This lets the same agent runtime power both browser-first and desktop-first workflows.

## Current Architecture Summary

Magi uses a layered backend architecture:

- Infrastructure
  Event transport, logging, config loading, persistence helpers

- Core runtime
  Sensor hub, router agent, task agents, action execution, lifecycle management, scheduler runtime

- Agent layer
  Task orchestration, worker management, execution loops, prompt assembly

- Memory layer
  Lifecycle-based memory ingestion, cognition extraction, reflection, procedural memory, and prompt retrieval

- Extension layer
  Tools, providers, memory backends, unified plugins, skills, LLM adapters

- API layer
  FastAPI routers, websocket bridges, read services

- UI layer
  React app, settings, chat, task and memory-related views

The extension layer now uses a unified plugin runtime for three contribution families:

- tools
- sensors
- actions

This means official built-ins and external packages follow the same discovery, enablement, and registry flow instead of separate hardcoded registration paths.

The memory system has also been rewritten around a lifecycle model instead of the older feature-stacked L1-L5 framing.

Current high-level memory shape:

- `L0`
  In-memory working context with checkpointing for crash recovery and short-lived execution state

- `L1`
  Normalized event memory as the long-term factual source of truth

- `L2`
  Structured cognition such as entities, relationships, and defensive ToM assertions derived from L1

- `L3`
  Reflection memory that compresses event streams into summaries and durable insights

- `L4`
  Procedural memory that stores reusable strategies, failure lessons, and execution heuristics

This model lets Magi separate ephemeral runtime state from durable user memory while still supporting retrieval, timeline insighting, and future behavior adaptation.

Current persistence boundary:

- `~/.magi/data/message_queue.db`
  Message bus queue persistence only (`message_queue`)

- `~/.magi/data/memories/l1_events.db`
  Canonical L1 storage split into semantic facts and runtime observations (`fact_events`, `runtime_observations`)

- `~/.magi/data/memories/memory.db`
  Shared L0/L2/L3/L4 storage (`l0_*`, `knowledge_graph`, `tom_*`, `summaries`, `procedural_skills`)

- `~/.magi/data/scenario_prompts.db`, `~/.magi/data/llm_usage.db`
  Runtime prompt policy and LLM usage metrics, separate from memory-layer databases

- Per-layer vector tables
  Vectors are stored in layer-owned tables (`l1_event_vectors`, `l3_summary_vectors`, `l4_skill_vectors`, `l5_capability_vectors`) instead of a shared `embeddings.db`, so model/dimension changes can be rebuilt per layer.

## Repository Structure

```text
magi/
├── backend/
│   ├── src/magi/
│   │   ├── agent/          # Task agents, worker orchestration, execution
│   │   ├── api/            # FastAPI app, routers, services
│   │   ├── awareness/      # Sensors and perception-related modules
│   │   ├── config/         # Runtime and provider config
│   │   ├── core/           # Runtime lifecycle and loop primitives
│   │   ├── events/         # Event backends and event types
│   │   ├── llm/            # Provider bridge and model adapters
│   │   ├── memory/         # Memory ingestion, retrieval, cognition, reflection, prompt context
│   │   ├── plugins/        # Plugin interfaces and loading
│   │   ├── processing/     # Processing modules
│   │   ├── runtime/        # Runtime bootstrap and wiring
│   │   ├── scheduler/      # Unified scheduled task runtime
│   │   ├── skills/         # Skill loading and execution
│   │   ├── tools/          # Builtin tools and provider tools
│   │   └── websocket/      # Websocket server support
│   └── tests/
├── frontend/
│   ├── src/
│   └── src-tauri/
├── docs/
└── scripts/
```

## Runtime Model

The agent runtime is built around a layered agent model:

- Master and routing responsibilities
  Runtime and routing components ingest external facts and send them to the correct task agent

- Task agents
  Own task-level interpretation, orchestration, and parent-task lifecycle

- Worker agents
  Leaf executors that perform one bounded task and return a structured result

The most important specialized task agents today are:

- `ChatTaskAgent`
  The main user-facing task agent that handles chat requests, direct tool use, generic orchestration, and final answer rendering

- `ExploreTaskAgent`
  A specialized task agent for large exploration-style requests such as codebase architecture analysis

The runtime also now includes a unified scheduler layer:

- `SchedulerService`
  A persistent local scheduler used for one-shot, interval, and cron-style business jobs

- `scheduler.db` execution observability
  In addition to `schedules`, `target_state`, and APScheduler job metadata, runtime execution history is persisted in `schedule_executions` for audit/debug replay.

- `SchedulerBootstrap`
  The runtime adapter that connects scheduled jobs to timeline sensor sync, task-agent dispatch, and outbound actions

This scheduler is intentionally separate from housekeeping loops such as `MaintenanceDaemon`.

The runtime also includes a unified memory subsystem:

- `UnifiedMemoryStore`
  Owns L0-L4 stores and the write path for normalized memory events

- `MemoryIntegrationModule`
  Bridges runtime events, timeline events, and task execution facts into the memory pipeline

- `HybridRetrievalService`
  Reads across event, cognition, reflection, and procedural memory when prompt assembly or tools need recall

## Current Explore Flow

Large explore requests are not handled by one giant worker anymore.

The current flow is:
  
1. `ChatTaskAgent` recognizes a large explore-style request
2. It routes that request to `ExploreTaskAgent`
3. `ExploreTaskAgent` plans bounded leaf subtasks
4. Leaf `Explore` workers run in parallel
5. Their structured results are aggregated into a Markdown dossier
6. The dossier is returned to `ChatTaskAgent`
7. `ChatTaskAgent` renders the final user-facing answer

This keeps worker scope bounded while preserving a user-facing conversational entry point.

## Key Technical Principles

- Workers stay leaf-only
  They do not recursively create other workers

- Parent orchestration is explicit
  `TaskOrchestrator` owns the lifecycle of decomposed parent tasks

- Internal contracts are typed
  Recent refactors moved task-agent execution requests, orchestration payloads, worker results, and internal fact payloads away from ad hoc dictionaries toward explicit DTOs

- External transport stays pragmatic
  Event payloads and tool payloads may still serialize to dictionaries at process boundaries, but internal runtime logic now prefers typed contracts

## Tech Stack

### Backend

- Python 3.10+
- FastAPI
- Pydantic v2
- SQLite and related local persistence helpers
- Structlog
- OpenAI / Anthropic compatible model integrations

### Frontend

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Zustand
- React Router
- TanStack Query

### Desktop

- Tauri v2
- Python sidecar runtime

## Where To Go Next

- If you want to use or evaluate the project:
  Start from the root [README](/Users/asuka/code/magi/README.md), then read [Product Configuration Guide](/Users/asuka/code/magi/docs/product-configuration-guide.md) and [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md) when you need more detail.

- If you want to work on the runtime:
  Read [Task-Agent Runtime Architecture](/Users/asuka/code/magi/docs/task-agent-runtime-architecture.md) next.

- If you want to work on extensions or plugin-backed settings:
  Read [Unified Plugin Extension Architecture](/Users/asuka/code/magi/docs/plugin-extension-architecture.md) and [Plugin Development Guide](/Users/asuka/code/magi/docs/plugin-development-guide.md) next.
