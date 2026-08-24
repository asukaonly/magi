# Project Overview

## What Magi Is

Magi is a local-first AI agent framework that runs as a desktop application with a Rust gateway, a Python backend sidecar, and a Tauri shell.

At a high level, Magi combines:

- a backend runtime for bootstrap, agent execution, memory, tools, plugins, and scheduling
- a Rust gateway (Axum) that owns HTTP/WebSocket transport, static reads, config I/O, and IPC dispatch to Python
- a React frontend for onboarding, settings, chat, inspection, and operational workflows
- a Tauri desktop shell that hosts the frontend, starts the Rust gateway, and manages the Python sidecar process

The project is optimized for local deployment and contributor control rather than cloud-first orchestration.

## Distribution And Releases

Desktop artifacts are distributed through GitHub Releases.

The repository automation source of truth is `.github/workflows/release.yml`.
Current release expectations are:

- maintainers run `scripts/bump-release.sh` only from an up-to-date `main` branch; the script synchronizes version metadata, pushes `main`, and gates tag creation on a successful `ci.yml` run for the exact release commit
- `release.yml` independently verifies that exact-commit CI result before any platform build, so a manually pushed tag cannot bypass the validation gate
- the pushed tag must match the version stored in `frontend/package.json`, `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`, and `backend/pyproject.toml`
- the full frontend, backend, API-contract, Rust gateway, and desktop-shell validation suite belongs to `ci.yml`; release jobs consume that result instead of repeating the same checks on every platform
- each platform release job prepares its native dependencies and plugin runtime, then the Tauri build hook builds the frontend and Python sidecar exactly once before producing the desktop bundle
- release jobs publish a GitHub Release and attach the generated desktop installers (`releaseDraft: false` in the workflow)
- desktop update packages are signed with the Tauri updater keypair, and release automation expects `TAURI_SIGNING_PRIVATE_KEY` plus the optional `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` secret in the `release` environment
- the desktop app checks the GitHub Release update feed through `latest.json`; prerelease visibility follows the release tag and updater configuration, startup runs a delayed background check, and packaged builds reuse the app-level network proxy for updater requests when configured
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

The Rust gateway serves all HTTP and WebSocket traffic on a single port. It handles static database reads, identity-validated streaming chat attachment downloads, config file I/O, task CRUD, and lightweight chat-session creation/title/workspace updates natively in Rust. Governed message, session, and history deletion is forwarded to Python because it also owns memory, trace, file, delivery, and runtime cleanup. Chat attachment uploads are size-bounded and streamed into temporary staging by the gateway; IPC passes the staging reference, and Python streams the body into its in-memory API so it can own the final managed-file mutation, parsing, and message ownership without repeated whole-body copies. Other requests that require the Python runtime (message send, LLM calls, agent execution) use the same IPC channel, with Unix Domain Sockets on Unix-like systems and loopback TCP on Windows. The Python process runs no public HTTP server; FastAPI is used only as an in-memory ASGI app for IPC request dispatch.

The gateway-to-Python channel has its own random per-launch credential, separate
from the WebView session credential. The Python worker accepts no business
request until the gateway authenticates in the first IPC frame, allows only one
authenticated connection, and removes the launch credential from its process
environment before runtime and plugins start. This rule is identical for Unix
sockets and Windows loopback TCP; the credential remains memory-only and is
never exposed to the WebView, plugins, files, URLs, or logs.

The desktop host also protects Magi's local data before it opens any log or
starts the Python worker. Existing files under `~/.magi` are repaired on every
launch so other operating-system accounts cannot read or change them. Links,
foreign-owned entries, and files with aliases outside the tree stop startup
instead of causing Magi to change an external target. This boundary covers only
Magi-owned storage; it never changes permissions on user-selected workspaces or
source libraries.

Every desktop gateway process creates a strong random session credential and
returns it only to the Magi WebView. The credential stays in process memory: it
is not passed to Python or plugins, written to disk, logged, or placed in a URL.
The liveness endpoint and bundled persona avatars are the only public reads.
Every other native or proxied request requires the session credential, and
browser-originated requests are accepted only from the known Magi development
or packaged WebView origins.

DOM-managed image requests cannot attach the session header. Chat attachments,
timeline assets, and user-uploaded avatars therefore use short-lived,
memory-only resource tickets issued from typed resource identities. A ticket
is bound to one exact resource and may be reused briefly for image loading,
HEAD, or range reads; it never replaces the existing ownership, deletion, and
file-identity checks at the content endpoint. The frontend requests tickets
only when an image approaches the viewport and transparently renews an expired
ticket. Bundled avatars remain public because they contain no user data.

Future browser extensions or external collectors must use a separately paired,
revocable ingestion capability with a narrow route scope. They must never
receive or reuse the desktop WebView session credential. This keeps external
ingestion extensible without turning the complete desktop API into a local
public service.

On confirmed desktop quit, the Tauri shell hides the main window first and then stops the Python sidecar in the background before exiting. Windows helper processes used for sidecar startup and shutdown must be launched without visible console windows so quit feels like a native desktop close rather than a terminal-driven teardown.

External links are opened only after the desktop host validates their protocol. Web and email links are allowed on every platform; macOS and Windows additionally allow only their own system-settings protocol. Empty, malformed, credential-bearing, control-character, and all other protocol forms are rejected. Windows sends approved links directly to the native system handler and must never route them through a command interpreter.

### Gateway-visible API contract

The frontend talks to the Rust gateway, not directly to the Python FastAPI app. The gateway-visible contract is therefore the union of Rust-native routes, Rust static mounts, and Python routes that are reached through the IPC proxy fallback.

L0 inspection is Python-proxied even though its checkpoint tables are SQLite:
the current in-memory attention frame, lifecycle status and TTL expiry, source-forgetting
rules, and chat-owned context snapshot must be composed by one runtime owner.
The gateway must not serve L0 sessions, workbenches, or aggregate memory
statistics from a separate checkpoint-only view.

The machine-readable route ownership manifest lives at `contracts/api/gateway_routes.json`. It records Rust-native route method/path ownership, static mounts, Python proxy prefixes, native routes that still have Python parity implementations, and the public/private resource exceptions to the default authenticated access policy. `scripts/check-api-contract.py` validates the manifest against the Rust Axum router and the Python FastAPI route table, and is part of CI/release validation.

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
  The unified task-agent runtime, child-run execution, and task-specific flows.

- `api/`
  Product-facing services and routers dispatched via IPC from the Rust gateway.

The backend is described in more detail in [Layered Agent Architecture](./layered-agent-architecture.md) and [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).

## Current Runtime Highlights

### Task-agent runtime

The core runtime is centered on:

- `ChatTaskAgent`
  The chat-domain driver for typed ingress, prompt assembly, session-run state,
  and durable outcome projection

- `AgentRunHandler` and `FunctionCallingOrchestrator`
  The single model-facing execution path for ordinary chat, background, skill,
  and child runs

- `CapabilityResolver`, `CompletionGate`, and `AgentRunJournal`
  Runtime-owned capability, evidence, completion, and durable lifecycle policy

- `ChildRunCoordinator`
  Bounded child-run lifecycle, presets, budgets, cancellation, and results

Background-task completion is recoverable across startup ordering: every
terminal attempt leaves a pending completion snapshot before listeners run, and
the outreach layer drains those snapshots after channels are ready. A task that
finishes while the app is still starting therefore still converges on the same
chat result and proactive-delivery identity. If delivery fails while the app
keeps running, the periodic outreach pass retries a bounded set of pending
snapshots using the already saved wording; a handled attempt is not sent again.

### Conversation lifecycle

Deleting a message, clearing a conversation, deleting a session, or clearing
all memory is a governed operation across chat, memory, evidence, active work,
delivery state, traces, and private files. Related foreground and background
work is stopped first, and matching new background work or retries remain
blocked until memory and the visible chat surface finish cleanup. Deleting one
edited or replaced message covers its complete logical message chain without
blocking unrelated sibling work. The transcript becomes inaccessible before
slower file cleanup runs, and startup recovery finishes any interrupted cleanup
without bringing deleted content back.

Managed attachments are removed only when no surviving visible message owns
them. Code-task logs, diffs, temporary worktrees, and private branches follow
the same ownership rule and are removed with the conversation that owns them.
Edits already applied to the user's main project remain in place; deleting a
conversation never rolls those edits back.

### Unified plugin runtime

Plugin packages declare five contribution types through one package model:

- tools
- sensors
- channels
- skills
- hooks

Discovery, enablement, trust, install consent, and settings metadata are owned by
the plugin runtime. Tools, sensors, channels, and hooks register through the
shared plugin lifecycle. Skill loading remains separate and is not currently
driven by plugin registration.

### Scheduler runtime

`SchedulerService` is the local persistent scheduler for business-facing runtime work such as:

- sensor sync
- agent task dispatch
- layer-owned memory maintenance, consolidation, and summary generation
- runtime operational cleanup and background-task history retention

It now owns data-retention work that needs persistence, visibility, and
execution history. `MaintenanceDaemon` is reserved for lightweight
process-local checks such as health checks and log-size warnings.

### Lifecycle-based memory model

Magi uses a lifecycle-based memory model instead of the older feature-stacked framing:

- `L0`
  Bounded short-term attention for what still matters in the next
  conversational turn

- `L1`
  Normalized long-term event memory

- `L2`
  Structured cognition derived from retained events

- `L3`
  Reflection summaries and durable insights

- `L4`
  Procedural memory and reusable execution heuristics

`L0` is a disposable, rebuildable projection rather than memory truth. Chat
owns the transcript and rolling summaries; runtime owns live runs, tools,
interruptions, and recovery; `L1` and above own durable evidence and
understanding. Only an accepted complete chat turn may enter shared post-turn
understanding. That bounded analysis can produce an L0 attention delta together
with separately validated personality and durable-memory candidates, avoiding
duplicate model calls without merging their storage authority.

By default, L0 understanding runs after three newly accepted turns, after 30
seconds of conversational idle time, or no later than 90 seconds after the
first pending accepted turn. The update is asynchronous and affects subsequent
turns only; it never delays or changes the accepted answer that triggered it.
Its pending analysis queue is process-local: normal shutdown gives it a
five-second best-effort flush, while a crash or force termination may lose
pending analysis and uncheckpointed attention. Restart restores checkpointed
attention only; durable chat history, not L0, preserves the conversation.

This separates short-term attention and live runtime state from durable user
memory while keeping retrieval and future behavior adaptation connected to
governed source evidence.

Execution observability is now a separate concern from durable memory:

- `L1` keeps canonical memory facts that may participate in recall, cognition, and reflection; execution-scoped outcomes stay out of `L1`
- runtime trace spans, tool calls, LLM call metrics, and turn-level execution summaries live in the dedicated runtime trace store

### Persona runtime model

Magi treats persona as a structured runtime behavior model rather than a permanent style filter.

The Personality Layer owns persona definitions, relationship depth, dynamic persona state, and per-turn persona planning. For each user-facing model call, it should produce a `PersonaTurnPlan` that selects the current register, quiet-hour clamps, active signature triggers, relationship-layer modifiers, and dynamic-state modulations. The Context Layer then renders that plan alongside memory, profile, runtime, attachment, and tool context.

The durable design is documented in [Persona Runtime Architecture](./persona-runtime-architecture.md).

## Persistence Boundaries

- `~/.magi/runtime/message_queue.db`
  Runtime command-queue persistence only

- `~/.magi/runtime/sensor_state.db`
  Sensor sync cursors, source-item fingerprints, and sensor sync statistics. The awareness layer owns this database; high-volume fingerprint writes flow through a bounded batch queue so sensor catch-up runs apply backpressure instead of opening one SQLite write per emitted event.

- `~/.magi/data/chat/chat.db`
  Chat-domain source of truth for sessions, turns, messages, indexed
  attachments, message-owned asset and code-delegation references, private
  deletion-recovery registries, user-turn delivery attempts, assistant-memory
  projection intents, permanent cleared-session and cleared-message scopes, and
  interrupted global conversation clear

- `~/.magi/runtime/background_tasks.db`
  Background task rows, attempt events, and recoverable terminal-completion
  snapshots. Task history is operational state rather than recallable memory
  and remains visible in Tasks until manual dismissal or its configured
  retention policy removes it.

- `~/.magi/data/resources/chat/`
  Managed local chat attachments and derived artifacts grouped by type, session, and turn. Rust owns size-bounded upload staging and native downloads; Python owns the final managed upload write, semantic parsing, compact session attachment references, on-demand attachment reading tools, derived text artifacts, and lifecycle serialization with garbage collection.

- `~/.magi/data/memory/l1_events.db`
  Canonical L1 fact storage for lossy memory projection of `user_text` and `assistant_final` content only

- `~/.magi/data/memory/memory.db`
  Shared L0/L2/L3/L4 storage

  Sensor-derived L2 knowledge graph projection is owned by Python memory, but high-volume event subscribers must enter it through the awareness-owned knowledge graph write queue. The queue batches edge writes into memory facade calls and exposes queue depth, flush, retry, and failure counters for runtime diagnostics.

- `~/.magi/data/channels/channels.db`
  External channel conversation mappings, binding preferences, delivery
  receipts, notification cursors, and proactive-outreach outbox/delivery state

- `~/.magi/runtime/runtime_trace.db`
  Runtime execution journal and observability: run manifests, ordered lifecycle
  events, versioned plans, normalized spans, LLM/tool metrics, live
  notifications, and append-only plugin ingress events

- `~/.magi/runtime/llm_usage.db`
  LLM usage metrics and usage-event persistence, including provider-reported prompt-cache read/write token counts used by the statistics dashboard

- `~/.magi/cache/plugins/<plugin_id>/`
  Rebuildable plugin-owned state such as in-progress sensor aggregation caches

- `~/.magi/workspaces/<workspace_id>/`
  Private workspace-scoped buckets for heavy rebuildable project state such as code indexes, plugin caches, and task runtime checkpoints. These buckets are keyed by normalized workspace identity and are not chat, memory, or trace truth.

- `<workspace>/.magi/`
  Optional project-local overlay for team-shareable project instructions, rules, skills, safe project settings, and gitignored local runtime/cache/traces. It is created only by explicit workspace initialization or by a feature that needs generated workspace-local state.

  Code delegation keeps private logs, diffs, context bundles, temporary
  worktrees, and branches under the governed workspace/session identity. Chat
  owns their lifecycle through private references in `chat.db`; applied files
  in the main workspace are not part of that disposable artifact set.

Workspace storage is an overlay, not a second global database. Core path infrastructure owns workspace identity, path resolution, generated directory creation, local `.gitignore` guards, and state manifests. A random durable identity is written under the gitignored local overlay only when chat commits a workspace association or an explicit workspace-state feature needs it; read-only discovery does not modify the workspace. Copies and ordinary path switches receive new identities, so the product never merges projects by guessing that a missing old path means a move. Context may read project knowledge from the overlay; agent runtime, tools, and plugins may use scoped cache/runtime directories through the workspace path facade; memory projection remains the only route into durable memory databases.

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

High-volume Python write paths must have a single owning service or bounded writer queue. Event subscribers, sensors, schedulers, and trace projectors should not create unbounded per-event write tasks against SQLite. Low-frequency CRUD may keep using short-lived repository connections; bursty ingestion paths must apply backpressure, batch related writes, and expose lightweight queue statistics.

Sensor pull sync has one additional acceptance rule: the scheduler may report
an item as ingested and advance its cursor only after the memory-owned commit
boundary confirms the L1 result. The in-process event bus is used afterward for
rebuildable timeline, graph, and fingerprint projections; queue admission is
not a substitute for durable-memory confirmation.

| Database | Tables / state | Source of truth | Rust gateway access | Python access | Migration owner |
|---|---|---|---|---|---|
| `chat.db` | sessions, session-creation idempotency mappings, turns, messages, attachment metadata, asset/code-delegation ownership, private cleanup registries, delivery attempts, assistant-memory projection intents, clear intents, cleared-session scopes, cleared-message scopes | Chat transcript, server-owned session identity, presentation state, delivery convergence, and deletion barriers | Reads history/session/attachment views; atomically writes server-generated lightweight sessions and their client idempotency mappings; writes presentation fields such as title and workspace | Writes runtime turns and messages; owns stop, message/session/history deletion, permanent session and message tombstones, attachment/code-delegation cleanup, projection handoff, and recovery invariants. Governed deletion is forwarded to Python and is never a native Rust soft-delete | Python chat store schema; Rust route tests must track response/write expectations |
| `data/resources/chat/` | attachment files and derived artifacts | Managed chat attachment content | Streams bounded upload request bodies into temporary staging outside managed storage and streams downloads only from an exact active message owner after file-identity validation | Streams staged uploads into the in-memory API; owns final upload writes, derived artifacts, tool/channel imports, message ownership validation, safe internal reads, and serialized garbage collection | Python chat attachment services own every managed mutation and internal safe-read rules; Rust gateway owns request staging and native validated downloads |
| `runtime_trace.db` | run manifests, ordered run events, versioned plans, trace turns, spans, tool calls, LLM calls, runtime notifications, plugin ingress events | Durable agent-run facts, execution observability, and best-effort live fan-out | Reads trace snapshots and readiness metrics; inserts `runtime_notifications` only for gateway-owned mutations that need frontend fan-out | Writes run journals, trace projections, notifications, and plugin ingress records produced by runtime services | Python runtime trace store schema; Rust notification bridge contract tests |
| `message_queue.db` | `runtime_commands`, user-message clear generation, cleared session/turn scopes | Durable runtime command queue and pre-admission privacy boundary | No direct writes except through IPC-facing command enqueue flows if explicitly implemented | Owns queue schema, attempt identity, claiming, retry, ack, recovery, generation advance, and scope blocking | Python runtime command queue |
| `background_tasks.db` | background task rows, attempt events, effect ledger, execution budgets, terminal-completion intents | Background execution state, effect replay governance, and recoverable completion handoff | No direct native writes currently | Owns task transitions, cancellation, budgets, effect attempts, startup recovery, terminal snapshot handoff, and retention | Python background-task store/schema |
| `channels.db` | session mappings, binding settings, receipts, notification cursors, proactive-outreach outbox and delivery log | External conversation routing and proactive-delivery state | No direct native writes currently | Owns channel mapping/preferences, delivery receipts, clear-time conversation cleanup, proactive-outreach claiming, and delivery convergence | Python channels/outreach schema |
| `tasks.db` | `tasks` | User-facing task records | Reads task views; writes product task CRUD fields through `crates/magi-gateway/src/api/tasks/write.rs` | May write runtime-linked task rows through task-domain services | Shared task-domain schema; native route mutations must stay field-scoped |
| `scheduler.db` | `schedules`, `target_state`, execution history, durable sensor-sync attempts | Unified scheduler configuration and execution bookkeeping | Reads schedules/executions; writes product schedule CRUD, target-state reset fields, and cancellation markers through `crates/magi-gateway/src/api/schedules/write.rs` | Owns scheduler execution, job registration, run history, bounded sensor-sync retry, and immediate recovery of interrupted sensor jobs | Python scheduler repository schema; Rust route tests cover native mutation fields |
| `sensor_state.db` | `sensor_cursors`, `sensor_fingerprints`, `sensor_stats` | Sensor sync bookkeeping and source-item dedupe state | No direct native writes currently; product commands request state flushes through IPC/runtime command queue | Owns cursor/stat updates and fingerprint dedupe writes; high-volume fingerprint writes must use the awareness-owned bounded batch writer | Python sensor_state schema |
| `llm_usage.db` | `llm_usage`, `llm_usage_rollups` | LLM usage metrics | Reads usage dashboards, including cache read/write utilization | Writes provider/runtime usage records for Python LLM execution and preserves cache token counts in rollups | Python LLM usage store schema; Rust metrics tests cover read/write shape |
| `l1_events.db` | `fact_events`, L1 vector/index tables | Canonical lossy memory projection | Read-only for native memory list/stat endpoints; startup may create idempotent performance indexes | Owns all semantic writes, retention, archival, projection, and vector writes | Python memory L1 store schema; Rust may only add documented idempotent indexes |
| `memory.db` | L0/L2/L3/L4 tables, graph, assertions, summaries, procedures | Lifecycle memory state beyond L1 | Reads selected L2-L4 inspection endpoints and may create idempotent performance indexes at startup; L0 inspection, aggregate statistics, and all product mutations are forwarded to Python | Owns the live L0 attention projection, cognition, reflection, procedural extraction, conflict resolution, vector writes, user feedback, corrections, and deletion governance | Python memory stores/schema; Rust may only add documented idempotent indexes |
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
│   │   ├── agent/          # Unified agent runtime and child runs
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
│   │   ├── runtime_trace/  # Run journal and execution observability
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

## Unified Agent Flow

Ordinary user messages do not pass through a chat/code/explore classifier. The
chat driver deterministically admits the typed message, resolves a bounded
initial capability surface, and builds one `AgentRunRequest`. The main model can
answer directly, call tools, maintain a versioned plan, or launch one or more
bounded child runs through the `agent` tool. Code-owned completion policy checks
effects, evidence, plan state, and validation before the final answer is
committed.

This keeps simple turns cheap while allowing source-heavy exploration and broad
repository work to decompose only when the main model has concrete reason to do
so.

## Technical Principles

- child runs cannot recursively launch child agents
- parent/child ownership, presets, and budgets are explicit and typed
- internal runtime logic prefers typed contracts over anonymous dictionaries
- transport payloads remain pragmatic at process boundaries
- bootstrap assembly stays thin; business logic stays with the owning layer

## Where To Go Next

- Runtime contributors should read [Task-Agent Runtime Architecture](./task-agent-runtime-architecture.md).
- Product and settings contributors should read [Product Configuration Guide](./product-configuration-guide.md).
- Plugin contributors should read [Unified Plugin Architecture](./plugin-extension-architecture.md) and [Plugin Development Guide](./plugin-development-guide.md).
- Memory contributors should read [Memory System Design](./memory-system-design.md).
