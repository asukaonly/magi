# Persistence & Migrations

Authoritative reference for how Magi stores data on disk and evolves
those schemas over time. If you are about to add a SQLite column,
create a new table, change an index, or reason about which database
file owns a piece of state — start here.

## Runtime SQLite layout

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

Startup rejects a runtime root or descendant that is a symbolic link, Windows
reparse point, externally hard-linked file, or an entry owned by another
account. It fails before normal runtime startup instead of following the entry
or weakening an external target. This policy applies only to the Magi-owned
runtime root. User-selected workspaces, repositories, photo libraries, and
other external source directories are never traversed or modified by it.

Desktop gateway session credentials and private-resource tickets are deliberately
absent from this layout. They exist only in process memory, expire with the
gateway process, and must not enter SQLite, YAML configuration, logs, backups,
chat payloads, memory records, or plugin state.

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
| `data/chat/chat.db` | chat | sessions, session-creation idempotency mappings, turns, messages, attachments, per-turn context-usage snapshots, canonical message-to-asset and message-to-code-delegation ownership, private attachment/code-delegation cleanup registries, context summaries, user-turn delivery checkpoints, retryable assistant-memory projection intents, interrupted global-clear intent, permanent cleared-session and cleared-message scopes |
| `data/memory/l1_events.db` | memory L1 + L1-projected chat sessions | normalized event log, embeddings, FTS, entity links |
| `data/memory/memory.db` | memory L0 / L2 / L3 / L4 | short-term attention checkpoints, grounded Claim/evidence/entity-reference ledgers, exact L2 projection attempts and outcomes, knowledge graph, ToM, correction history, stable context identities, summaries, procedural skills |
| `runtime/runtime_trace.db` | runtime trace | trace turns / spans / llm calls / tools, plugin ingress events |
| `runtime/llm_usage.db` | llm | per-request usage + cost telemetry, daily rollups |
| `data/app/persona_registry.db` | personality | personas, active persona, source-linked reference dossiers for generated personas |
| `data/memory/behavior_evolution.db` | personality | task interactions, category statistics, behavior profiles |
| `data/memory/emotional_state.db` | personality | emotional state KV + events |
| `data/memory/growth_memory.db` | personality | milestones, relationships, personality evolution |
| `runtime/scheduler.db` | scheduler | schedules, execution history, sensor sync jobs |
| `runtime/bootstrap_state.db` | bootstrap | completed revisions, content fingerprints, attempts, and errors for versioned startup work |
| `runtime/message_queue.db` | runtime | runtime command queue, stable user-turn deduplication, command rollups, plugin/sensor full-clear checkpoint, pending desktop full-clear transaction |
| `runtime/sensor_state.db` | sensors | per-source cursors, fingerprints, stats |
| `runtime/background_tasks.db` | runtime | background-task rows and event history, plus recoverable terminal-completion snapshots with frozen outreach intent/body |
| `runtime/permission_rules.db` | runtime permissions | trust and permission rule state |
| `data/channels/channels.db` | channels + outreach | external channel session mappings, binding preferences, delivery receipts, notification cursors, proactive-outreach outbox and delivery log |
| `data/identity/identity.db` | identity | external channel identity to canonical user mapping |
| `data/batch/batch.db` | batch | batch job and item manifests |
| `data/memory/self_memory_v2.db` | (reserved) | — |

### Versioned startup work

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

Sensor pagination is part of scheduler truth. When a completed sensor batch
reports more source data, `scheduler.db` records the parent success and admits
the next queued job plus execution row in one transaction. A failed
continuation insert rolls back the parent success instead of leaving a
successful record with unqueued source data.

A destructive full clear treats scheduler configuration and scheduler content
differently. It preserves system-owned schedules and each source's cursor,
watermark, and binding, while deleting user-created agent schedules, their
runtime jobs and target state, every execution-history row, and every queued or
running sensor-sync job. Remaining target state keeps progress fields but loses
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

The desktop host coordinates crash recovery with
`runtime/full-data-clear.pending.json`. This is not user content and contains no
path, credential, prompt, or payload: only a marker version and an opaque,
unique, content-free transaction ID. The file is atomically replaced and
synced before destructive work begins. A single valid transaction-named
temporary file is recoverable after an interrupted write even when its payload
is incomplete; invalid names, multiple candidates, and filename/payload
conflicts fail closed. `runtime_full_user_content_clear_state` in `message_queue.db`
records that same ID only while the backend phase is pending. Startup adopts
the host ID before recovering queue claims, restarting an already running
backend when necessary. A pending backend row without the matching host marker
fails startup. A successful backend phase securely returns the singleton row
to `idle`, clears the ID and start time, and truncates the WAL; there is no
retained backend completion journal. The host marker stays until browser-owned
state and desktop logs are also clean, so a crash or ambiguous response replays
the complete idempotent clear.

Plugin- and sensor-owned user content uses the same full-clear generation stored
by the runtime command queue. `runtime_plugin_user_content_clear_state` records
only the latest generation whose plugin/sensor hooks may be treated as applied;
it is not the global clear completion record and does not create a second
generation stream. It advances only at the surrounding clear's success edge.
The checkpoint remains behind when any hook fails, the clear
is cancelled, a later global clearer or diagnostic-log erasure fails, or sensor
collection cannot be resumed safely. Collection is started in a non-claiming
paused state before the checkpoint write and released only after that write
succeeds. Startup detects a pending shared generation after plugins load and
fails closed before collection or other plugin ingress starts; plugin-only
replay is not allowed to claim completion for the cross-store clear.
Configuration, credentials,
connected-account state, and sensor cursor/watermark are intentionally retained;
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
orchestration payloads outside `chat.db`. The intent is deleted only after
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
conversation state and orchestration payloads, and then asks chat to complete
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

A DEFER message remains non-terminal while it is attached to another active
run. Exact completion of that run captures the deferred entry and clears the
run before the message is prepared as a higher delivery attempt. Its durable
runtime envelope and stable turn ID are reused. A transient completion
release failure retains one in-process retry for the captured batch. A failure
before scheduling leaves admitted or ready ledger work for startup or
background recovery rather than relying on an L0 execution checkpoint.

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
| `sensor_state` | `sensor_state.db` |
| `background_tasks` | `background_tasks.db` |
| `message_queue` | `message_queue.db` |
| `permission_rules` | `permission_rules.db` |
| `channels` | `channels.db` |
| `identity` | `identity.db` |
| `batch` | `batch.db` |

Current heads that matter to the chat-clear, memory-projection, and delivery boundaries:

| environment | head | Boundary added at head |
|-------------|------|------------------------|
| `chat` | `v11` | accepted visible-turn context usage stored with chat truth |
| `background_tasks` | `v2` | recoverable terminal-completion snapshots with durable delivery claims, frozen intent/body, and scoped discard during conversation deletion |
| `channels` | `v2` | stable proactive-outreach identity and due-work indexes |
| `message_queue` | `v7` | pending desktop full-clear transaction adopted before command recovery; success returns to an empty idle row |
| `memory_shared` | `v48_history_import_l2_reimport` | release stale L2 queue and event-rule identities only for durable explicit history reimports, then make any affected active import ledger resumable |

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
| `runtime_trace.db` | delete raw traces, notifications, and terminal plugin ingress rows older than 7 days |
| `llm_usage.db` | roll up expired raw rows by day, then delete raw rows older than 7 days |
| `message_queue.db` | roll up completed rows by hour, delete completed rows older than 24 hours, delete failed rows older than 7 days |
| `scheduler.db` | delete success history after 30 days and failed history after 60 days |
| `sensor_state.db` | keep only the latest configured fingerprint count per sensor |
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
