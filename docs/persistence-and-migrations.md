# Persistence & Migrations

Authoritative reference for how Magi stores data on disk and evolves
those schemas over time. If you are about to add a SQLite column,
create a new table, change an index, or reason about which database
file owns a piece of state — start here.

## Desktop background delivery storage

`<Tauri app_config_dir>/delivery/outbox.db` is a private producer database,
independent of the selected server's `data_dir`. `magi-delivery` owns schema
version 1, producer identity, per-destination stream sequences, pending payloads,
leases and retry deadlines. It uses an OS ownership lock, SQLite FULL synchronous
commits, DELETE journaling and secure deletion. Supported platforms use the same
owner-only filesystem protection as connection credentials. Queue capacity is
10,000 outstanding records / 64 MiB of payload, plus at most 10,000 stream
watermarks. Admission fails explicitly when capacity is exhausted.

Server delivery receipts and work items live in `runtime/runtime_trace.db`;
A plugin connection's first ingress epoch is its immutable host-issued UUID.
A clear request durably replaces that epoch in host-only
`plugin-connections/{connection_id}.ingress.json` before erasure. Settings
updates and stop/start preserve it. This metadata is separate from account settings:
the connection registry format is unchanged and needs no compatibility reader or
configuration reset. Runtime trace revision `v7` requires connection-scoped ingress records. Unscoped pre-v7 work is
removed because assigning it to one of several accounts would be unsafe; receipts
retain only identity hashes. Connection erasure removes payloads, and startup
retires any obsolete generations left by an interrupted clear.

Runtime trace revision `v8` adds `plugin_rpc_receipts` for connection creation and
settings-action start. Admission and response commits use SQLite FULL synchronization.
The journal stores an input hash (no request credentials), authenticated device,
data epoch, request identity, owner and bounded response. It permits at most 4,096
receipts and 64 MiB of results, with a 256 KiB per-result limit. It is not an execution
queue: losing the owner of a running attempt makes its outcome uncertain. New
attempt identities expire after 24 hours, so seven-day GC cannot enable a stale
request to execute again; results are retained for seven days. Lookup of an older
identity returns its retained result or an explicit expired outcome. Operator-reviewed
closure writes a completed rejection tombstone without replaying effects; it refuses
live attempts and preserves any already-completed result. The client releases its
saved identity only after the closure is confirmed, and a new execution requires a
separate user action. Connection
content clear and global chat/content clear erase private results while preserving
uncertain identity tombstones. Result recording cannot overwrite such tombstones.

Alembic revision `v6` creates `background_delivery_receipts` and ingress retry
columns/index and the work item delivery epoch. Admission uses a FULL synchronous
transaction for both receipt and payload. Receipts contain identity and a payload fingerprint, not a payload
copy. A reliable sender admits the next sequence only after confirming the prior
ACK. Advancing a stream therefore compacts its receipts to the latest fingerprint
and sequence watermark. Replaying that latest event returns the same ACK;
older stream positions are rejected without execution. No timer deletes a current
watermark. Event identity is scoped to its producer/epoch/stream position; an
event must never be moved to another stream or assigned a new sequence to retry.
There are at most 10,000 retained stream watermarks. Existing streams can advance
at that limit; new streams receive backpressure. Completed ingress payloads are
erased immediately and completed metadata is capped at 1,000 rows.
Failed background ingress work is retained until retried or explicitly cleared.
Full content clear removes receipts and queued payloads under the ingress barrier.
The gateway data epoch additionally invalidates offline work on clear/restore.
The next normal worker retires inbox work and receipts from replaced epochs before
recovering claims; restricted restore workers leave the inbox paused and intact.

## Async SQLite lifetime

Projection repositories only read and write migrated schemas. Profile and portrait
queries must never run DDL. The memory clear-generation singleton is installed by
the migration chain; a missing singleton fails explicitly instead of resetting its
generation to zero. Bootstrap must migrate even when memory layers are disabled,
because destructive clear and recovery still depend on that durable fence.

The composition root supplies the same `UserProjectionRepositories` to API
reads, derivation jobs, chat prompt assembly and the opening dialogue. Prompt
services receive repository methods and a subject-invalidation signal; they do
not infer a database location from L2 or construct their own SQLite repositories.
Durable source revisions and clear generations still gate projection freshness.

The shared helpers in `magi.core.sqlite` own connection creation and closure
through cancellation. Cancelling an awaiting coroutine cannot interrupt SQLite
work already running in its worker thread. An interrupted open therefore waits
for the connection result and closes it; context exit waits for pending work and
closure, including repeated cancellation. Shutdown must not report completion
while these operations can still create or update database files.

## External relational connection boundary

The L1 `MemoryEventRepository.append` boundary commits the event, embedding
state, pinned source payload, source facets, text index and session preview
atomically. SQLite acquires its write transaction before looking up an existing
event or allocating a session sequence. Duplicate identities return the original
event and sequence, including after soft deletion. An interruption rolls back
the sequence and all side records; embedding work is scheduled only after a
confirmed new insertion. Point and filtered reads decode database values into
`MemoryEventRecord`; point reads explicitly select raw, active or user-visible
scope. Evidence lookups exclude deleted events while maintenance identity reads
retain their turn, source and replay identities. Batch hydration preserves caller
order and session windows retain user filtering. Source-facet reads return typed
values; each facet rebuild page holds a write transaction from source selection
through publication, so deletion cannot race between those operations. Counts,
source summaries and retention pages share the repository boundary. The current
live L1 adapter remains SQLite; embedding-state publication and full-clear
lifecycle still use owner-specific SQLite methods.

Selective deletion resolves event and vector identities through the repository,
then removes vectors under the memory service's mutation guard before committing
the source tombstone. Physical purge selects only tombstoned events and repeats
that condition inside its write transaction before removing any side records.
Passing an active event ID to purge cannot delete its payload, facets, text index,
chunks or vectors. Raw deletion selectors intentionally retain hidden identities
so interrupted forgetting can resume.

Pinned capture-time payloads and the durable cognition handoff ledger also use
the event repository. L2 reads the frozen payload rather than a live source;
retry timing and acknowledgement are persisted beside the canonical event.
SQLite payload I/O uses the shared cancellation-drained connection boundary.

`magi.db.mysql.MysqlDatabase` provides connection and transaction infrastructure
for MySQL repository implementations, using the optional `storage-mysql` extra.
Repositories own SQL and row mapping; application services receive domain ports.
Connection settings reference an environment variable for the password, use a
bounded pool and verified TLS for remote hosts, and disable local infile access.
Transactions commit once and close through cancellation. No connection failure
automatically retries a write: the caller may have lost confirmation of a commit.
Driver failures cross repository boundaries as persistence-unavailable or
constraint-conflict outcomes. Schema migration remains a startup operation.

The channel lifecycle scope has both SQLite and MySQL implementations. It includes
thread-aware session bindings, notification and relay cursors, approval preferences,
delivery receipts, and the proactive outreach outbox and receipt log. Both implementations
serve the same domain ports. `StructuredStorageModule` assembles them before channels
start; outreach receives its repositories from that assembly. MySQL tables use InnoDB,
exact identity hashes and complete original identifiers, avoiding truncated indexes or
case-insensitive account collisions. A database is owned by one logical center.

Selection is server startup configuration in `config/agent.yaml`:

```yaml
structured_storage:
  channels: mysql
  mysql:
    host: database.example
    port: 3306
    database: magi_channels
    user: magi
    password_env: MAGI_MYSQL_PASSWORD
    tls: true
    # ca_file: /private/path/to/ca.pem
```

Install `storage-mysql`, provision an empty database and supply the named environment
variable to the server. Localhost-only test databases may disable TLS. Other structured
owners retain their separately configured/current implementations; this option selects
the complete channel lifecycle scope, not every application database.

For an existing center, stop its service, configure the destination, then run:

```bash
python -m magi.bootstrap.channel_storage_transfer --root /absolute/magi-root --target mysql
```

The offline command takes the worker lease, exports a typed logical snapshot, imports
all seven collections in one destination transaction, checks the complete logical digest,
and atomically activates the new binding. Source data remains intact. Selecting SQLite
uses the same command with `--target sqlite`; an occupied owned destination requires
the explicit `--replace-target` flag. Replacement rolls back as one transaction on failure.
Changing between different MySQL servers requires a separate source configuration and
is rejected by this command. The storage setting cannot be edited through the product UI.

`data/channels/storage-binding.json` retains center identity, active destination and an
interrupted transfer intent. Configuration changes alone cannot silently select an empty
store. An unfinished cutover blocks startup; rerun the same command and flags to verify
or resume it without duplicate imports. Pending, attempting and uncertain operations keep
their exact states during transfer; migration never sends a message or replays an effect.
The MySQL owner marker is not part of an exported business snapshot. Copying another
center's database does not grant ownership to a new center.

## Runtime SQLite layout

Personal commitments live in `RuntimePaths.personal_tasks_db_path`
under the app-owned data directory. The `personal_tasks` Alembic target owns
`personal_items` and `personal_item_changes`. The Python personal-task service
is their sole mutation owner; the gateway proxies its authenticated product API.
Current structured fields and the Markdown body are saved with the mutation
receipt in one transaction. Optimistic versions reject stale writes, and scoped
request hashes make retries idempotent. Body revision hashes in change history
avoid copying the complete Markdown into every progress response.

Deleting an item scrubs its current content and change content, while retaining
content-free mutation/deletion receipts to prevent delayed retries and source
replays from recreating it. Project deletion requires an explicit cascade. Full
user-content clear seals admission and uses the same store cleanup; original
chat and source records retain their own deletion scope. Reminder registrations
are derived in the existing scheduler and reconciled after commits and restart.
Memory-only portability archives retain their L0–L4 scope and do not include
this separate product database. Backing up the complete private service data
root must include the app-owned database alongside chat and runtime stores.

Runtime-trace migration `v10` moves notification-center rows from the old
`default_user` owner to the canonical `local_user`; all notification producers
and the center feed use that canonical owner.

All runtime data is rooted under `RuntimePaths.base_dir`
(`~/.magi` in the desktop product). Tests and maintenance code may inject a
different `RuntimePaths` instance, but the shipped Settings UI does not
currently support moving an existing runtime directory. The runtime keeps
state across multiple SQLite files, grouped by lifecycle ownership:

The runtime root is a private operating-system account boundary. Before the
desktop host opens logs or starts Python, it creates or repairs the complete
`~/.magi` tree so only the current account can access it. On Unix-like systems,
directories use owner-only access and files use owner-only read/write access
while preserving the owner's executable bit where required. On Windows, the
tree uses a protected access policy for the current account and the operating
system. The Python worker repeats the Unix protection when it starts outside
the desktop host.

The native protection implementation lives in the Tauri-independent
`crates/magi-platform` leaf crate. Hosts share these OS checks without depending
on each other's UI or lifecycle implementation.

The independent server uses the explicit `data_dir` in its configuration and
passes it to Python as `MAGI_HOME`. The server and Python worker hold separate OS
leases in `runtime/server.lock` and `runtime/worker.lock`; these files carry no
credentials and may remain after a normal or abnormal exit. File existence is
not evidence of a running instance; ownership is determined by the OS lock.

Startup rejects a runtime root or descendant that is a symbolic link, Windows
reparse point, externally hard-linked file, or an entry owned by another
account. It fails before normal runtime startup instead of following the entry
or weakening an external target. This policy applies only to the Magi-owned
runtime root. User-selected workspaces, repositories, photo libraries, and
other external source directories are never traversed or modified by it.

Center authorization lives in `service/server.db`, owned exclusively by
`crates/magi-gateway/src/auth/storage.rs`. Schema version 1 contains the stable
server identity and client names, creation/revocation times and SHA-256 hashes
of high-entropy device credentials. Raw credentials are returned only at
pairing. A newer `user_version` fails closed. The CLI uses a same-account,
permission-protected Unix management socket rather than modifying an active
service database directly.

Pairing grants, access sessions, desktop OS-owner sessions and resource tickets
exist only in process memory. Pairing grants expire after 30 minutes; access
sessions after fifteen minutes; owner sessions end with the host process.
Service restart preserves client authorization but requires fresh access
sessions. Revocation persists and also invalidates existing resource tickets.
Raw credentials and ephemeral tokens must not enter SQLite, YAML, logs,
backups, chat payloads, memory records, or plugin state. `service/server.db` is
outside memory portability and business-data restore ownership.

Native L1 and shared-memory read indexes belong to the Alembic migration chains
(`v5_gateway_read_indexes` and `v53_gateway_read_indexes`). The Rust gateway
never creates schema objects at startup. This keeps production snapshots equal
to the schema used by restore validation; an index outside that contract can
otherwise make a newly created backup impossible to restore.

A confirmed restore uses its inspected candidate UUID as the operation UUID.
Repeated confirmations return the existing operation while it runs or after its
receipt is reloaded; they do not launch a second replacement. A new restore
requires a new inspection. Admission rejects non-canonical candidate identities.

The service writes a separate content-free ownership marker at
`service/memory-restore.pending.json` with a candidate/operation UUID and a
`run` or `verify` stage. This marker fences native readers and HTTP work before
Python replacement starts. Both restricted worker startups recover the Python
journal before loading agents or plugins. Verification reads the existing operation;
it never creates a missing job. Completed maintenance records use format 2 under
`service/operations/`, retain no backup paths or private content, and publish
`data_epoch` separately from the full-clear-only `content_epoch`.

A configuration-only runtime is a valid post-restore state: missing model selection
must not make a portable data restore fail. Its vector rebuild is explicitly deferred.
On normal runtime startup, the latest committed restore with pending/running/deferred
index work resumes a rebuild covering every layer, independently of newer backup or
export jobs. Index completion updates only the indexing field of the committed receipt;
it never reopens or reruns the replacement transaction. Restricted verification workers
cannot start this post-restore work.

Memory portability uses `runtime/memory-portability/` only for private,
short-lived snapshot, inspection-candidate, and crash-recovery state. Automatic
pre-restore safety backups are durable `.magibackup` files under
`data/memory/backups/`; they are not SQLite owners and are never opened by normal
memory reads. User-requested backup and readable-export destinations may be
outside the runtime root.

Only `data/memory/l1_events.db`, `data/memory/memory.db`, configured date archive
databases, and referenced files under `data/media/manual_entries/` participate
in a memory restore. A cutover must never rename or replace the complete
`data/memory/` directory because that directory also contains personality-owned
databases and automatic safety backups. Staged L1 and shared-memory databases
must pass manifest integrity, SQLite `quick_check`, and their own Alembic
revision validation, then upgrade to the installed heads before cutover. An
unknown revision is a future/incompatible backup and must be rejected rather
than guessed through a compatibility path.

A restore uses a singleton, owner-only, content-free journal at
`runtime/memory-portability/memory-restore.pending.json`. The journal records
only its transaction ID, process owner, phase, target identities, private
artifact paths, and file/tree integrity digests; it never records a password,
source package path, prompt, or memory payload. Before live mutation, the
engine creates an unencrypted but owner-only safety `.magibackup`, complete
logical SQLite rollback copies, and incoming sibling stages on every target
filesystem. It synchronizes the journal before replacing L1, shared memory,
the managed date-archive set, or the manual-entry asset directory, and removes
SQLite sidecars at each database boundary. A normal exception rolls back
immediately. On process startup, `runtime_memory_restore_recovery` runs before
`runtime_database_migrations`; any uncommitted cutover is rolled back
idempotently before Alembic opens the databases. The only skip is an explicitly
registered same-process transaction while the caller initializes and validates
the newly restored runtime. The caller commits only after runtime validation
and durable index-rebuild admission succeed. A crash after that commit keeps
the new files and finishes removing plaintext rollback artifacts.

| File | Owner | Holds |
|------|-------|-------|
| `data/chat/chat.db` | chat | sessions, session-creation idempotency mappings, turns, durable root-turn execution budgets, visible messages, append-only model-context events, current context surfaces, deduplicated system/tool epochs, model-call boundaries, attachments, per-turn context-usage snapshots, canonical message-to-asset and message-to-code-delegation ownership, private attachment/code-delegation cleanup registries, named boundary summaries, user-turn delivery checkpoints, retryable assistant-memory projection intents, interrupted global-clear intent, permanent cleared-session and cleared-message scopes |
| `data/memory/l1_events.db` | memory L1 + L1-projected chat sessions | normalized event log, embeddings, FTS, entity links |
| `data/memory/memory.db` | memory L0 / L2 / L3 / L4 | short-term attention checkpoints, grounded Claim/evidence/entity-reference ledgers, exact L2 projection attempts and outcomes, knowledge graph, ToM, correction history, stable context identities, summaries, procedural skills |
| `runtime/runtime_trace.db` | runtime trace | canonical run manifests/events, versioned plans, normalized spans / llm calls / tools, plugin ingress events |
| `runtime/llm_usage.db` | llm | per-request usage + cost telemetry, daily rollups |
| `data/app/persona_registry.db` | personality | personas, active persona, source-linked reference dossiers for generated personas |
| `data/memory/behavior_evolution.db` | personality | historical task interactions, category statistics, and behavior profiles; no runtime collection or inference |
| `data/memory/emotional_state.db` | personality | emotional state KV + events |
| `data/memory/growth_memory.db` | personality | milestones, relationships, personality evolution |
| `runtime/scheduler.db` | scheduler | schedules, execution history, source sync jobs |

| `runtime/bootstrap_state.db` | bootstrap | completed revisions, content fingerprints, attempts, and errors for versioned startup work |
| `runtime/message_queue.db` | runtime | runtime command queue, stable user-turn deduplication, command rollups, plugin/source full-clear checkpoint, pending service full-clear transaction |
| `runtime/source_state.db` | sources | per-source cursors, fingerprints, stats |
| `runtime/background_tasks.db` | runtime | background-task rows and event history, stable task-level execution budgets, privacy-minimized tool-effect intent/completion records, plus recoverable terminal-completion snapshots with frozen outreach intent/body |
| `runtime/permission_rules.db` | runtime permissions | trust and permission rule state |
| `data/channels/channels.db` | channels + outreach | external channel session mappings, binding preferences, delivery receipts, notification cursors, proactive-outreach outbox and delivery log |
| `data/identity/identity.db` | identity | external channel identity to canonical user mapping |
| `data/batch/batch.db` | batch | batch job and item manifests |
| `data/memory/self_memory_v2.db` | (reserved) | — |

Scheduler migration `v3` adds content-free creation receipts keyed by the client
schedule identifier. A request fingerprint prevents identifier reuse with a
different payload. Receipts survive schedule execution, deletion, and user-data
clear, so delayed retries cannot resurrect completed work; they contain no
prompt or metadata text. Schedule read revisions use the definition's
`updated_at` value. Runtime job binding changes leave that revision unchanged;
conditional definition writes compare it inside an immediate SQLite transaction.

### Versioned startup work

The shared-memory revision `v50_profile_fact_descriptions` removes only the exact
obsolete profile-settings diagnostic template from assertion `natural_summary`.
It preserves other retained wording, semantic values, evidence, lifecycle and
timestamps. New settings writes no longer create that diagnostic, so no runtime
source-name exception or old-format fallback is required.

The revision `v51_portrait_prompt_contract` adds a persisted prompt contract
version to the portrait cache. Existing rows retain their text and receive
version `0`; the migration initially required a successful rebuild to record
version `1`. The current host-resolved wording contract requires prompt version
`2`, using the same persisted field without another schema migration. Older
prompts are ineligible for model-context fallback,
including when L2 or profile reads fail. Current-contract caches still follow the
existing last-successful-result policy on transient failures. This version is
independent of the UI item shape, assertion lifecycle and source revisions.
The same migration clears the rebuildable `user_profile_projection` cache so
unchanged source highwaters cannot preserve values decoded under the previous
generic JSON rules. Retained assertions, evidence and portrait prompt text remain
unchanged; subsequent reads rebuild profile fields with their trait-specific
value contract.

Claim-backed assertion wording has a separate, explicit recovery boundary:
`magi.memory.l2.assertions.summary_recovery.recover_assertion_summaries` accepts
between 1 and 100 exact assertion snapshots (`assertion_id`, `expected_updated_at`,
`expected_summary`) and defaults to `dry_run=True`. It never scans or repairs an
entire memory database automatically. Under one write transaction it checks live
assertion state, active immutable Claims and projection receipts, authoritative
entity identities, routed semantic values, supporting and antecedent evidence,
source deletion/forgetting barriers, user corrections, and completed source
projection jobs. A stale snapshot, unresolved name, conflicting support, or a
competing projection refuses the affected item.

A committed repair replaces only `natural_summary` and the assertion's
`updated_at`, appends an `assertion_summary` recovery receipt, invalidates L3
insights linked by dependencies to those exact rebuilt assertions, and advances
the affected subject revision. L3 invalidation removes stale search entries while
preserving existing insight content and user review states until rebuilding.
Only current or already stale dependencies are eligible; retired, rejected and
deleted insights are excluded. Unrelated insights remain unchanged. Claim bodies,
evidence, negation, temporal cues,
confidence, promotion, correction and forgetting state remain unchanged. The
revision makes stale profile and portrait caches ineligible immediately; normal
reads rebuild them even after an interrupted recovery.

Explicit L3 wording recovery requires every original dependency to be an
assertion. Mixed assertion/edge dependencies fail closed and remain stale, so a
wording repair cannot drop an edge's correction or forgetting dependency.

Operators can rebuild the affected profile and portrait immediately through the
existing handlers:

```python
from magi.memory.l2.assertions.summary_recovery import (
    AssertionSummaryRecoveryRequest, recover_assertion_summaries,
)
from magi.user_profile.correction_derivation import UserProfileCorrectionDerivationHandlers
from magi.memory.l3.correction_derivation import L3CorrectionDerivationService

# Build these snapshots from a read-only inspection of explicitly selected rows.
requests = [AssertionSummaryRecoveryRequest(assertion_id, updated_at, natural_summary)]
preview = await recover_assertion_summaries(db_path, requests=requests, language="zh")
# Apply the same inspected snapshots after reviewing the preview.
result = await recover_assertion_summaries(
    db_path, requests=requests, dry_run=False, language="zh",
)
handlers = UserProfileCorrectionDerivationHandlers(db_path=db_path, l2_store=l2_store)
insights = L3CorrectionDerivationService(db_path=db_path, l2_store=l2_store)
for subject, revision in result.subject_revisions.items():
    job = {"target_key": subject, "target_revision": revision}
    await handlers.rebuild_profile(job)
    await handlers.rebuild_portrait(job)
    if result.l3_summary_ids:
        await insights.rebuild_subject(
            subject, expected_revision=revision, summary_ids=result.l3_summary_ids,
        )
```

This operation needs no model call when the retained Claim, evidence and entity
resolution already describe the correct proposition. It repairs derived text,
including summaries previously generated from entity IDs, without rewriting
immutable Claims. A mistranslated Claim requires the versioned original-event
extraction workflow under extractor contract 7; it must retain source, deletion,
forgetting, correction and exact task-lease barriers. Summary recovery and route
reprojection are not substitutes for that workflow.

`runtime/bootstrap_state.db` is the central ledger for bounded startup work
whose result can be reused across launches. Each step owns a stable ID, an
explicit revision, and an optional content fingerprint. The expected revision
stays in code; the ledger records only the last successful revision and source
fingerprint plus the latest attempt state.

The ledger follows these rules:

- unchanged successful steps are skipped without rewriting their target store
- a new revision or content fingerprint triggers the owning step
- success is recorded only after the work completes
- failure preserves the last successful revision and records the failed attempt
- work interrupted by a dead process is reclaimable on the next launch
- a live second process cannot execute the same step concurrently

The ledger does not replace per-database Alembic revisions. Schema versions
remain inside each owned database so restoring or replacing one database cannot
be hidden by a global bootstrap record. Crash recovery, process-local bindings,
and other every-launch work also remain outside the skip mechanism.

Source bookkeeping uses `runtime/source_state.db` with `source_cursors`,
`source_fingerprints`, and `source_stats`, keyed by `source_id`. Its Alembic
environment is `backend/src/magi/db/migrations/source_state/`. Scheduler
attempts live in `source_sync_jobs` in `scheduler.db`. These names are part
of the unreleased Source contract; no old-name aliases or rename-specific
data migration are provided.

The source sync history API projects this existing ledger per connection and
source, with a bounded page size. Failure category and service platform are stored
under `stats_json.failure`; original bounded error text stays in `error`. Permission
failures are terminal for that job, while transient failures retain bounded retries.
Worker IPC preserves permission failures as typed errors rather than requiring the
host to parse exception messages. No duplicate error-history table is maintained.

Source pagination is part of scheduler truth. When a completed source batch
reports more source data, `scheduler.db` records the parent success and admits
the next queued job plus execution row in one transaction. A failed
continuation insert rolls back the parent success instead of leaving a
successful record with unqueued source data.
Each continuation carries the parent's explicit connection identity and sync
request, keeping normal sync and backfill on the same connection and checkpoint.
A missing connection identity rejects the continuation within that transaction;
it is never inferred from a plugin name or another available connection.

A destructive full clear treats scheduler configuration and scheduler content
differently. It preserves system-owned schedules and each source's cursor,
watermark, and binding, while deleting user-created agent schedules, their
runtime jobs and target state, every execution-history row, and every queued or
running source-sync job. Remaining target state keeps progress fields but loses
error and statistics payloads. The scheduler applies SQLite secure deletion and
truncates its WAL before reporting that this store has been cleared, so removed
prompt, result, error, and statistics text is not left in database sidecars.

A full clear applies the same physical-cleanup rule to every SQLite store from
which it removes user content. After writers are quiesced and logical deletion
commits, the owning boundary rebuilds the database from live rows and truncates
its WAL before success is reported. This covers shared memory, runtime traces,
LLM usage, background tasks, batch manifests, channel conversation state,
scheduler history, chat, the runtime command queue, and learned persona state.
Configuration rows intentionally retained by the product remain live; deleted
payload bytes must not remain in free database pages or SQLite sidecars.

The independent server coordinates crash recovery with
`runtime/full-data-clear.pending.json`, using shared native marker primitives
from `crates/magi-platform`. The marker contains only a version and opaque
transaction ID. It is atomically published and synced before destructive work;
one valid transaction-named temporary file can recover an interrupted write.
Invalid names, multiple candidates and filename/payload conflicts fail closed.

Native database handles own bounded maintenance permits. Closing the gate
rejects new native reads/writes and waits for existing handles, even when their
HTTP caller has disconnected but a blocking task is still running. The server
then stops its normal worker and launches a recovery worker with the pending
transaction ID. Python adopts that ID before queue recovery and suppresses
ordinary agents, collectors and background work. Only the supervisor invokes
the internal full-clear implementation. A failed clear keeps the marker and
business gate closed; the same operation can be retried or recovered on restart.

Python clears its pending queue row and truncates its WAL after its own phase
succeeds. The server stops that recovery worker, clears server logs, persists
content-free completion/count records in `service/operations/`, and removes the
pending marker. A completion record survives an ambiguous HTTP response and
makes the same operation ID idempotent. If the process exits after completion
publication but before marker removal, startup finishes the marker removal
without repeating the clear. The completed operation also becomes the durable
business-data epoch. Center identity and paired devices remain unchanged;
private resource tickets are invalidated. Normal workers restart only afterward.

Client cache and desktop-log cleanup are device-owned. The connection integration
must compare the center's data epoch and clear stale local state before allowing
interaction; an offline device cannot hold the center's completion hostage.
The previous desktop-coordinated UI flow is being replaced alongside the local
service-host migration.

Plugin- and source-owned user content uses the same full-clear generation stored
by the runtime command queue. `runtime_plugin_user_content_clear_state` records
only the latest generation whose plugin/source hooks may be treated as applied;
it is not the global clear completion record and does not create a second
generation stream. It advances only at the surrounding clear's success edge.
The checkpoint remains behind when any hook fails, the clear
is cancelled, a later global clearer or diagnostic-log erasure fails, or source
collection cannot be resumed safely. Collection is started in a non-claiming
paused state before the checkpoint write and released only after that write
succeeds. Startup detects a pending shared generation after plugins load and
fails closed before collection or other plugin ingress starts; plugin-only
replay is not allowed to claim completion for the cross-store clear.
Configuration, credentials,
connected-account state, and source cursor/watermark are intentionally retained;
plugin hooks delete only their locally retained raw, derived, pending, and
temporary user content.

The stable-context migration converts legacy free-text correction scopes into
typed local identities. Scoped relationship IDs and uniqueness are rebuilt at
the same boundary, and all version, correction, dependency, snapshot, profile,
and portrait references are rewritten together. Malformed scopes are isolated
instead of becoming global. Alias collisions retire losing current claims and
invalidate affected derived views so they can be rebuilt from the surviving
governed records.

Relationship correction side effects are stored separately from mutable
relationship rows. This lets revert restore only the state still owned by the
correction and preserve evidence added after the correction was created.

Each subsystem owns the schema for its own file. There is no
cross-file foreign-key enforcement.

The historical behavior database keeps its registered schema and runtime path
for explicit learned-state clearing. Normal persona initialization and chat
processing neither read nor update its behavior records. Clearing removes all
three historical tables' rows and securely compacts the existing database; it
does not create a missing database or remove the database file. This deletion
responsibility does not reintroduce a behavior-learning execution path.

The persona registry stores reference research separately from the runtime persona
configuration. `persona_reference_dossiers` is keyed by stable `persona_id` and
keeps the canonical reference fingerprint, grounding status, structured evidence,
source metadata, coverage, contradictions, and unknowns as one validated JSON
document. It does not store fetched page bodies. Builtin, original, and private-
person personas need no dossier row. Repeated onboarding creation with the same
persona ID may refresh the dossier without creating a second persona.

The runtime command queue provides durable **at-least-once handoff through chat
agent admission**. Publishing a user message to the process-local bus does not
acknowledge its command. The command remains claimed until the task-agent
manager has either admitted that exact delivery attempt or recognized it as an
already admitted or superseded attempt. Lease expiry or acknowledgement failure
may replay the same physical command and attempt. On process startup, the queue
restores claimed rows and chat recovery first checks for a durable terminal
surface. Any remaining pre-restart non-terminal attempt is superseded by a
higher attempt and scheduled with a new command ID while preserving the stable
turn ID and runtime envelope. Stable correlation IDs identify the logical turn,
while an explicit attempt number and command ID distinguish deliberate
redelivery from duplicate transport. Repeating the same attempt is idempotent;
only a higher attempt creates a new command, including after completed command
rows have been cleaned up.

This closes the former publish-to-subscriber loss window, but it does not make
agent execution or external side effects exactly once. A replay after admission
is rejected by the durable chat delivery record and then acknowledged without
entering the agent twice. Transcript completion and external tools must still
converge on stable turn or message identities and provide their own
idempotency where needed.

Chat read pages use the `v18` keyset indexes and content-free
`chat_read_revisions` ledger. Session-list revisions are per user; history
revisions are per user and session. SQLite triggers advance the owning revision
in the same transaction as session, message, turn, and context-usage mutations,
including updates and deletions. Epochs prevent a recreated revision scope from
matching an older cache. Revision rows contain scope identities and counters,
without transcript text. Global chat clear removes the ledger in its final
cleanup transaction so session identities cannot survive erasure; newly created
scopes receive fresh epochs. `history_version` retains its separate prompt-history meaning.

Runtime trace revision `v9` adds a separate, content-free per-user/session
`trace_read_revisions` ledger. Triggers cover turn records, spans, model/tool
details, run manifests/events, and plans, including updates and deletions. This
revision remains distinct from the chat ledger because trace details can settle
after a chat turn becomes terminal. History validation includes both revisions
and checks the trace revision again after projection so a concurrent trace write
cannot publish a mixed snapshot. The revision lookup uses the owner primary key
and does not reconstruct trace trees. Session deletion removes its ledger scope;
global clear removes every trace revision before database compaction and WAL
truncation, and recreated scopes receive fresh epochs.

The Python chat session reader loads its revision and page within one
read transaction. History combines its chat revision with the `v9` runtime-trace
scope revision. It keeps the chat read snapshot open and checks the trace
revision before and after enrichment; a concurrent trace write retries the read
up to three times, then reports temporary unavailability instead of returning a
mixed snapshot. Late terminal trace events therefore invalidate cached history
without forcing other sessions to reload. Cursors bind the owner, session
or list scope, revision, and the timestamp/sequence/identity boundary. A changed
snapshot rejects its old cursor with `409 stale_page_cursor`; clients restart
from the newest page. Unchanged first-page reads may return `not_modified`, and
active chat turns bypass conditional history responses so trace activity can
still reconcile. Pages read at most the requested message/session count plus
one lookahead row before display enrichment. Per-turn trace status appears only
on the page containing that turn's first visible message, and exact-turn recovery
also includes its initiating user message through one bounded anchor lookup.
A selected session outside the recent list is resolved through the authenticated
`GET /api/messages/session/{session_id}` lookup; it returns the same typed summary
and rejects another owner, an archived session, or a deleted session with 404.

The chat-owned user-turn ledger moves through ready, queued, admitted, and
terminal states. Terminal is evidence-backed: it is written only after the
matching chat turn has a durable final surface, a legal no-message/reaction
outcome, a persisted cancelled/interrupted/merged state, or another durable
handoff. When the runtime fact carries an attempt number and command ID,
terminal transition is an exact compare-and-set; a late result from an older
attempt cannot close a newer one. Recovery without command identity may close
only the currently stored attempt and only after verifying the durable terminal
surface.

Terminal-surface recovery closes the chat turn and its exact delivery attempt
in one `chat.db` transaction. It may update an existing queued or running turn
to completed when the durable final or complete rhythm surface proves the
result, but it never inserts a missing turn. This keeps a late recovery pass
from recreating a turn that message or session deletion already removed. The
chat `v4` migration applies the same rule while backfilling existing delivery
rows.

User-memory delivery is an independent obligation on the accepted user-turn
ledger. Ordinary chat can proceed when memory projection is temporarily
unavailable, but `projection_completed` remains false until a memory-owned
receipt confirms L1 persistence and the required durable L2 job, or an explicit
disabled-layer, empty-prose, quarantine, policy, or forget disposition. Publishing
to the process-local bus alone is not a receipt. Startup and periodic recovery
also inspect queued and terminal turns with pending memory; they retry only the
memory projection for already executed turns and never rerun the agent.
Confirmation uses the original accepted timestamp and stable business identity,
so a forget rule terminates the obligation without resurrecting the message.
For chat user and assistant projections, event translation also preserves the
committed chat timestamp in `MemoryEvent.created_at`. Retries cannot substitute
the current delivery time, and payload metadata cannot override this clock.
The memory-owned write guard therefore enforces the same turn cutoff even when
forgetting occurs between publication and ingestion.

L1 cognition handoffs survive database backup inspection as durable obligations.
The existing backup sanitizer still omits L2 execution jobs: a backup taken after
L1 handoff acknowledgement but before L2 job completion does not retain that
pending execution. The new handoff ledger guarantees runtime restart recovery,
not complete reconstruction of this already-handed-off backup window.

Assistant transcript completion and assistant-memory projection use one chat
transaction. The chat store derives the projection directly from the committed
assistant rows, so callers cannot save a visible answer while forgetting its
memory handoff. A normal final reply uses its message ID and text. A segmented
reply uses the first segment ID as the stable identity and the ordered segment
texts joined with newlines as the canonical content. Reaction-only and other
legal no-message outcomes create no projection work.

The same accepted-outcome transaction stores one context-usage snapshot when a
provider input measurement is available. The snapshot keeps the used input,
the exact model window and input capacity used for that turn, the compaction
threshold, the model identity, and whether the count was provider-reported or
estimated. History reads select the newest snapshot whose final assistant
surface is still visible, so reload survives process restarts and deleting the
latest answer falls back to the previous visible turn. Runtime notifications
only refresh this durable state; they are not its owner.

The pending projection remains in `chat_assistant_memory_outbox` until L1
confirms the exact `chat` / `AIResponse` / message-ID identity. A worker starts
during runtime bootstrap, recovers expired claims, retries with bounded
backoff, and periodically scans even if its in-process wake hint was lost. It
checks L1 before publishing so a crash after successful ingestion does not
publish a duplicate. If L1 is disabled, the row is completed without blocking
the visible reply. Successful confirmation deletes the outbox row, including
its answer text; failed attempts retain the text only for the next retry.

Terminal background-task delivery uses the same durable-work principle in
`background_task_completion_intents`. The first outreach intent and rendered
body are frozen before delivery, and every attempt is claimed in the database.
Pending rows are drained both after startup and by the bounded periodic
outreach pass, so a live delivery failure does not require a process restart.
Successful acknowledgement scrubs the private snapshot and removes it from
pending work; retries retain the same task-attempt identity and wording.

Destructive chat operations use two database phases around external cleanup.
The first phase validates the exact message or transcript snapshot, removes all
public content and attachment metadata, and retains only private ownership
records for managed attachments and code-delegation artifacts. Code delegation
is registered before its first filesystem write, so cleanup does not depend on
an assistant message having been committed successfully. The first phase
commits before any trace row, managed file, delegation log/diff, temporary
worktree, or delegation branch is deleted. After external cleanup succeeds, a
second transaction removes those private records and physically deletes the
redacted message and turn rows. Shared artifacts survive while another visible
message in an active session still owns them. Applied edits in the main
workspace are user project state and are never reverted by conversation
deletion. A crash or cleanup failure therefore never leaves public transcript
content pointing at an already removed file, and retry retains exact cleanup
identities without retaining user-facing content.

The same operation holds a matching background-task admission scope from before
the memory delete snapshot until chat-surface cleanup returns. Enqueue and retry
check that scope under the manager's admission lock, so newly submitted work
cannot enter between cancellation and deletion. Exact-message deletion derives
the scope from the complete logical replacement chain, including linked task
and pending-message identities; session and history operations hold the whole
user/session scope. Work outside the selected scope is unaffected.

Full chat clear uses the same ordering and additionally persists one
`chat_global_clear_intent` row in the first transaction. The intent records the
original visible-session count. Chat cleanup removes traces, assets, messages,
turns, and sessions but deliberately retains the intent: the same clear also
owns conversation mappings, delivery receipts, notification cursors, pending
proactive outreach and its delivery log in `channels.db`, plus persisted
background execution state outside `chat.db`. The intent is deleted only after
those stores have also been cleared.

The full-memory clear boundary holds a global background admission seal,
cancels matching non-terminal work, and waits for its terminal listeners until
the cross-store clear finishes. It then deletes every task row, event, and
completion intent from `background_tasks.db` before releasing admission. The
Tasks UI may still dismiss individual rows and scheduled retention still
governs ordinary operation, but a product-wide clear does not preserve this
audit history.

Startup recovery is split across the stores. Chat recovery first finishes the
local redaction and physical cleanup while retaining the intent. Before channel
plugins start, the channels lifecycle sees that marker, clears channel
conversation and outreach state, and then asks chat to complete
the intent. External delivery remains blocked while the marker exists. This is
an immediate crash-recovery path; it does not rely on the periodic orphan-file
retention window.

Deleted and globally cleared session IDs are retained in
`chat_cleared_session_scopes`. The table key, session lookup, and the unique
`chat_sessions` identity index all use case-insensitive comparison. Insert
triggers on sessions and every session-scoped chat table reject a cleared ID,
a case-only alias, an archived/deleted session, or any write while the global
clear intent is active. These tombstones are permanent privacy barriers, not
temporary recovery rows.

An explicit stop does not depend on an in-memory run already existing. The chat
store validates the requested user, session, and turn in the same transaction
that marks the turn cancelled and closes any ready, queued, or admitted
delivery. A queued runtime command may remain in the separate queue database
briefly; when consumed, the terminal chat record rejects admission and the
command is acknowledged. A fact already transferred into an in-memory agent
batch is revalidated against the same exact delivery before any context, tool,
or model work and is discarded if cancellation or supersession won. Other
executable facts in that batch are preserved. The final revalidation and
in-memory run creation are serialized with stop: cancellation either closes the
delivery before a run exists, or observes and cancels the exact run that was
created first. This deliberately avoids pretending that the queue and chat
databases share one atomic transaction. Repeated stops are idempotent, while a
completed outcome that committed first remains completed.

An ordinary text message received while a session run is active remains a
durable chat turn and is attached to that exact run as pending input.
`RunInputQueue` consumes it once at a safe model-step boundary and records the
supersession link to the root turn. Structured interactions that require a new
root run remain in the normal durable delivery flow. There is no persisted
AUGMENT/STEER/DEFER semantic disposition and L0 does not own this recovery.

L0 tables persist only disposable workbench projections: session metadata,
attention items, L0-local source barriers, and temporal entity cutoffs. An
attention item stores its kind, compact summary, lifecycle state, confidence,
salience, source turn/event references, the durable accepted times of its
source turns, optional linked entity or task attempt, and expiry metadata.
Exact raw-turn deletion cutoffs are instead shared memory governance: they
survive an ordinary L0 clear and are removed only by full-memory clear.
Full-memory clear removes dormant rows from every persisted memory layer even
when that layer is disabled. L0 does not
persist current chat runs, pending interruptions, cancellation controls,
triggers, tool results, or its pending post-turn analysis queue. The
runtime-scoped queue is shared across chat-agent instances; only runtime
shutdown attempts to flush it for up to five seconds. A crash can lose pending
analysis or uncheckpointed changes. Execution recovery comes from the chat
delivery ledger, which re-drives non-terminal turns with a fresh live run;
startup does not rebuild a missed L0 analysis backlog.

## Two tiers of schema management

### Tier 1 — Alembic-managed runtime DBs

These have schema that evolves under load. They each have an
independent Alembic environment with its own version chain:

| env name | file |
|----------|------|
| `chat` | `chat.db` |
| `l1` | `l1_events.db` |
| `memory_shared` | `memory.db` (L0/L2/L3/L4) |
| `runtime_trace` | `runtime_trace.db` |
| `llm_usage` | `llm_usage.db` |
| `persona_registry` | `persona_registry.db` |
| `behavior_evolution` | `behavior_evolution.db` |
| `emotional` | `emotional_state.db` |
| `growth_memory` | `growth_memory.db` |
| `scheduler` | `scheduler.db` |
| `source_state` | `source_state.db` |
| `background_tasks` | `background_tasks.db` |
| `message_queue` | `message_queue.db` |
| `permission_rules` | `permission_rules.db` |
| `channels` | `channels.db` |
| `identity` | `identity.db` |
| `batch` | `batch.db` |

Current heads that matter to the chat-clear, memory-projection, and delivery boundaries:

| environment | head | Boundary added at head |
|-------------|------|------------------------|
| `chat` | `v21_outbound_redaction` | per-target delivery intents and content-scrubbing receipt retention |
| `background_tasks` | `v4` | tool-effect intent/completion ledger with explicit uncertain crash recovery |
| `batch` | `v2` | remove the unused inline-driver reconciliation limit while preserving job and item manifests |
| `channels` | `v3` | connection and thread scoped session bindings |
| `runtime_trace` | `v12` | durable questions, atomic answer arbitration and frozen notification intents |
| `message_queue` | `v7` | pending service full-clear transaction adopted before command recovery; success returns to an empty idle row |
| `memory_shared` | `v53_gateway_read_indexes` | own native query indexes in the portable schema; earlier heads include portrait prompt contracts and entity identity governance |
| `l1` | `v5_gateway_read_indexes` | own the native deleted-event query index in the portable schema |

`chat_task_execution_budgets` is owned by the accepted root turn. Its
`root_turn_id` is a non-null primary key and a foreign key to `chat_turns`, with
`ON DELETE CASCADE`, so session, turn, and full-clear deletion cannot leave an
orphaned allowance. Reservations and refunds use immediate SQLite transactions;
the limits first persisted for a root remain authoritative after restart.
Chat-derived background continuations retain this root identity. Standalone
background tasks store the equivalent counters on their `background_tasks` row,
keyed by the stable task id, so another attempt or process restart rehydrates the
same allowance.

Chat model context is intentionally separate from the visible transcript:

- `chat_model_context_events` is the append-only provider-neutral event log;
- `chat_model_context_surface_nodes` orders the events visible to the next model
  call, while `chat_model_context_heads` owns its optimistic revision;
- `chat_model_context_epochs` deduplicates the exact stable system prompt and
  canonical tool declaration set;
- `chat_model_context_boundaries` binds each actual model call to one surface
  revision and one epoch.

The runtime synchronizes the surface before a model call and after every output
that can affect a later call. Surface replacement records new events instead of
mutating earlier log rows. Raw attachment bytes are not stored in context JSON;
stable attachment identifiers and metadata are retained. The runtime trace
stores only privacy-safe fingerprints and metrics, not a duplicate prompt
archive.

There is no data migration from `chat_messages` or an earlier transcript-summary
format. Existing development sessions begin with an empty context head when they
receive their first post-cutover turn. This follows the pre-release no-
compatibility policy and prevents the visible transcript and Model Context Log
from becoming competing prompt sources.

Message deletion clears the complete session Model Context Log because surviving
context may still contain the deleted content or a tool result derived from it.
History clear, session deletion, and global clear physically remove the matching
heads, events, surfaces, epochs, and boundaries inside the governed chat cleanup
transaction. The visible transcript is never used to reconstruct a partial
replacement after deletion.

`tool_effect_attempts` is the execution-safety source of truth for non-read-only
tool calls. It stores stable scope and tool-call identities plus SHA-256 digests,
never raw arguments or results. An intent is committed before the tool body is
entered. Process recovery converts leftover `attempting` rows to `uncertain`;
only policies that prove replay safety may pass an unresolved matching row.
Conversation-scoped deletion removes matching effect rows, and global clear
removes and compacts the complete ledger under the background admission seal.

The L2 Claim-ledger chain was introduced by `memory_shared` revisions `v38`
through `v42`: grounded Claims and their evidence/projection outcomes, projection
leases, the durable L2-to-L1 entity-link outbox, Claim-aware subject revisions,
and exact projection-batch descriptors. Fresh-store baseline DDL and each
incremental migration define the same columns and indexes. `v42` deliberately
adds nullable descriptor fields and resets legacy `queued` / `running` rows to a
retryable pending state rather than guessing the members of an interrupted
attempt; the new runtime then enforces exact descriptor binding before execution.
`v48` is a bounded repair over durable `known_events` operations whose selector
explicitly records `replay_policy=explicit_reimport` and whose reason is
`history_import_deleted`. It deletes only those stable event IDs from the L2
projection queue, removes only their event-scoped forget evidence, preserves
mixed or unrelated rules, excludes every event that still has a permanent replay
tombstone or any non-reimportable durable forget operation, and resets affected
active import memberships for a real retry.
Permanent and ordinary forgetting operations are outside its scope.
`v58` adds `history_import_source_records.source_role` with a checked
`user|assistant|other|unknown` vocabulary. It stores the importer-declared role
independently of the user's confirmed participant mapping. Existing rows default
to `unknown`: previously discarded roles cannot be recovered from names or prose.
The migration preserves existing content, mappings and L1/portrait state; new
imports enforce immutable roles and reject assistant/other self-selection.
Calendar timezone and civil-range provenance live in L1 event metadata and the
Claim temporal frame, so they require no additional shared-memory schema revision.

Layout under `backend/src/magi/db/`:

```
db/
  __init__.py              # exports MIGRATION_TARGETS, run_upgrade_head
  __main__.py              # python -m magi.db CLI
  _alembic_env.py          # shared env.py logic (every env delegates here)
  runner.py                # MigrationTarget table + run_upgrade_head()
  migrations/
    chat/
      env.py
      script.py.mako
      versions/
        v1_initial.py
    l1/...
    memory_shared/...
    runtime_trace/...
    llm_usage/...
    persona_registry/...
```

### Store baselines

Some stores keep `CREATE TABLE IF NOT EXISTS` baseline DDL for fast
fresh-install initialization, but registered runtime DB schema is still
owned by its Alembic environment. Additive schema changes to registered
DBs require both a migration revision and a matching baseline update.
Reserved or experimental stores that are not in `MIGRATION_TARGETS`
may still use store-owned DDL until they graduate into a migration
environment.

## Operational lifecycle cleanup

Runtime data retention is configured in `~/.magi/config/lifecycle.yaml`,
materialized from `backend/configs/lifecycle.example.yaml` on first run.
The maintenance daemon combines memory maintenance with operational GC.

Current governed runtime cleanup:

| Area | Default behavior |
|------|------------------|
| `runtime_trace.db` | delete run journals, run plans, normalized traces, notifications, and terminal plugin ingress rows older than 7 days |
| `llm_usage.db` | roll up expired raw rows by day, then delete raw rows older than 7 days |
| `message_queue.db` | roll up completed rows by hour, delete completed rows older than 24 hours, delete failed rows older than 7 days |
| `scheduler.db` | delete success history after 30 days and failed history after 60 days |
| `source_state.db` | keep only the latest configured fingerprint count per source |
| `background_tasks.db` | delete terminal task rows, event history, and their completion-intent rows after the configured background-task history window |
| chat resources | preserve every file with a surviving message owner, including hidden transcript rows; remove unclaimed files from active sessions only after the longer of the configured grace period or 25 hours; optionally sweep old orphan session directories after the configured grace period |
| ephemeral jobs | personality generation job snapshots use the configured TTL |

Cleanup deletes operational rows or files after any configured rollup step;
it does not soft-delete runtime telemetry. Durable memory history remains
governed by the memory retention/archive settings described in the product
configuration guide.

Chat upload storage and transcript ownership are intentionally separate:
uploading writes the managed file first, while accepting the message creates
its durable owner record. Periodic cleanup therefore always bounds abandoned
uploads in active sessions, even when orphan session-directory cleanup is
disabled. The extra 25-hour floor protects in-progress browser recovery across
a full day. `lifecycle.chat_assets.delete_on_session_delete` controls only the
whole-directory sweep for sessions that no longer have an active row; it does
not disable cleanup of unclaimed upload files.

User-requested memory deletion is tracked separately from periodic retention.
The shared memory database stores the selected source references, replay
barriers, cleanup progress, projection blocks, and the current recovery lease.
Time-range deletion also stores the interval itself, its L1-retention choice,
reason, and owning operation. This interval remains active after the original
cleanup completes so a source first synchronized later is governed before it
can recreate memory from that period. Full memory clear removes both the range
rules and their operation history.
The complete selected L1 set is hidden when its barriers commit; cleanup of
derived memory, chat projections, and archives can then resume safely after a
crash. Startup must stop if these barriers cannot be read or pending deletion
cannot be recovered, because continuing would allow data the user removed to be
projected again.

## How migrations run

`DatabaseMigrationModule.init` (in `backend/src/magi/db/lifecycle.py`)
calls `magi.db.run_upgrade_head(runtime_paths)` immediately after core runtime
paths are initialized and before any store opens its connection. It iterates
`MIGRATION_TARGETS` and runs `alembic upgrade head` against each. A failure
aborts startup with a logged error.

Every store also keeps its own baseline `executescript(...)` of
`CREATE TABLE IF NOT EXISTS` statements as a fast path on fresh
installs. Because every CREATE in both the store baseline and
`v1_initial` uses `IF NOT EXISTS`, the two paths are idempotent
relative to each other. The first time Alembic runs against an
already-populated DB without an Alembic stamp it records `v1` in a
new `alembic_version` table without rewriting anything.

## CLI

The wrapped entry point auto-resolves DB paths from the active
runtime layout:

```sh
python -m magi.db upgrade [target] [revision]   # default revision: head
python -m magi.db downgrade <target> <revision>
python -m magi.db current [target]              # omit target = all envs
python -m magi.db history [target]
python -m magi.db revision <target> -m "describe change"
```

`target` is one of the registered `MIGRATION_TARGETS` names above. For
`upgrade`, `current`, and `history`, omitting `target` runs the action
against every env in order. `revision` and `downgrade` always require
an explicit env.

Use the raw `alembic -c alembic.ini -n <env>` CLI only when you need
to point Alembic at a non-runtime DB file via `-x dburl=sqlite:///...`.
The `alembic.ini` at repo root only exposes `script_location` per
section; the wrapped CLI is what knows about runtime paths.

## Adding a schema change

The workflow for any change to a Tier-1 DB:

1. **Generate the revision file**

   ```sh
   python -m magi.db revision chat -m "add foo column to chat_messages"
   ```

   This creates an empty file under
   `db/migrations/chat/versions/<rev>_<slug>.py` populated by
   `script.py.mako`.

2. **Write the upgrade / downgrade**

   For additive changes use `op.add_column`, `op.create_index`,
   `op.create_table`. For SQLite-specific reshapes (drop column,
   change type, change NOT NULL) wrap the affected table in
   `op.batch_alter_table(...)` so Alembic does the
   create-new-table + copy + swap dance for you.

   ```python
   from alembic import op
   import sqlalchemy as sa

   revision = "0002_add_foo"
   down_revision = "v1"
   branch_labels = None
   depends_on = None

   def upgrade() -> None:
       op.add_column(
           "chat_messages",
           sa.Column("foo", sa.Text(), nullable=True),
       )
       op.create_index(
           "idx_chat_messages_foo",
           "chat_messages",
           ["foo"],
       )

   def downgrade() -> None:
       op.drop_index("idx_chat_messages_foo", table_name="chat_messages")
       op.drop_column("chat_messages", "foo")
   ```

3. **Update the store's baseline DDL to match.** The Tier-1 store's
   `CREATE TABLE IF NOT EXISTS` payload should always reflect the
   shape *after* head — fresh installs run the baseline directly
   before `upgrade head` stamps the version. Forgetting to keep the
   baseline in sync means fresh installs and migrated installs end up
   with different schemas. Treat baseline DDL and the revision as a
   pair.

4. **Verify locally**

   ```sh
   # apply against a fresh DB
   rm -f /tmp/magi-fresh-chat.db
   alembic -c backend/alembic.ini -n chat \
     -x dburl=sqlite:////tmp/magi-fresh-chat.db upgrade head

   # apply against a copy of an existing DB
   cp ~/.magi/data/chat/chat.db /tmp/chat-existing.db
   alembic -c backend/alembic.ini -n chat \
     -x dburl=sqlite:////tmp/chat-existing.db upgrade head

   # run the affected test surfaces
   cd backend && pytest tests/chat -q
   ```

5. **Commit the revision and the baseline change together.** Never
   land one without the other.

## Adding a new Tier-1 environment

If a Tier-2 DB needs to graduate (e.g. `behavior_evolution` starts
needing column-level migrations):

1. Add a new `MigrationTarget` to `MIGRATION_TARGETS` in
   `db/runner.py` mapping the env name to its `RuntimePaths` accessor.
2. Add `db/migrations/<name>/{__init__.py, env.py, script.py.mako,
   versions/__init__.py}` — copy from any existing env.
3. Add a `[<name>]` section to `backend/alembic.ini` pointing at the
   new `script_location`.
4. Add a `"magi.db.migrations.<name>" = ["script.py.mako"]` entry
   under `[tool.setuptools.package-data]` in
   `backend/pyproject.toml` so the template ships with the wheel.
5. Write `v1_initial.py` using the same shape as
   `db/migrations/chat/versions/v1_initial.py`: a SCHEMA_SQL string
   with `CREATE … IF NOT EXISTS` everywhere, a DROP_SQL string in
   reverse-dependency order, and `upgrade()` /  `downgrade()` calling
   `op.get_bind().connection.executescript(...)`. Copy the live
   baseline DDL verbatim — keep it idempotent so existing DBs upgrade
   cleanly.

## Conventions

- **Always use `IF NOT EXISTS`** in both the store baseline DDL and
  any 0001-initial-style revision. Only later revisions that add new
  objects to a known-stamped DB are allowed to omit it.
- **`*_at_ms`** for INTEGER millisecond timestamps;
  **`*_at`** without suffix for REAL Unix-second timestamps. Existing
  columns mix the two (chat uses `_at_ms`, L1 uses unsuffixed `_at`);
  follow whichever convention the table already uses.
- **JSON payloads** live in `_json` suffixed `TEXT` columns
  (`payload_json`, `metadata_json`, `ux_plan_json`, `label_json`).
  Default to `'{}'` on NOT NULL JSON columns.
- **Use soft deletion where the schema defines a lifecycle tombstone** through
  `_at_ms` (chat) or `deleted_at` (L1, L4). Governed chat transcript deletion is
  the deliberate exception: it first commits an inaccessible redacted state for
  crash recovery, then physically removes message and turn rows after strict
  trace and asset cleanup succeeds. Do not add any other hard-delete path
  without documenting its recovery and ownership boundary.
- **Indexes belong in the same revision** as the column they support.
  Don't split them.
- **Never write data migrations from old tables that no longer exist
  in the baseline.** Pre-release on-disk databases are not supported;
  when a column is removed, delete it cleanly instead of leaving
  backfill code behind.

## Background

The Alembic introduction landed in the run-up to the first public
release after a sweep that removed the previous generation of
hand-rolled `ensure_*_columns` helpers and `try/except ALTER TABLE`
idioms. The short version:

- Pre-release on-disk databases from earlier development builds are
  not supported. A clean release requires a fresh runtime directory.
- Every `ensure_*_columns` helper is gone; the columns it added are
  now part of the baseline `CREATE TABLE`.
- One-shot data migrations (legacy L1 → ChatStore, ToM legacy table
  rebuild, envelope-id retrofits) have been deleted along with their
  tests.
- Going forward, all schema deltas to Tier-1 DBs go through Alembic
  revisions; Tier-2 DBs continue to evolve their `CREATE TABLE`
  statements directly.

## External conversation threads

Channels revision `v3` keys session mappings by the connection-scoped channel,
external conversation and external thread. Existing conversation bindings migrate
to the unthreaded scope without changing session IDs, metadata or timestamps.
A thread reset deletes only that thread binding. Notification cursors remain
conversation-scoped. Downgrade requires a pre-migration snapshot because merging
independent thread histories would lose their identity.
### External message delivery ledger

Chat migration `v20_outbound_delivery` adds `chat_outbound_deliveries`, one immutable
intent per accepted message and concrete endpoint. The message owner inserts intents
inside its existing acceptance transaction. This is separate from incoming
`chat_user_turn_delivery` runtime admission and from the tool-effect ledger.

The storage port is `delivery.outbox.DeliveryOutbox`; its SQLite implementation
lives in `chat/storage/outbound_delivery.py`. Each record freezes content and target,
owns a lease token and expiry, and retains its per-target receipt. An expired lease
before provider invocation can be reclaimed. An expired in-flight attempt can be
retried only when provider idempotency was recorded before invocation; otherwise its
state becomes `uncertain`. A stale lease cannot settle a newer attempt. Chat clear
barriers fence claims, attempts and settlement, while message deletion cascades to
its outbox. Revision `v21_outbound_redaction` scrubs delivery content when a message
is hidden or replaced, cancels unsent work and marks in-flight work uncertain while
retaining successful receipts for external retraction. Message commits validate the
plan owner and roll back both the message and intents on any ownership mismatch.
The sender echoes the stable delivery ID and session in its receipt. Missing,
foreign or partial confirmations never become successful delivery records.

### Durable questions and first-answer arbitration

Runtime trace migration `v11` adds control-owned `control_asks`. The
`AskRepository` port owns persistence; its SQLite adapter owns serialization and
compare-and-set updates. Opening a new question cancels the previous pending
question in that session. Every accepted answer is committed before its broker
waiter is notified. A pending row can transition once, and invalid choices, empty
answers, expired requests and later device replies are rejected.

The broker remains a process-local wait mechanism. Startup cancels orphaned
questions (or expires overdue ones), because their suspended coroutines did not
survive the worker restart; closed answers remain inspectable. Permissions are
never persisted or restored as authorization. Session/history deletion clears the
control owner inside chat's deletion workflow, including recovery. Full user-content
clear deletes question content and fences stale replies before reopening admission.

Runtime trace migration `v12` adds `control_ask_deliveries`. Question opening commits
the explicit origin endpoint and formatted notification in the same transaction.
`control/persistence/` owns row mapping, question-state guards and lease updates;
`channels/ask_outbox.py` adapts that queue to the common `DeliveryWorker`. The bus
only wakes recovery, so missing an event cannot lose an accepted question notice.
The original answer deadline also bounds delivery, including time spent resolving
the route. Answer, timeout, replacement, restart recovery and clearing cancel unsent
work; an already invoked provider call can remain uncertain. Clear deletes question
content and cascades to its notification records. Physical tool effects and transient
permission prompts do not use this queue.

Memory shared revision `v59_timeline_cover_preferences` adopts the previously
runtime-created timeline preference table, preserving existing rows and adding an
asset-reference index. Cover and daily-mood repositories no longer create tables
as a fallback. Test composition uses migrations and injects repositories, just as
runtime composition does. Cover row conversion yields a typed domain record; HTTP
serialization remains the timeline service's responsibility.

Vector engine construction is centralized in `embedding/sqlite_factory.py`.
The shared structured-data clearer no longer creates vector adapters. The unified
clear coordinator invokes the configured factory under the existing exclusive
memory barrier, including dormant indexes, and requires cleanup to finish before
reporting success. SQLite vector cleanup truncates WAL and compacts every affected
index database, including files stored separately from structured memory. Normal
shutdown closes factory-owned resources after stopping layer workers.


Memory revision `v60_vector_projection_journal` owns remote vector namespaces,
collection generations, desired revisions, and publication operations. SQLite row
and JSON conversion lives in `embedding/sqlite_projection.py`; vector consumers
use typed contracts. Pending upserts include the vector payload until a matching
receipt commits. Replacement/deletion removes obsolete payloads and queues cleanup;
a late receipt cannot publish a different revision.

Memory backups exclude the complete remote projection journal. Restore staging
carries forward only the current center's content-free collection identities and
advances their generation; it never imports another center's pending writes or
remote addresses. This update is included in the staged file fingerprint and fsync
sequence, while the exact rollback database remains unchanged. Restored source
records rebuild new indexes, and recovery removes the center's retired remote
collections. Standalone vector databases remain derived caches outside the portable
memory archive.


Chat session creation, rename, workspace updates and labels have one mutation
owner in Python. The gateway authenticates and proxies these routes; it no longer
opens chat SQLite for writes. Creation and its idempotency receipt commit together,
return HTTP 201 on both first creation and retry, and return 409 if the retained
identity points at an archived/deleted session. Missing/foreign sessions return
404 for rename and workspace mutations. Storage unavailability is a service error,
never a successful response with an empty session ID.

Recent workspace choices use the chat-owned `RecentWorkspaceRepository` port.
The JSON adapter preserves the existing five-path file, validates persisted values,
serializes concurrent updates, and atomically replaces the private file. Both HTTP
methods are registered through the public Python router. Rust retains transport,
authentication and native file security, while chat owns serialization and mutation
semantics.

Native attachment downloads resolve a typed ownership record through authenticated
`chat.resolve_attachment` IPC. The chat owner joins the exact user, session, turn
and visible message; the gateway independently verifies the returned identity and
managed-file boundary before streaming ranges. It does not open `chat.db`.

Schedule execution history is served by the Python scheduler repository, including
recent and per-schedule endpoints. The gateway does not query scheduler tables.

LLM usage summary and time-series HTTP endpoints delegate to the Python usage
store, which owns aggregation, currency grouping and row conversion. Missing
runtime storage returns an unavailable response instead of fabricated zero usage.

Runtime overview combines native OS/readiness measurements with authenticated
`runtime.metrics` snapshots assembled from the usage, memory and scheduler owners.
The gateway contains no business-metric SQL. Memory layers count their own pending
embedding records (L1 uses numeric state in `l1_event_embedding_state`); scheduler
next-run times come from its authoritative job store. A failed owner is represented
as a null section and the UI displays unavailable, preserving other measured data.

The gateway notification bridge polls authenticated `runtime.notifications` IPC,
not `runtime_trace.db`. The owner reads the watermark and rows in one snapshot,
bounds both row count and payload size, decodes JSON and supplies authoritative
routing fields. Missing/rewound cursors and malformed/oversized payloads request a
snapshot resync. Worker generations, storage readiness and the maintenance gate
fence in-flight reads before events reach SSE. Gateway database access is enforced
to `auth/storage.rs`; the former business SQL/path helpers have been removed.

Manual image storage is injected as `ImageAssetRepository`; manual-entry workflows,
timeline reads, bootstrap slots and API upload/clear flows consume this port.
The local adapter owns reference parsing, MIME conversion, content digest validation,
size bounds and atomic durable files. Application calls use the asynchronous
`asset_io` boundary, which drains an in-flight blocking storage operation before
propagating cancellation so a memory-clear barrier cannot be released early.
New adapters implement the same byte/reference operations and are injected at
`ManualEntriesModule`; business services receive no filesystem paths. Source
visibility remains governed separately by memory and timeline reference owners.

Entity-link reads and projection publication use `MemoryEventRepository`. The
SQLite adapter owns manual/projected rows, atomic batch revision checks and the
durable clear-generation fence. A recreated repository rechecks the persisted
generation before publishing; a stale worker cannot repopulate cleared links.
Lexical query grammar and driver rows also belong to the adapter. Every lexical
candidate joins the current active event, even without a user/time filter, and
index backfill holds the source write transaction through publication. Search-text
construction is storage neutral and shared by ingestion and rebuild.

L1 embedding workers pass immutable source snapshots and typed publication records
to the event repository. Chunk rows, embedding profiles and completion status
commit in one transaction after rechecking the active source snapshot. A stale
publication or removal is ignored without modifying the current source. The
repository also owns rebuild pagination, chunk hydration and orphan visibility;
vector search ranks typed records and never sees SQL rows or source paths.

L1 initialization verifies the migration-owned schema; it no longer assembles or
executes a partial schema at runtime. Full clear deletes event facts, payloads,
previews, handoffs and projections and advances the entity-link fence in one
repository transaction. It preserves the database identity, migration version and
unrelated tables; derived vector indexes clear through their own port. In-flight
embedding work carries a local generation so a pre-clear result cannot publish
even if an identical event ID and text are ingested again.
Evidence reclassification scans a bounded high-water snapshot and publishes
conditional updates against the exact source record read. Deleted, replaced or
concurrently reclassified sources are skipped. Invalid stored rows are reported
as scan errors, and dry runs never persist annotations. Chat preview rebuilds
hold a write transaction from source read through publication.

The event adapter translates driver constraint and availability failures into the
shared persistence error contract after connection cleanup. This applies to side
records and maintenance as well as insertion. Lexical failures propagate as
unavailability instead of returning a misleading empty result; cancellation keeps
its cancellation semantics and still drains the underlying connection.

`L1EventStore` requires an injected event repository and vector factory and has no
database path or default SQLite implementation. `UnifiedMemoryStore` requires the
event repository whenever L1 is enabled and forwards it unchanged. The memory
lifecycle composition selects the adapter; standalone tests use explicit test
factories that prepare migrated databases. A pathless repository contract test
runs ingestion, reads and clear while rejecting any attempt to open SQLite.

### MySQL event repository

The L1 MySQL owner uses the `mysql_l1` migration chain and `magi_l1_*`
InnoDB tables. Event and idempotency identities are stored without truncation;
fixed-size SHA-256 keys provide indexed identity constraints. The owner state
row binds the tables to one logical center and serializes write transactions,
including session sequence allocation. Event insertion commits embedding state,
pinned content, source facets, chat previews and cognition handoffs together.
Repository initialization validates an already migrated schema; it never creates
tables. Storage selection must be performed at composition, after migration and
logical cutover validation. It must not silently switch from existing SQLite data.

MySQL event readers hold a shared owner-row lock for multi-query snapshots;
writers hold the exclusive lock. Evidence updates compare the complete source
record inside that transaction. Embedding publication verifies the current source
and atomically saves chunks, profile and completion state. Clear deletes owned
facts and all side records while advancing the entity-link fence, preserving the
center binding, schema version and other owners' tables. Pending cognition
handoffs and retry times remain durable across worker restarts.

MySQL manual entity links and L2 projections have separate ownership. Projected
batches compare revisions, lease identity and payload fingerprint before changing
any row, and check the durable generation after restart. Advancing a generation
removes only projected links. Physical event retirement selects tombstones inside
the write transaction before deleting side records, so mixed live/deleted input
cannot erase a live event's evidence or vector metadata.

The MySQL event adapter implements the complete `MemoryEventRepository` contract,
including facets, retention/evidence scans and lexical retrieval. Its lexical
index uses MySQL's ngram parser; rank values are normalized to the lower-is-better
repository convention, but scores are not numerically interchangeable with FTS5.
Strict English queries additionally enforce word boundaries. Every lexical or
facet candidate is checked against active source rows. A real MySQL + Chroma
contract test covers ingest, retrieval, rebuild, service recreation and clear;
a late remote vector cannot hydrate a source event that no longer exists.
