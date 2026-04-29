# Project Overview

## What Magi Is

Magi is a local-first AI agent framework that runs as a desktop application with a Rust gateway, a Python backend sidecar, and a Tauri shell.

At a high level, Magi combines:

- a backend runtime for bootstrap, orchestration, memory, tools, plugins, scheduling, and agent execution
- a Rust gateway (Axum) that owns HTTP/WebSocket transport, static reads, config I/O, and IPC dispatch to Python
- a React frontend for onboarding, settings, chat, inspection, and operational workflows
- a Tauri desktop shell that hosts the frontend, starts the Rust gateway, and manages the Python sidecar process

The project is optimized for local deployment and contributor control rather than cloud-first orchestration.

## Distribution And Releases

Desktop artifacts are distributed through GitHub Releases.

The repository automation source of truth is `.github/workflows/release.yml`.
Current release expectations are:

- maintainers publish desktop builds by pushing a version tag in the form `vX.Y.Z`
- the pushed tag must match the version stored in `frontend/package.json`, `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`, and `backend/pyproject.toml`
- release automation builds the Python sidecar first, then runs frontend type-check, a focused frontend smoke suite, frontend lint, a focused backend smoke suite, and finally the Tauri bundle build
- release jobs publish a GitHub Release and attach the generated desktop installers (`releaseDraft: false` in the workflow)
- desktop update packages are signed with the Tauri updater keypair, and release automation expects `TAURI_SIGNING_PRIVATE_KEY` plus the optional `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` secret in the `release` environment
- the desktop app checks the GitHub Release update feed through `latest.json`; prerelease visibility follows the release tag and updater configuration
- macOS signing and notarization should be supplied through repository secrets before shipping public releases to end users

## Core Goals

- local-first deployment and data ownership
- a layered backend with explicit ownership boundaries
- a pragmatic but extensible task-agent runtime
- unified plugin loading for built-ins and external packages
- a product surface that makes the runtime operable through onboarding and settings

## Non-Goals

- Magi is not a hosted multi-tenant platform
- Magi is not a fixed end-user assistant product with one hardcoded workflow
- Magi is not built around distributed services as the default deployment model
- Magi does not treat built-in tools as the only extension path

## Product Shape

Magi is a desktop-only application:

- Desktop mode
  Tauri shell plus React WebView plus Rust Axum gateway plus Python sidecar (IPC worker)

The Rust gateway serves all HTTP and WebSocket traffic on a single port. It handles static database reads, chat attachment content reads, config file I/O, and session/task mutations natively in Rust. Requests that require the Python runtime (message send, LLM calls, agent execution) are dispatched over IPC to the Python sidecar, using Unix Domain Sockets on Unix-like systems and loopback TCP on Windows. The Python process runs no public HTTP server; FastAPI is used only as an in-memory ASGI app for IPC request dispatch.

### Gateway-visible API contract

The frontend talks to the Rust gateway, not directly to the Python FastAPI app. The gateway-visible contract is therefore the union of Rust-native routes, Rust static mounts, and Python routes that are reached through the IPC proxy fallback.

The machine-readable route ownership manifest lives at `contracts/api/gateway_routes.json`. It records Rust-native route method/path ownership, static mounts, Python proxy prefixes, and native routes that still have Python parity implementations. `scripts/check-api-contract.py` validates the manifest against the Rust Axum router and the Python FastAPI route table, and is part of CI/release validation.

Python-proxied routes also have a dedicated schema export path: `scripts/export-python-openapi.py`. That script builds the in-memory FastAPI app and exports its OpenAPI document for IPC-dispatched Python routes only. Rust-native routes still belong in the gateway manifest and Rust contract tests.

When adding or moving a product API route, update the route implementation, the manifest, and the relevant contract tests in the same task. FastAPI OpenAPI is useful for Python-proxied routes only; it is not sufficient as the complete desktop API contract because Rust-native routes are registered outside Python.

The Rust gateway's direct SQLite write surface is tracked separately in `contracts/sqlite/gateway_writes.json`. `scripts/check-sqlite-ownership.py` scans production Rust gateway SQL and fails when a write or gateway-created index is not declared in that ownership contract.

## Backend Shape

The backend uses a thin composition root plus layer-owned runtime modules.

- `bootstrap/`
  The outer composition root. It assembles lifecycle modules, owns bootstrap context slices, and exports initialized runtime services.

- `core/`
  Application infrastructure such as logging, dependency injection, runtime paths, database initialization, and maintenance dependencies.

- `agent/`
  The task-agent runtime, orchestration, worker execution, and task-specific flows.

- `api/`
  Product-facing services and routers dispatched via IPC from the Rust gateway.

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

Plugin packages now contribute two capability families through one registration path:

- tools
- sensors

Discovery, enablement, and settings metadata are owned by the plugin runtime; execution stays in the owning runtime layers.

### Scheduler runtime

`SchedulerService` is the local persistent scheduler for business-facing runtime work such as:

- sensor sync
- agent task dispatch

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

- `L1` keeps canonical memory facts that may participate in recall, cognition, and reflection; execution-scoped outcomes stay out of `L1`
- runtime trace spans, tool calls, LLM call metrics, and turn-level execution summaries live in the dedicated runtime trace store

## Persistence Boundaries

- `~/.magi/runtime/message_queue.db`
  Runtime command-queue persistence only

- `~/.magi/data/chat/chat.db`
  Chat-domain source of truth for `chat_sessions`, `chat_turns`, `chat_messages`, and indexed `chat_attachments`

- `~/.magi/data/resources/chat/`
  Managed local chat attachments and derived artifacts grouped by type, session, and turn

- `~/.magi/data/memory/l1_events.db`
  Canonical L1 fact storage for lossy memory projection of `user_text` and `assistant_final` content only

- `~/.magi/data/memory/memory.db`
  Shared L0/L2/L3/L4 storage

- `~/.magi/runtime/runtime_trace.db`
  Runtime execution observability only: turn summaries, spans, LLM metrics, tool calls, intent-resolution details, live notifications, and append-only plugin ingress events produced by the desktop shell

- `~/.magi/data/app/scenario_prompts.db`
  Scenario prompt policy and prompt metadata

- `~/.magi/runtime/llm_usage.db`
  LLM usage metrics and usage-event persistence

- `~/.magi/cache/plugins/<plugin_id>/`
  Rebuildable plugin-owned state such as in-progress sensor aggregation caches

Chat ownership is now intentionally separated by domain:

- `chat.db`
  Owns transcript truth and turn presentation state

- `runtime_trace.db`
  Owns execution observability and best-effort live fan-out

- `l1_events.db`
  Owns canonical memory projection only

- the frontend still owns which session is currently selected and always sends an explicit `session_id`

## SQLite Ownership Matrix

The Rust gateway is allowed to write SQLite only for product or transport surfaces it owns natively. Python remains the owner for runtime-heavy behavior, memory cognition, plugin execution, and any operation that needs live runtime services.

When adding a new SQLite write path, update this matrix, `contracts/sqlite/gateway_writes.json`, and the gateway ownership test in the same change. A Rust native write is acceptable only when the table and operation are listed here or the write is delegated to Python over IPC.

| Database | Tables / state | Source of truth | Rust gateway access | Python access | Migration owner |
|---|---|---|---|---|---|
| `chat.db` | `chat_sessions`, `chat_turns`, `chat_messages`, `chat_attachments` metadata | Chat domain transcript and presentation state | Reads history/session/attachment views; writes lightweight session presentation mutations such as create, rename, workspace, labels, soft-delete, and history version bumps | Writes user/assistant turn and message records produced by runtime execution; owns chat-domain store invariants | Python chat store schema; Rust route tests must track response/write expectations |
| `data/resources/chat/` | attachment files and derived artifacts | Managed chat attachment content | Reads attachment content for desktop HTTP routes | Writes managed attachment files and parsed artifacts during upload/runtime preparation | Python chat attachment services |
| `runtime_trace.db` | trace turns, spans, tool calls, LLM calls, runtime notifications, plugin ingress events | Execution observability and best-effort live fan-out | Reads trace snapshots and readiness metrics; inserts `runtime_notifications` only for gateway-owned mutations that need frontend fan-out | Writes trace/notification/plugin ingress records produced by runtime services | Python runtime trace store schema; Rust notification bridge contract tests |
| `message_queue.db` | `runtime_commands` | Durable runtime command queue | No direct writes except through IPC-facing command enqueue flows if explicitly implemented | Owns queue schema, claiming, retry, ack, and recovery semantics | Python runtime command queue |
| `tasks.db` | `tasks` | User-facing task records | Reads task views; writes product task CRUD fields exposed by native task routes | May write runtime-linked task rows and orchestration linkage through task-domain services | Shared task-domain schema; native route mutations must stay field-scoped |
| `scheduler.db` | `schedules`, `target_state`, execution history | Unified scheduler configuration and execution bookkeeping | Reads schedules/executions; writes product schedule CRUD and target-state reset fields through `crates/magi-gateway/src/api/schedules/write.rs` | Owns scheduler execution, job registration, run history, and recovery | Python scheduler repository schema; Rust route tests cover native mutation fields |
| `llm_usage.db` | `llm_usage` | LLM usage metrics | Reads usage dashboards; may insert gateway-originated metric rows when no Python runtime call owns the event | Writes provider/runtime usage records for Python LLM execution | Python LLM usage store schema; Rust metrics tests cover read/write shape |
| `l1_events.db` | `fact_events`, L1 vector/index tables | Canonical lossy memory projection | Read-only for native memory list/stat endpoints; startup may create idempotent performance indexes | Owns all semantic writes, retention, archival, projection, and vector writes | Python memory L1 store schema; Rust may only add documented idempotent indexes |
| `memory.db` | L0/L2/L3/L4 tables, graph, assertions, summaries, procedures | Lifecycle memory state beyond L1 | Read-only for native memory inspection endpoints; startup may create idempotent performance indexes | Owns all memory writes, cognition, reflection, procedural extraction, conflict resolution, and vector writes | Python memory stores/schema; Rust may only add documented idempotent indexes |
| `scenario_prompts.db` | scenario prompt policy and metadata | Prompt policy registry | Read-only if surfaced through gateway in the future | Owns scenario prompt CRUD and prompt assembly inputs | Python context/scenario prompt store |
| `persona_registry.db` | personas and active persona state | Persona registry identity and active selection | No direct native writes currently; proxied to Python persona APIs | Owns persona CRUD, seed import, active persona selection, and runtime cache synchronization | Python persona repository |
| plugin cache DB/files | plugin-owned cursors and rebuildable state | Owning plugin or sensor contribution | No direct access | Plugin/sensor runtime owns reads and writes through contribution APIs | Owning plugin/sensor package |

Important rules:

- Rust native writes must stay narrow, product-facing, and table-scoped. If a write requires runtime services, LLM calls, memory cognition, plugin execution, or scheduler execution semantics, it belongs in Python behind IPC.
- Runtime notifications are not transcript truth. They are live fan-out of already committed state and may be replayed or compacted independently.
- Startup index creation from Rust is allowed only for idempotent performance indexes documented above. It must not create or migrate source-of-truth table schemas.
- Memory writes, vector writes, persona registry writes, plugin state writes, and runtime command claiming remain Python-owned unless this document is updated with a new explicit owner.

## Repository Structure

```text
magi/
├── backend/
│   ├── src/magi/
│   │   ├── agent/          # Task-agent runtime, orchestration, workers
│   │   ├── api/            # Product-facing routers and services
│   │   ├── awareness/      # Sensors and runtime event emission
│   │   ├── bootstrap/      # Composition root and lifecycle assembly
│   │   ├── channels/       # External messaging adapters (Telegram, etc.)
│   │   ├── chat/           # Chat domain persistence and attachments
│   │   ├── config/         # Runtime and provider config
│   │   ├── context/        # Prompt and recall shaping
│   │   ├── core/           # Infrastructure, DI, logging, runtime paths
│   │   ├── events/         # Message bus and event transport
│   │   ├── ipc/            # IPC server, dispatcher, protocol
│   │   ├── llm/            # Provider bridge and scenario model runtime
│   │   ├── memory/         # Lifecycle-based memory stores and retrieval
│   │   ├── personality/    # Personality state and subjective modeling
│   │   ├── plugins/        # Plugin discovery and registration
│   │   ├── runtime_trace/  # Execution observability persistence
│   │   ├── scheduler/      # Persistent scheduler and target dispatch
│   │   ├── skills/         # Shared skill loading and execution
│   │   ├── tasks/          # User-facing task tracking
│   │   ├── timeline/       # Timeline domain and sync workflows
│   │   ├── tools/          # Built-in and provider-backed tools
│   │   └── transport/      # IPC transport app wiring and middleware
│   └── tests/
├── crates/
│   └── magi-gateway/       # Rust gateway: Axum routes, IPC client, DB reader
├── frontend/              # React UI and Tauri desktop host
├── docs/                  # Durable architecture and product documentation
├── benchmark/             # LongMemEval and benchmark utilities
├── plugins/               # Built-in plugin packages
├── sdk/                   # Plugin SDK package
└── scripts/               # Dev/build helper scripts
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
- Plugin contributors should read [Unified Plugin Architecture](./plugin-extension-architecture.md) and [Plugin Development Guide](./plugin-development-guide.md).
- Memory contributors should read [Memory System Design](./memory-system-design.md).
