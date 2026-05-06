# Persistence & Migrations

Authoritative reference for how Magi stores data on disk and evolves
those schemas over time. If you are about to add a SQLite column,
create a new table, change an index, or reason about which database
file owns a piece of state — start here.

## Runtime SQLite layout

All runtime data is rooted under `RuntimePaths.base_dir`
(`~/.magi` by default; override with `MAGI_RUNTIME_DIR`). The runtime
keeps state across **fourteen** SQLite files, grouped by lifecycle
ownership:

| File | Owner | Holds |
|------|-------|-------|
| `data/chat/chat.db` | chat | sessions, turns, messages, attachments, context summaries |
| `data/memory/l1_events.db` | memory L1 + L1-projected chat sessions | normalized event log, embeddings, FTS, entity links |
| `data/memory/memory.db` | memory L0 / L2 / L3 / L4 | working memory, knowledge graph, ToM, summaries, procedural skills |
| `runtime/runtime_trace.db` | runtime trace | trace turns / spans / llm calls / tools, plugin ingress events |
| `runtime/llm_usage.db` | llm | per-request usage + cost telemetry |
| `data/app/persona_registry.db` | personality | personas, active persona |
| `data/memory/behavior_evolution.db` | personality | task interactions, category statistics, behavior profiles |
| `data/memory/emotional_state.db` | personality | emotional state KV + events |
| `data/memory/growth_memory.db` | personality | milestones, relationships, personality evolution |
| `runtime/scheduler.db` | scheduler | apscheduler job store |
| `runtime/message_queue.db` | runtime | runtime command queue |
| `runtime/sensor_state.db` | sensors | per-source sync state |
| `runtime/background_tasks.db` | runtime | background-task durability |
| `data/memory/self_memory_v2.db` | (reserved) | — |

Each subsystem owns the schema for its own file. There is no
cross-file foreign-key enforcement.

## Two tiers of schema management

### Tier 1 — Alembic-managed (six core DBs)

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
        0001_initial.py
    l1/...
    memory_shared/...
    runtime_trace/...
    llm_usage/...
    persona_registry/...
```

### Tier 2 — store-owned baseline (eight smaller DBs)

`behavior_evolution`, `emotional_state`, `growth_memory`, `scheduler`,
`message_queue`, `sensor_state`, `background_tasks`, `self_memory_v2`
keep their schema as `CREATE TABLE IF NOT EXISTS` blocks inside
their respective lifecycle modules. They are small, low-churn, and
rebuildable. **Add a new column there → just edit the lifecycle
module's DDL.** If a Tier-2 database starts seeing frequent or
non-additive changes, promote it to Tier 1 (add a `MigrationTarget`
in `db/runner.py`, add a `migrations/<name>/` folder, write
`0001_initial.py` mirroring an existing env, then move the DDL into
that revision).

## How migrations run

`CoreDependenciesModule.init` (in `backend/src/magi/core/lifecycle.py`)
calls `magi.db.run_upgrade_head(runtime_paths)` early in the
bootstrap sequence — before any store opens its connection. It
iterates `MIGRATION_TARGETS` and runs `alembic upgrade head` against
each. A failure aborts startup with a logged error.

Every store also keeps its own baseline `executescript(...)` of
`CREATE TABLE IF NOT EXISTS` statements as a fast path on fresh
installs. Because every CREATE in both the store baseline and
`0001_initial` uses `IF NOT EXISTS`, the two paths are idempotent
relative to each other. The first time Alembic runs against an
already-populated DB it simply stamps `0001_initial` into a new
`alembic_version` table without rewriting anything.

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

`target` is one of `chat`, `l1`, `memory_shared`, `runtime_trace`,
`llm_usage`, `persona_registry`. For `upgrade`, `current`, and
`history`, omitting `target` runs the action against every env in
order. `revision` and `downgrade` always require an explicit env.

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
   down_revision = "0001_initial"
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
   rm -rf /tmp/magi-fresh && MAGI_RUNTIME_DIR=/tmp/magi-fresh \
     python -m magi.db upgrade chat

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
5. Write `0001_initial.py` using the same shape as
   `db/migrations/chat/versions/0001_initial.py`: a SCHEMA_SQL string
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
- **Deletes are soft** wherever a `_at_ms` (chat) or `deleted_at`
  (L1, l4) column is present. Don't add hard `DELETE` paths to those
  tables without a discussion.
- **Indexes belong in the same revision** as the column they support.
  Don't split them.
- **Never write data migrations from old tables that no longer exist
  in the baseline.** Pre-release on-disk databases are not supported;
  when a column is removed, delete it cleanly instead of leaving
  backfill code behind (see `docs/cleanup-audit/` for the rationale).

## Background

The Alembic introduction landed in the run-up to the first public
release after a sweep that removed the previous generation of
hand-rolled `ensure_*_columns` helpers and `try/except ALTER TABLE`
idioms. The audit reports under `docs/cleanup-audit/` document what
was removed and why. The short version:

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
