# Project Overview

## What Magi Is

Magi is a local-first AI agent framework that runs as a desktop application with a Rust gateway, a Python backend sidecar, and a Tauri shell.

At a high level, Magi combines:

- a backend runtime for bootstrap, agent execution, memory, tools, plugins, and scheduling
- a Rust gateway (Axum) that owns HTTP transport, static reads, config I/O, and IPC dispatch to Python
- a React frontend for onboarding, settings, chat, inspection, and operational workflows
- a Tauri desktop shell that hosts the frontend and manages connections; local mode launches the independent service, which owns the gateway and Python worker

The project is optimized for local deployment and contributor control rather than cloud-first orchestration.

## Distribution And Releases

Desktop artifacts are distributed through GitHub Releases.

The repository automation source of truth is `.github/workflows/release.yml`.
Current release expectations are:

- maintainers run `scripts/bump-release.sh` only from an up-to-date `main` branch; the script synchronizes version metadata, pushes `main`, and gates tag creation on a successful `ci.yml` run for the exact release commit
- `release.yml` independently verifies that exact-commit CI result before any platform build, so a manually pushed tag cannot bypass the validation gate
- the pushed tag must match the version stored in `frontend/package.json`, `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`, and `backend/pyproject.toml`
- the full frontend, backend, API-contract, Rust gateway, and desktop-shell validation suite belongs to `ci.yml`; release jobs consume that result instead of repeating the same checks on every platform
- frontend contributors and CI share `npm run check:full`: application and build/test configuration type checks, lint, import boundaries, generated contracts, translation keys/interpolation, component tests, and the production build; `npm run check` runs the static checks only. These checks do not replace a packaged desktop smoke test.
- each platform release job prepares its native dependencies and plugin runtime, then the Tauri build hook builds the frontend and shared Rust/Python service bundle exactly once before producing the desktop bundle
- release jobs attach installers to a draft GitHub Release (`releaseDraft: true`); successful builds do not publish an unvalidated candidate or advance the public updater feed
- desktop update packages are signed with the Tauri updater keypair, and release automation expects `TAURI_SIGNING_PRIVATE_KEY` plus the optional `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` secret in the `release` environment
- if installation fails after the desktop disconnects its service, recovery goes through the app bootstrap to replace runtime credentials, API clients and event streams; remote services are never stopped by a desktop update
- the desktop app checks the GitHub Release update feed through `latest.json`; prerelease visibility follows the release tag and updater configuration, startup runs a delayed background check, and packaged builds reuse the app-level network proxy for updater requests when configured
- macOS signing and notarization should be supplied through repository secrets before shipping public releases to end users

### Dependency security

The root Cargo lockfile owns the desktop dependency graph. Tauri must be at
least 2.11.1 for the corrected local-origin check. Keep `@tauri-apps/api` on the
same major/minor release as the Rust `tauri` crate, updating the frontend
manifest and lockfile together when upgrading either side to a new minor release.
The Linux GTK3 graph still requires `glib 0.18`, so the workspace overrides
that crate with the reviewed
upstream `VariantStrIter` safety backport in `vendor/glib`. Its archive and file
checksums, two-line patch and removal criteria are recorded in
[`vendor/README.md`](../vendor/README.md). CI verifies those sources and runs
the upstream iterator tests with optimization; a version-only warning about
0.18.5 does not authorize ignoring an unpatched registry copy.

The frontend gate rejects moderate-or-higher production advisories and
high-or-higher advisories across the complete build dependency graph. The Rust
gate checks both vulnerabilities and `unsound` warnings. Its exact advisory,
package and version exceptions are rechecked against the dependency graph or
verified patch on every run, and require review before 2026-10-07. The existing
quick-xml exceptions cover notification-string escaping only; the rkyv exception
requires that the optional feature remain disabled on every workspace target.

RustSec is complemented by `scripts/check-rust-github-advisories.py`, which
downloads the public crates.io [OSV data dump](https://google.github.io/osv.dev/data/)
and matches GitHub advisories against the lockfile locally. It sends no package
inventory and fails on download, parsing or unsupported-version-range errors.
Install its pinned matcher dependency with
`python -m pip install -r scripts/security-audit-requirements.txt`.
The `--database` option accepts a downloaded snapshot for reproducible reviews;
CI always downloads the current public database. Version-only GLib findings are
accepted only after proving the local backport is still connected and intact.
The GitHub matcher checks the vendored GLib version for all other advisories
as well as checking registry releases.

Dependency updates require new desktop builds. Repository audit results do not
prove that already distributed installers or installed applications were updated.

### Candidate acceptance

Before publishing the draft, a maintainer records the release commit, artifact
checksum, OS version, architecture, executed cases and results in the draft's
validation section. Each supported target (macOS Apple Silicon, macOS Intel and
Windows x64) needs actual installation/launch evidence for its own artifact.
An unsigned local build proves local behavior only; it does not prove signing,
notarization, installer behavior, updates or another target's runtime.

| Area | Required candidate evidence |
| --- | --- |
| Startup and native runtime | Launch outside the source checkout with a fresh isolated data root; bundled gateway, worker and plugin Python start without the development environment; native file selection and private resources work. |
| Configuration | Missing settings lead to onboarding; rejected connections remain editable; changing connection parameters invalidates verification; confirmed settings survive a full quit and relaunch. |
| Agent operation | Send, stream, stop, switch sessions and recover from provider/worker failure without displaying a false running or completed state. |
| Data and extensions | Import preview/selection, failure and retry; retrieve, delete and export selected data; invalid plugin configuration does not appear enabled; runtime state survives restart. |
| Desktop interaction | Core dialogs support Tab/Enter/Escape and return focus; minimum supported window and scaling keep actions visible; language, close/quit behavior and suspend/resume remain coherent. |

Existing component/contract tests supply detailed branch coverage; the record
identifies which cases were also executed through the actual packaged WebView,
gateway and worker. Missing platform or critical-flow evidence keeps the release
in draft. After acceptance, the maintainer replaces the pending validation text
with results and explicitly publishes that same draft. Code or artifact changes
invalidate the affected results and require a new candidate validation.

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

### Independent service development entry

The repository also builds the Tauri-independent `magi-server` executable from
`server/`. It replaces the former gateway-only CLI and owns both the Axum
listener and a supervised Python worker through `crates/magi-server-runtime`.
It listens on loopback, acquires an OS instance lease, binds before the worker
is ready, gates business storage access during startup, and reconnects after
bounded worker restarts. `crates/magi-platform` supplies shared OS data protection.

The Python worker publishes management readiness after foundational storage and
configuration initialize, before optional plugin/Agent startup. Missing core
model configuration leaves management, raw memory storage and source collection
available; model-dependent capabilities wait on the same lifecycle owner and
resume after configuration is saved. `/api/server/info` and operator `status`
use protocol version 2 and `service_ready` for this management boundary. Query
`/api/ready` for actual Agent readiness and per-capability reasons. A client and
server must use the same protocol version; there is no legacy response alias.


For a source checkout with its Python environment installed:

```text
cargo build -p magi-server
magi-server init --config <new-json-file> --data-dir <absolute-private-directory> --development-root <absolute-repository>
magi-server run --config <json-file>
```

The build output is `target/debug/magi-server` (with `.exe` on Windows); use that
path when it is not installed on PATH. Configuration paths are absolute and the
runtime root is explicit. Python and plugin Python executable locations are part
of the configuration, not inferred from the launching terminal.

The private `--bootstrap-stdin` owner protocol accepts a session credential over
an inherited input pipe and stops when that owner closes the pipe. It is for a
desktop host or benchmark launcher, not a remote pairing mechanism.

On macOS and Unix hosts, the same OS account can run `magi-server status`,
`pair`, `clients`, or `revoke`, each with `--config <json-file>`; revocation also
requires `--client-id <id>`. These commands use the private `runtime/manage.sock`
channel to the running instance. `pair` outputs a single-use, five-minute
pairing token; transfer it through a trusted channel. HTTP pairing exchanges
it for one device credential, and session renewal exchanges that credential
for a fifteen-minute access token. All three use `x-magi-session-token` only
at their specific purpose boundary. Credentials and tokens never appear in URLs.
Each paired device has full access to the single owner's center and can be
individually revoked. Revocation invalidates its sessions and resource tickets.

The center keeps a durable identity and hashed device credentials in its own
`service/server.db`; business data remains in existing domain stores. Only
liveness and bundled avatars are public. HTTPS must terminate at a trusted
same-machine proxy before remote access; loopback does not bypass Magi auth.
`/api/events` provides SSE using an access-token header and optional
`Last-Event-ID`. Envelopes include center identity, stream epoch, sequence,
event id, type and domain payload. Replay is bounded to 256 events and 8 MiB;
frames are capped at 64 KiB and oversized hints request a fresh snapshot.
Slow subscribers are disconnected with `resync_required`, and device revocation
or session expiry terminates subscriptions. A process restart or runtime reset
changes the stream epoch; clients must reload authoritative state. Replay is
within the running gateway's retained window, not a durable event-delivery SLA.

The center polls persisted runtime notifications once for all clients using
bounded blocking reads. Successful product HTTP mutations also emit resource
invalidation hints. These hints do not provide an atomic outbox across domain
stores: client reconnection and periodic snapshot reconciliation are still
required to cover a commit followed by a process failure before notification.
The desktop consumes the stream with bounded parsing, resumable IDs, epoch/gap
reconciliation hints and reconnect backoff. Domain-wide snapshot reconciliation
and standalone distribution are tracked separately from transport delivery.

The independent service owns full-clear jobs: `DELETE /api/memory/clear` with
`X-Magi-Full-Clear-Transaction` accepts an idempotent operation and returns 202.
`GET /api/server/maintenance` reports its phase, result and durable data epoch.
The service drains native database users, stops normal Python execution, runs
restricted recovery, clears server logs and restarts normal runtime. Its job
continues when the requesting device disconnects. Startup resumes a pending
marker, and a completed operation ID never starts another clear. Each client tracks its own cache/log cleanup separately; a local cleanup failure
does not rerun center deletion or stop the center.

Memory restore uses the same service maintenance boundary. The native
`POST /api/memory/portability/restores/{candidate_id}/confirm` admits the inspected
candidate UUID once. The service closes content request admission, drains current
requests, rejects an active portability job, and publishes a durable marker before
stopping the normal worker. A restricted worker recovers any journal and executes
only its bound restore; a second restricted startup verifies the journal and receipt
before normal access resumes. Device disconnects do not cancel admitted work.
`GET /api/server/maintenance/{operation_id}` reads an exact receipt without replaying
an action. Retrying a historical action reports current epochs, never an obsolete
cache generation. Recovery failures remain blocked and can retry the same identity.

Maintenance metadata separates `data_epoch` (any memory replacement or full clear)
from `content_epoch` (full clear only). Memory restore invalidates memory reads and
resource tickets while preserving mounted drafts and center-scoped conversation
caches. A full clear retires those caches and device diagnostic logs. A device that
missed a clear followed by a restore still sees the changed content epoch.

The desktop native connection component stores versioned profile metadata in
its app configuration `connections/` directory. Device credentials are stored
in macOS Keychain or Windows Credential Manager, never in profile JSON. Native
pairing and renewal accept normalized HTTPS origins, reject redirects and
validate center/device identity and protocol version before returning an access
session. Linux remote credential persistence is not yet supported. First startup
offers local or remote connection; the sidebar opens saved connection management.
The title bar identifies the active center. Switching selects one profile and
reloads the interface; unsent content must be saved first. The native
host now launches the shared service executable for a selected local profile; a
remote profile renews its paired credential and launches no local business services.

Magi has a desktop client and a Tauri-independent service:

- Local desktop: Tauri + React, owning a `magi-server` child through a private stdin lifetime pipe.
- Remote desktop: Tauri + React, connected to an independently managed center over HTTPS.
- Service: Rust Axum gateway + supervised Python IPC worker, identical in both deployments.

Rust workspace packages have distinct compilation and process boundaries:

- `frontend/src-tauri` builds `magi-desktop`; `server` builds `magi-server`.
- `magi-service-contract` owns service configuration, the private launch handshake,
  and the server protocol version. It depends only on serialization libraries.
- `magi-platform` owns native filesystem protection, with no service workflows.
- `magi-server-runtime` composes the gateway and supervises Python; center clear
  and restore lifecycle state belongs here, including durable clear markers.
- `magi-gateway` owns HTTP/SSE, authentication, native SQLite access and Python IPC.

The desktop depends on the shared contract and platform crates, never the service
runtime, gateway or database libraries. The server entry uses the runtime and
shared crates; its direct gateway dependency is test-only. Libraries do not create
additional processes. `scripts/check-rust-boundaries.py` checks declared workspace
dependencies, including optional, target-specific, build and test dependencies,
in CI. Service packages must remain independent of Tauri.

Without an active connection profile, desktop bootstrap shows the onboarding
welcome and runtime-location choice before starting any local service. Selecting
this computer activates local startup; selecting an existing center reveals its
pairing flow. Once connected, persisted center onboarding status determines
whether to enter the application or continue model setup, without another welcome.

`prepare-service-bundle.mjs` stages the shared executable, Python worker, SDK and
plugin Python under `build/service/`. Desktop builds copy this complete bundle
to `frontend/src-tauri/server-dist/`; packaged startup has no source-tree fallback.
`MAGI_BUILD_TARGET` selects an explicit release target. Development builds compile
the same `magi-server` executable before opening Tauri. No development or installer
helper may kill processes by executable name or arbitrary listening port.

The Rust gateway serves HTTP on a single port. The independent server also exposes authenticated SSE at `/api/events`. It handles static database reads, identity-validated streaming chat attachment downloads, config file I/O, task CRUD, and lightweight chat-session creation/title/workspace updates natively in Rust. Governed message, session, and history deletion is forwarded to Python because it also owns memory, trace, file, delivery, and runtime cleanup. Chat attachment uploads are size-bounded and streamed into temporary staging by the gateway; IPC passes the staging reference, and Python streams the body into its in-memory API so it can own the final managed-file mutation, parsing, and message ownership without repeated whole-body copies. Other requests that require the Python runtime (message send, LLM calls, agent execution) use the same IPC channel, with Unix Domain Sockets on Unix-like systems and loopback TCP on Windows. The Python process runs no public HTTP server; FastAPI is used only as an in-memory ASGI app for IPC request dispatch.

The gateway-to-Python channel has its own random per-launch credential, separate
from the WebView session credential. The Python worker accepts no business
request until the gateway authenticates in the first IPC frame, allows only one
authenticated connection, and removes the launch credential from its process
environment before runtime and plugins start. This rule is identical for Unix
sockets and Windows loopback TCP; the credential remains memory-only and is
never exposed to the WebView, plugins, files, URLs, or logs.

The service protects its own data root before opening logs and stores. Existing
files in that root are repaired so other OS accounts cannot read or change them.
Links, foreign-owned entries and aliases outside the tree stop startup. Remote
desktop startup touches only its own app configuration and log directories; it
does not initialize, repair or collect from the local business data root.

For local mode the desktop generates a strong owner session credential, sends
it to its service over stdin and returns it to the Magi WebView. The credential stays in process memory: it
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

On confirmed desktop quit, the Tauri shell hides the main window first and then closes its owned service pipe and waits for service shutdown before exiting. Remote centers remain running. Windows helper processes used for sidecar startup and shutdown must be launched without visible console windows so quit feels like a native desktop close rather than a terminal-driven teardown.

External links are opened only after the desktop host validates their protocol. Web and email links are allowed on every platform; macOS and Windows additionally allow only their own system-settings protocol. Empty, malformed, credential-bearing, control-character, and all other protocol forms are rejected. Windows sends approved links directly to the native system handler and must never route them through a command interpreter.

### Client state ownership

Authenticated HTTP calls capture the active connection synchronously, before
credential renewal. A connection switch aborts old calls and rejects late
responses even for A → B → A. Requests reject foreign origins and redirects;
short-lived access sessions renew once for concurrent callers, with no automatic
mutation replay. Profile JSON and browser storage never hold device credentials.

Browser content caches use center identity and the durable content epoch. Chat
retry receipts, active session, read cursors, onboarding drafts, MRU entries,
continuation selections, notification dedupe and portability tracking remain
isolated. Reconnecting after a clear deletes obsolete epoch caches before the
app renders. Unscoped content caches are discarded rather than assigned to an
unknown center. Language, theme and device notification preferences are separate.

### Process data directory

For a local profile, the service, Python worker and plugin SDK resolve the same
process-wide `MAGI_HOME` directory. The desktop itself stores profiles and logs
in OS app directories. The default is `~/.magi`. An override must be
a dedicated absolute directory, set before launch; it cannot be empty, a filesystem
root, the OS home itself, or contain parent traversal. Changing it requires a full
exit and relaunch. It does not change the operating-system home or discover data
from another profile. Existing explicit configuration paths remain explicit.

Runtime sockets/readiness files, diagnostics, avatars, plugin installs, child
process tracking, managed workspace and default stores follow this root. The
frontend consumes host-provided paths instead of inventing a user-home layout.
Fresh example configuration leaves managed paths to the host defaults. Desktop
candidate verification uses a new empty root and a distinct application identifier
so both app data and WebView preferences are isolated from a regular installation.

The gateway compiles its provider template and preset embedding-model catalog
from the same versioned YAML sources bundled with Python. Native reads never
resolve these immutable catalogs through a build-machine repository path.

### Gateway-visible API contract

The frontend talks to the Rust gateway, not directly to the Python FastAPI app. The gateway-visible contract is therefore the union of Rust-native routes, Rust static mounts, and Python routes that are reached through the IPC proxy fallback.

L0 inspection is Python-proxied even though its checkpoint tables are SQLite:
the current in-memory attention frame, lifecycle status and TTL expiry, source-forgetting
rules, and chat-owned context snapshot must be composed by one runtime owner.
The gateway must not serve L0 sessions, workbenches, or aggregate memory
statistics from a separate checkpoint-only view.

L2 assertion and relationship lists, snapshot lists, and individual ToM snapshots
are also Python-proxied. Their product responses require governed visibility,
complete fact descriptions, canonical entity names, and snapshot revision and
generation checks from the memory read model. A Rust-native `SELECT *` handler would
bypass that contract even when the Python API and frontend independently pass
their tests. Gateway integration tests must prove these paths reach the worker
with their query parameters and preserve its response fields.

The machine-readable route ownership manifest lives at `contracts/api/gateway_routes.json`. It records Rust-native route method/path ownership, static mounts, Python proxy prefixes, native routes that still have Python parity implementations, and the public/private resource exceptions to the default authenticated access policy. `scripts/check-api-contract.py` validates the manifest against the Rust Axum router and the Python FastAPI route table, and is part of CI/release validation.

### Frontend state and type boundaries

Production TypeScript under `frontend/src/` uses strict compilation and type-aware
ESLint. Explicit `any`, unsafe assignments/member access/calls/arguments/returns,
floating or misused promises, and incomplete hook dependencies fail validation.
`@ts-ignore` and `@ts-nocheck` are prohibited; a necessary `@ts-expect-error`
must describe the constraint and remains checked by TypeScript.

The policy has explicit coverage boundaries:

- `src/**/__tests__/` and `src/test/` retain incremental typing cleanup and do not
  have the production type-aware lint override. They still compile and run tests.
- `src/api/generated/` is excluded from lint. Generated TypeScript participates
  in compilation, and generation/export drift checks protect the source contracts.
- Build/test configuration has a separate strict TypeScript project. It and
  tooling scripts do not inherit the production type-aware lint override.

External and persisted data enter as `unknown` and must be validated at the owning
API, event, or storage boundary before reaching editable models or stores. Type
assertions, including `as unknown as`, do not validate data. The current lint rules
do not automatically prohibit every double assertion, so this review requirement
is additional to passing lint. Removing explicit `any` does not prove that all
runtime boundaries have been validated.

`npm run check` runs static validation; `npm run check:full` adds component tests
and the production build. CI uses the same full command, and separately verifies
the Python contract export. These gates supplement desktop runtime verification.

The frontend's scoped accessibility lint covers shared primitives, configuration,
onboarding, plugin, memory-data and memory-layer expansion controls. Expansion
buttons expose translated names and their content state, support Enter/Space,
and respect disabled layers. The lint checks ARIA attributes, labels,
images and tab order with `eslint-plugin-jsx-a11y-x`, which supports the current
ESLint major. Native inputs with real HTML labels are tested through rendered
controls instead of duplicated ARIA labels just to satisfy static inference.
Keyboard regressions cover selection, disabled choices, Enter/Escape and focus
return from nested dialogs. These checks complement actual desktop WebView smoke
validation. Translation checking permits locale-specific plural forms while
requiring matching semantic keys and interpolation arguments.

Python-proxied routes also have a dedicated schema export path: `scripts/export-python-openapi.py`. That script builds the in-memory FastAPI app and exports its OpenAPI document for IPC-dispatched Python routes only. Rust-native routes still belong in the gateway manifest and Rust contract tests.

Failed, blocked and cancelled final assistant outcomes use the localized runtime
status card instead of an ordinary answer bubble. The projection uses durable
run state or the live trace summary, never error-text matching, and the same turn
does not retain an additional running placeholder or trigger reply suggestions.

Desktop event connection failures remain visible without replacing the current page;
the reconnect action opens authenticated SSE and refreshes session state. Each
subscription/request lifetime discards stale completions. Background history
reconciliation retries transport failures without inventing a terminal task outcome.
Settings capture their initial loaders per mount and restart them when an effect
lifetime restarts, including development StrictMode replay. Preview changes do not
restart initialization or replace an edited draft.
Timeline snapshots and pending actions belong to their date, scale, query and
language. Only the latest request in the current mounted scope may update data,
errors or pending state; an older snapshot is never labeled as a different period.
Memory list loaders own request admission at the state write boundary. Batch L2
refreshes use the same per-resource loaders as filtered reads, so neither path can
overwrite a newer query. Superseded reads are distinct from failed reads, and
changing or clearing a selected session invalidates its pending workbench read.
Workbench refresh continuations also belong to the selected session; returning
to a previous scope does not reactivate callbacks from its earlier visit.
Private image grants and retry callbacks are owned by the current resource and
mount lifetime. A superseded grant can neither replace a newer URL nor report an
access failure for a different image.
Local model download polling is serialized and starts after request acceptance;
list, download, and deletion failures remain visible in model settings.

### Generated frontend contracts

Configuration, onboarding, and tool configuration response contracts are exported by
`python scripts/export-frontend-contracts.py` to `contracts/api/frontend-config.json`,
with fixtures serialized from the production Pydantic models. The exporter checks
that the corresponding response models remain reachable through the public router.
After changing these models, run the exporter and `npm run contracts:generate` in
`frontend/`. CI checks both the Python export and generated frontend output for drift.
The frontend validates responses with precompiled validators before mapping generated
wire types to editable UI models. Invalid or incomplete successful responses raise
a contract error; they must not become empty/default configuration. The validators
do not evaluate code or compile schemas inside the desktop WebView. Python model
validators remain authoritative for cross-field business rules.

The same export/generation commands cover installed plugin packages, translated
field specifications, registry fingerprints, installation plans, install candidates/jobs, and settings
actions in `contracts/api/frontend-plugins.json`. These endpoints return direct
payloads; the client does not accept the removed success-envelope format. Dynamic
resource widgets validate their supported collection/permission shapes before
rendering. A completed install without its package result is a contract failure,
not proof of installation or runtime activation.

Chat display messages, session summaries, background tasks, and code-agent run
messages are exported from their production Python serializers to
`contracts/api/frontend-events.json`. Notification fixtures are built by the
production notification builders. Desktop projections validate these boundaries
before updating stores; invalid or mismatched chat data requests history
reconciliation instead of inserting partial messages. Task statuses are derived
from the runtime enum, including `suspended_waiting_user`, which remains active
and cancellable. Streaming consumes structured events and their final boundary.
Code-agent terminal results use the same generated execution contract for live
events and persisted-result reads. Result identities must match the delegation;
invalid summaries never enter the store. Persisted discard timestamps are checked
as artifact metadata, and malformed result/event reads remain hydration failures.

History import jobs and source previews, memory backup/restore/export operations,
and memory/chat deletion acknowledgements use `contracts/api/frontend-lifecycle.json`.
The exporter verifies their public Python response models and emits production-model
fixtures. Clients validate resource identity and confirmed success before removing
UI data. A completed backup/export requires its output artifact; incomplete clear
results remain errors. Import/candidate deletion requires HTTP 204. Discovery errors
keep new portability operations disabled and retry visibly until active/latest task
state is known. Chat deletion remains Python-owned through the gateway proxy.

Rust session-list and notification serialization samples live in
`contracts/api/frontend-native-sessions.json` and
`contracts/api/frontend-native-notification.json`. Gateway tests compare actual
serialized responses with these samples; frontend tests consume the same files.
Regenerate intentional changes with
`UPDATE_FRONTEND_NATIVE_CONTRACTS=1 cargo test -p magi-gateway native_` and review
the resulting diff. Missing or unreadable chat storage returns an unavailable
response, while a successful query with no sessions returns an empty list.
Python history reads also propagate unavailable state instead of empty history.

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

A Source is a data-collection contribution that supplies ongoing data to the
host. Source outputs can feed memory and timeline projections; collection
does not belong to the timeline UI. `source_id` identifies the contribution,
`source_type` describes its semantic data category, and `connection_id`
identifies the account, folder, or independently configured instance.

Plugin packages declare five contribution types through one package model:

- tools
- sources
- channels
- skills
- hooks

Discovery, enablement, trust, install consent, and settings metadata are owned by
the plugin runtime. Tools, sources, channels, and hooks register through the
shared plugin lifecycle. Skill loading remains separate and is not currently
driven by plugin registration.

### Scheduler runtime

`SchedulerService` is the local persistent scheduler for business-facing runtime work such as:

- source sync
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
owns the visible transcript and a separate canonical Model Context Log/Surface;
runtime owns live runs, tools, interruptions, and recovery; `L1` and above own
durable evidence and understanding. Named chat summaries are boundary caches,
not the normal prompt frontier. Only an accepted complete chat turn may enter
shared post-turn understanding. That bounded analysis can produce an L0
attention delta together with separately validated personality and durable-
memory candidates, avoiding duplicate model calls without merging their storage
authority.

By default, L0 understanding runs after three newly accepted turns, after 30
seconds of conversational idle time, or no later than 90 seconds after the
first pending accepted turn. The update is asynchronous and affects subsequent
turns only; it never delays or changes the accepted answer that triggered it.
Its pending analysis queue is process-local: normal shutdown gives it a
five-second best-effort flush, while a crash or force termination may lose
pending analysis and uncheckpointed attention. Restart restores checkpointed
attention only; the chat-owned Context Surface, not L0 or the visible transcript,
preserves model-visible conversation state.

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

- `~/.magi/runtime/source_state.db`
  Source sync cursors, source-item fingerprints, and source sync statistics. The awareness layer owns this database; high-volume fingerprint writes flow through a bounded batch queue so source catch-up runs apply backpressure instead of opening one SQLite write per emitted event.

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

  Source-derived L2 knowledge graph projection is owned by Python memory, but high-volume event subscribers must enter it through the awareness-owned knowledge graph write queue. The queue batches edge writes into memory facade calls and exposes queue depth, flush, retry, and failure counters for runtime diagnostics.

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
  Rebuildable plugin-owned state such as in-progress source aggregation caches

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

High-volume Python write paths must have a single owning service or bounded writer queue. Event subscribers, sources, schedulers, and trace projectors should not create unbounded per-event write tasks against SQLite. Low-frequency CRUD may keep using short-lived repository connections; bursty ingestion paths must apply backpressure, batch related writes, and expose lightweight queue statistics.

Source pull sync has one additional acceptance rule: the scheduler may report
an item as ingested and advance its cursor only after the memory-owned commit
boundary confirms the L1 result. The in-process event bus is used afterward for
rebuildable timeline, graph, and fingerprint projections; queue admission is
not a substitute for durable-memory confirmation.

| Database | Tables / state | Source of truth | Rust gateway access | Python access | Migration owner |
|---|---|---|---|---|---|
| `service/server.db` | server identity, device credential hashes and revocation | Center authorization | Sole reader, writer and schema owner in `auth/storage.rs` | No access | Rust `user_version`; newer schemas rejected |
| `chat.db` | sessions, session-creation idempotency mappings, turns, messages, attachment metadata, asset/code-delegation ownership, private cleanup registries, delivery attempts, assistant-memory projection intents, clear intents, cleared-session scopes, cleared-message scopes | Chat transcript, server-owned session identity, presentation state, delivery convergence, and deletion barriers | Reads history/session/attachment views; atomically writes server-generated lightweight sessions and their client idempotency mappings; writes presentation fields such as title and workspace | Writes runtime turns and messages; owns stop, message/session/history deletion, permanent session and message tombstones, attachment/code-delegation cleanup, projection handoff, and recovery invariants. Governed deletion is forwarded to Python and is never a native Rust soft-delete | Python chat store schema; Rust route tests must track response/write expectations |
| `data/resources/chat/` | attachment files and derived artifacts | Managed chat attachment content | Streams bounded upload request bodies into temporary staging outside managed storage and streams downloads only from an exact active message owner after file-identity validation | Streams staged uploads into the in-memory API; owns final upload writes, derived artifacts, tool/channel imports, message ownership validation, safe internal reads, and serialized garbage collection | Python chat attachment services own every managed mutation and internal safe-read rules; Rust gateway owns request staging and native validated downloads |
| `runtime_trace.db` | run manifests, ordered run events, versioned plans, trace turns, spans, tool calls, LLM calls, runtime notifications, plugin ingress events | Durable agent-run facts, execution observability, and best-effort live fan-out | Reads trace snapshots and readiness metrics; inserts `runtime_notifications` only for gateway-owned mutations that need frontend fan-out | Writes run journals, trace projections, notifications, and plugin ingress records produced by runtime services | Python runtime trace store schema; Rust notification bridge contract tests |
| `message_queue.db` | `runtime_commands`, user-message clear generation, cleared session/turn scopes | Durable runtime command queue and pre-admission privacy boundary | No direct writes except through IPC-facing command enqueue flows if explicitly implemented | Owns queue schema, attempt identity, claiming, retry, ack, recovery, generation advance, and scope blocking | Python runtime command queue |
| `background_tasks.db` | background task rows, attempt events, effect ledger, execution budgets, terminal-completion intents | Background execution state, effect replay governance, and recoverable completion handoff | No direct native writes currently | Owns task transitions, cancellation, budgets, effect attempts, startup recovery, terminal snapshot handoff, and retention | Python background-task store/schema |
| `channels.db` | session mappings, binding settings, receipts, notification cursors, proactive-outreach outbox and delivery log | External conversation routing and proactive-delivery state | No direct native writes currently | Owns channel mapping/preferences, delivery receipts, clear-time conversation cleanup, proactive-outreach claiming, and delivery convergence | Python channels/outreach schema |
| `scheduler.db` | `schedules`, `target_state`, execution history, durable source-sync attempts and creation receipts | Unified scheduler configuration and execution bookkeeping | Reads schedules/executions; all mutations proxy to Python | Owns conditional schedule CRUD, live job registration, run history, queued cancellation, bounded source-sync retry, and recovery of interrupted source jobs | Python scheduler migrations; gateway tests verify mutation forwarding |
| `source_state.db` | `source_cursors`, `source_fingerprints`, `source_stats` | Source sync bookkeeping and source-item dedupe state | No direct native writes currently; product commands request state flushes through IPC/runtime command queue | Owns cursor/stat updates and fingerprint dedupe writes; high-volume fingerprint writes must use the awareness-owned bounded batch writer | Python source_state schema |
| `llm_usage.db` | `llm_usage`, `llm_usage_rollups` | LLM usage metrics | Reads usage dashboards, including cache read/write utilization | Writes provider/runtime usage records for Python LLM execution and preserves cache token counts in rollups | Python LLM usage store schema; Rust metrics tests cover read/write shape |
| `l1_events.db` | `fact_events`, L1 vector/index tables | Canonical lossy memory projection | Read-only for native memory list/stat endpoints | Owns all semantic writes, retention, archival, projection, and vector writes | Python L1 Alembic migrations own all schema and indexes |
| `memory.db` | L0/L2/L3/L4 tables, graph, assertions, summaries, procedures | Lifecycle memory state beyond L1 | Reads selected L2-L4 inspection endpoints; L0 inspection, aggregate statistics, and all product mutations are forwarded to Python | Owns the live L0 attention projection, cognition, reflection, procedural extraction, conflict resolution, vector writes, user feedback, corrections, and deletion governance | Python shared-memory Alembic migrations own all schema and indexes |
| `persona_registry.db` | personas and active persona state | Persona registry identity and active selection | No direct native writes currently; proxied to Python persona APIs | Owns persona CRUD, seed import, active persona selection, and runtime cache synchronization | Python persona repository |
| plugin cache DB/files | plugin-owned cursors and rebuildable state | Owning plugin or source contribution | No direct access | Plugin/source runtime owns reads and writes through contribution APIs | Owning plugin/source package |

Important rules:

- Rust native writes must stay narrow, product-facing, and table-scoped. If a write requires runtime services, LLM calls, memory cognition, plugin execution, or scheduler execution semantics, it belongs in Python behind IPC.
- Desktop event subscriptions are owned by a connection generation: disconnect releases pending registrations when they resolve, partial connection failures clean up, and late callbacks cannot mutate a newer connection. Incoming SSE envelopes and nested notification payloads are validated before dispatch.
- Runtime notifications are not transcript truth. They are live fan-out of already committed state and may be replayed or compacted independently.
- Python Alembic migrations own business table schemas and read indexes. Rust does not create indexes in Python-owned databases. The isolated service identity database is Rust-owned.
- Memory writes, vector writes, persona registry writes, plugin state writes, and runtime command claiming remain Python-owned unless this document is updated with a new explicit owner.

## Repository Structure

```text
magi/
├── backend/
│   ├── src/magi/
│   │   ├── agent/          # Unified agent runtime and child runs
│   │   ├── api/            # Product-facing routers and services
│   │   ├── awareness/      # Sources and runtime event emission
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
│   ├── magi-service-contract/ # Shared launch configuration and wire contracts
│   ├── magi-platform/     # Native filesystem protection
│   ├── magi-server-runtime/ # Service lifecycle and Python supervision
│   └── magi-gateway/      # HTTP/SSE routes, authentication, IPC and DB access
├── server/                # Standalone service CLI and OS service installation
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

### Standalone Mac service distribution

`server/` builds the `magi-server` command. `scripts/prepare-service-bundle.mjs`
stages the server, frozen backend, plugin Python, version, and operator guide as
one component in `build/service`. Desktop bundling consumes that component.
The separate Mac disk image contains the complete `MagiServer` folder and does
not require Tauri or a development Python installation on the host.

The [operator guide](../server/README.md) covers foreground `run`, initial
configuration, private pairing, and the current-user LaunchAgent commands.
The managed service runs after GUI login; it is not a system daemon. Installation
uses a fixed executable/configuration path and rejects replacement of another
installation's launch agent. `uninstall` removes the owned startup registration
and preserves business data and configuration. Desktop removal is independent.
Stop and restart wait for launchd to remove the old registration. Start explicitly
requests a running job, including when the label already exists, so a rapid
stop/start cannot silently accept a departing job as a running center.
`scripts/smoke-service-launchagent.py` validates this lifecycle using a temporary
data root, refuses to replace an existing installation, and removes its own
registration while preserving its test data.

Packaged acceptance uses isolated generated data roots. Run
`scripts/smoke-service-bundle.py --bundle build/service --deny-checkout <repository>`
on macOS to validate relocation with source and Homebrew access denied. Run
`scripts/smoke-service-transfers.py --executable build/service/magi-server --tls-proxy --full-clear`
for authenticated upload/download, two paired clients, SSE reconnection, concurrent
configuration reads, and center-owned clear recovery through an HTTPS proxy.
The proxy uses a temporary test certificate trusted only by that test client;
ordinary certificate verification must reject it, and the OS trust store is unchanged.
Run `scripts/smoke-service-restore.py --executable build/service/magi-server`
for packaged restore, then add `--restart-during-restore` for interrupted-service
recovery. Omit `--project` to use the shipped worker instead of source Python.
These same-host probes do not replace signed, two-device, permission, or target-OS
acceptance, and their concurrent-read timings are not agent performance benchmarks.

Mac release CI builds the standalone disk image from the same signed service
component inside the desktop candidate. The standalone image requires an accepted
notarization result, stapled ticket, SHA-256 checksum, and status manifest.
Both products share the release version and protocol, while protocol negotiation
controls whether a client may connect. Candidates stay in draft until packaged
center startup, proxy/SSE/file transfer, plugin permissions, upgrade, and recovery
validation has been recorded; successful source tests do not establish that evidence.

Reopening a local desktop window reuses its running `magi-server` process and
refreshes the center identity and data epoch from the service before returning
connection metadata. Reusing a process must not reuse a stale maintenance epoch.

The product task surface is `/api/background-tasks`, owned by the Python agent
runtime. The obsolete native `/api/tasks` CRUD and its orphan database path
have been removed; there is no second user-task store or parallel task editor.
