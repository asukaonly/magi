# DB schema compatibility audit (pre-release cleanup)

Audit date: 2026-05-06
Scope: backend/, crates/, contracts/, sdk/, scripts/, plugins/

## Top-level findings

- The repo uses **no formal migration framework** (no alembic / sqlx / diesel migration dirs). Every SQLite store keeps its own `CREATE TABLE IF NOT EXISTS` baseline plus a hand-written list of `ALTER TABLE ... ADD COLUMN` statements guarded by `PRAGMA table_info(...)` lookups. There are 110 ALTER TABLE call sites and 118 `CREATE INDEX IF NOT EXISTS` sites in `backend/src`.
- The compat code is overwhelmingly **additive backfill** for columns that have **already been merged into the baseline `CREATE TABLE`**. For a clean release that drops support for pre-release on-disk DBs, almost all of it can be deleted: the baseline `CREATE TABLE` already declares the column, so the `ADD COLUMN` branches are dead on a fresh DB.
- A few items go beyond simple `ADD COLUMN` (table rebuilds, data backfills, dual schemas) and are called out individually with a stronger recommendation.
- One large blob of code (`backend/src/magi/chat/migration.py`) is a **legacy L1 -> chat store backfill**. This should be deleted entirely for a clean release.

Recommendation summary:
- DELETE: 7 files / blocks (legacy backfills, duplicate-schema files, table rebuilds for old DBs).
- CONSOLIDATE: 14 schema files where `ensure_*_columns` helpers can be dropped because the columns are in the baseline `CREATE TABLE`.
- KEEP: indexes intentionally kept idempotent at startup (`crates/magi-gateway/src/db.rs::ensure_indexes`).

---

## Group A: Chat store schema (write + read)

Two files maintain near-identical chat schemas with the same migration ladder.

### A1. `backend/src/magi/chat/storage/schema.py:126-204`
- `ensure_chat_store_schema` calls four helpers: `ensure_chat_turn_columns` (lines 134-149), `ensure_chat_session_columns` (lines 152-161), `ensure_chat_message_columns` (lines 164-173), `ensure_chat_context_summary_columns` (lines 176-204).
- All target columns (`run_id`, `run_revision`, `run_disposition`, `response_anchor_turn_id`, `superseded_by_turn_id`, `supersession_reason`, `history_version`, `workspace_path`, `reply_to_message_id`, `label_json`, `persona_id`, plus all 18 `chat_context_summaries` columns) are **already in the baseline `CREATE TABLE`** at lines 7-122.
- Recommendation: **CONSOLIDATE / DELETE** the four `ensure_*_columns` helpers and the calls in `ensure_chat_store_schema`. The baseline DDL covers a fresh install.

### A2. `backend/src/magi/chat/read/schema.py:107-170`
- Read-side mirror of A1 with identical migration ladder for the same tables (sync sqlite3 API).
- Recommendation: **CONSOLIDATE / DELETE** the entire post-`executescript` block (lines 109-170). Baseline at lines 13-103 already has the columns.

### A3. `backend/src/magi/chat/migration.py` (whole file)
- `backfill_chat_store_from_legacy` reads from the legacy L1 `fact_events` + old `chat_sessions` tables (with second-precision `created_at`/`last_message_at`) and writes ms-precision rows into the new chat store.
- Wired in `backend/src/magi/chat/lifecycle.py:8,30-33` only when `chat_store.is_empty()`.
- Recommendation: **DELETE** the file plus the import/call in `chat/lifecycle.py:8,29-33`. This is a one-shot pre-release migration from a column-renamed (`*_at` -> `*_at_ms`) ancestor schema; not needed for a clean release.

### A4. `backend/src/magi/memory/l1/chat_sessions.py:60-70`
- `ensure_chat_sessions_schema_async` adds `workspace_path` if missing; column is in baseline at line 27.
- Recommendation: **CONSOLIDATE** — drop the `PRAGMA + ALTER` block, keep the `executescript`.

---

## Group B: Runtime trace store

### B1. `backend/src/magi/runtime_trace/schema.py:157-189`
- `ensure_trace_turn_columns` (lines 164-175) adds `continued_from_turn_id`, `continued_from_trace_id`, `superseded_by_turn_id`, `supersession_reason`. All four are in the baseline `trace_turns` definition at lines 23-26.
- `ensure_trace_detail_columns` (lines 178-189) adds `thinking_content` to `trace_llm_calls` and `result_json` to `trace_tools`. **Note: neither column appears in the baseline `CREATE TABLE` at lines 75-89 or 93-105.** These migrations are the only way the columns get created. Either the baseline must be updated or the migrations kept.
- Recommendation:
  - **CONSOLIDATE**: delete `ensure_trace_turn_columns` and its call site.
  - **CONSOLIDATE**: add `thinking_content TEXT` to `trace_llm_calls` baseline and `result_json TEXT` to `trace_tools` baseline, then delete `ensure_trace_detail_columns`.

### B2. `backend/src/magi/runtime_trace/schema.py:192-240`
- `_ensure_trace_spans_turn_id_nullable` does a full table rebuild to drop NOT NULL on `trace_spans.turn_id`. The baseline at line 38 already declares `turn_id TEXT` (nullable).
- Recommendation: **DELETE** — only relevant if a pre-release DB has the old NOT NULL definition.

---

## Group C: L2 cognition store

### C1. `backend/src/magi/memory/l2/storage/migrations.py` (whole file)
- `_ensure_knowledge_graph_columns` (lines 11-38): adds 9 additive columns to `knowledge_graph`. All present in baseline at `l2/storage/schema.py`.
- `_ensure_tom_assertion_schema` (lines 40-175): branching path; either appends ~9 columns + index recreation, or **renames the table to `_legacy` and reinserts with trait_family/temporal_scope CASE-mapping** (lines 138-245). Heavy backfill code for an old assertion shape.
- `_recreate_assertions_without_unique` (lines 247-304): rebuilds `tom_trait_assertions` to drop a stale UNIQUE constraint.
- `_ensure_tom_snapshot_schema` (lines 306-324): adds 8 additive columns to `tom_snapshots`.
- Recommendation: **DELETE the file**. All columns/indexes are now in the baseline `l2/storage/schema.py`. The `tom_trait_assertions_legacy` rebuild and the unique-constraint recreation only matter for pre-baseline DBs.
- Caller in `backend/src/magi/memory/l2/store.py` (the mixin); remove the four method calls together.

### C2. `backend/src/magi/memory/l2/projection/queue.py:38-56`
- `ensure_schema` adds `catch_up_owner`, `max_events`, `min_ready_events`, `max_wait_seconds`, `started_at`. Verify these are in the baseline `l2_projection_jobs` table (`l2/storage/schema.py:126-150`); if so, **CONSOLIDATE** — delete the helper.

### C3. `backend/src/magi/memory/l2/entities/facets.py:187-200`
- `_ensure_entity_facet_columns` adds `status` and `privacy_scope` to `entity_facets`. Baseline `entity_facets` schema is in `l2/storage/schema.py:30-`.
- Recommendation: **CONSOLIDATE** — confirm baseline, drop helper.

---

## Group D: L1 event store

### D1. `backend/src/magi/memory/l1/storage/schema.py` (whole mixin)
- `_ensure_embedding_status_columns` (16-32): adds 4 embedding columns.
- `_ensure_metadata_json_column` (34-38): adds `metadata_json`.
- `_backfill_external_owner_user_ids` (40-51): UPDATE backfill: sets `user_id = DEFAULT_USER_ID` for legacy external rows where `user_id IS NULL`.
- `_ensure_event_identity_schema` (53-166): full table rebuild migration that introduces `id INTEGER PK AUTOINCREMENT` + `idempotency_key` and copies all rows; only triggered if old table lacks the new identity columns.
- `_ensure_envelope_columns` (168-181): adds 4 envelope columns (`causation_id`, `trace_id`, `span_id`, `parent_span_id`) plus two indexes.
- Recommendation:
  - **DELETE** `_ensure_event_identity_schema` (lines 53-166): heavy table rebuild for very old DBs. Tested by `backend/tests/memory/l1/test_envelope_migration.py` — that test should also be removed/rewritten.
  - **DELETE** `_backfill_external_owner_user_ids` (40-51): one-shot data fix.
  - **CONSOLIDATE** the three `_ensure_*_columns` helpers into the baseline `fact_events` `CREATE TABLE`.

### D2. `backend/tests/memory/l1/test_envelope_migration.py` and `backend/tests/runtime_trace/test_envelope_migration.py`
- These tests exist solely to verify the legacy-to-current migration paths in D1/B1.
- Recommendation: **DELETE** alongside the migration code.

### D3. `backend/tests/chat/test_chat_migration.py`
- Verifies `backfill_chat_store_from_legacy`. Delete with A3.

---

## Group E: Memory L0 / L3 / L4

### E1. `backend/src/magi/memory/l0/working/schema.py:107-139`
- `ensure_execution_run_columns` adds `cancel_*` columns; `ensure_execution_pending_turn_columns` adds `disposition`. All present in baseline (lines 58-83).
- Recommendation: **CONSOLIDATE / DELETE** both helpers and calls.

### E2. `backend/src/magi/memory/l3/storage/schema.py:86-103`
- `_ensure_summary_insight_columns` adds `insight_key`, `review_state`, `insight_metadata`. Baseline already has them at lines 29-31.
- Recommendation: **CONSOLIDATE** — delete the helper and call.

### E3. `backend/src/magi/memory/l4/storage/schema.py:90-114`
- `ensure_procedural_memory_schema` runs three `ALTER TABLE ... ADD COLUMN` wrapped in **bare `try/except: pass`** to swallow `duplicate column` errors. Columns: `pending_trace_count`, `turn_id`, `deleted_at`. **Note: only `pending_trace_count` is in the baseline at line 33-style; `turn_id` and `deleted_at` are NOT in baseline definitions (lines 73-85, 17-50).** The implicit-exception pattern means the baseline relies on these to add new columns to fresh DBs as well as old ones.
- Recommendation: **CONSOLIDATE** — add `turn_id TEXT` to baseline `l4_execution_traces`, add `deleted_at REAL` to baseline `procedural_skills`, delete the three try/except blocks. Keep `TRACE_TURN_INDEX_SQL` (it's just `CREATE INDEX IF NOT EXISTS`).

---

## Group F: LLM usage store

### F1. `backend/src/magi/llm/usage_store.py:26-78`
- `_ensure_optional_columns` adds `ttft_ms` and `cost_usd`. Baseline already has both at lines 42-43.
- Recommendation: **CONSOLIDATE** — delete the helper.

### F2. `backend/src/magi/core/database_initializer.py:293-328`
- `_init_llm_usage_db` defines `llm_usage` with an **OLDER schema** (no `ttft_ms`, no `cost_usd`) than the canonical `LLMUsageStore` definition. This is dead/divergent compat code: the actual store rebuilds the schema correctly via `usage_store.py`.
- Recommendation: **DELETE** the `_init_llm_usage_db` method and its call site, OR sync it with `usage_store.py`. Same likely applies to other `_init_*` methods in this file (personality, growth, behavior); they overlap with the schema files in `personality/` and `memory/`.

---

## Group G: Personality / behavior databases

### G1. `backend/src/magi/personality/persona_repository.py:102-121`
- Adds `description` (with **JSON-extracting backfill**, lines 110-118) and `deleted_at` columns to `personas`.
- Recommendation:
  - **DELETE** the JSON backfill loop (110-118) — it imports from `config_json` for pre-release rows.
  - **CONSOLIDATE** the two `ADD COLUMN` calls into the baseline `_CREATE_SCHEMA`.

### G2. `backend/src/magi/personality/behavior_evolution_schema.py:64-68`
- Loops three tables and `ALTER TABLE ... ADD COLUMN persona_id` inside bare `try/except: pass`. All three baseline `CREATE TABLE` blocks already declare `persona_id TEXT NOT NULL DEFAULT ''`.
- Recommendation: **DELETE** the loop (lines 64-68).

### G3. `backend/src/magi/personality/emotional_storage.py:59-62`
- Same pattern: `ALTER TABLE emotional_events ADD COLUMN persona_id` in `try/except: pass`. Baseline at line 55 already has it.
- Recommendation: **DELETE** the try block.

### G4. `backend/src/magi/personality/growth_schema.py:37-41`
- Same pattern for `milestones` and `relationships`. Baseline already declares `persona_id`.
- Recommendation: **DELETE** the loop.

---

## Group H: Gateway / Rust

### H1. `crates/magi-gateway/src/db.rs:188-218` (`ensure_indexes`)
- Idempotent `CREATE INDEX IF NOT EXISTS` only — no schema mutation, no column compat. Documented as "called once at startup".
- Recommendation: **KEEP**. These are perf indexes the gateway adds defensively; cheap and idempotent.

---

## Files / blocks to delete vs. consolidate (consolidated list)

DELETE:
- `backend/src/magi/chat/migration.py` (whole file) + caller in `backend/src/magi/chat/lifecycle.py:8,29-33`.
- `backend/tests/chat/test_chat_migration.py`.
- `backend/src/magi/memory/l2/storage/migrations.py` (whole file) + mixin calls in `memory/l2/store.py`.
- `backend/src/magi/memory/l1/storage/schema.py::_ensure_event_identity_schema` (lines 53-166) and `_backfill_external_owner_user_ids` (40-51).
- `backend/tests/memory/l1/test_envelope_migration.py`, `backend/tests/runtime_trace/test_envelope_migration.py`.
- `backend/src/magi/runtime_trace/schema.py::_ensure_trace_spans_turn_id_nullable` (lines 192-240).
- `backend/src/magi/personality/persona_repository.py:110-118` (JSON-derived `description` backfill).
- `backend/src/magi/personality/behavior_evolution_schema.py:64-68`, `emotional_storage.py:59-62`, `growth_schema.py:37-41` (all bare `try/except` `ADD COLUMN persona_id`).
- `backend/src/magi/core/database_initializer.py::_init_llm_usage_db` (lines 293-328) — duplicate, divergent schema.

CONSOLIDATE (move column into baseline `CREATE TABLE`, then delete the `ensure_*_columns` helper + its call):
- `backend/src/magi/chat/storage/schema.py:126-204` (4 helpers).
- `backend/src/magi/chat/read/schema.py:107-170`.
- `backend/src/magi/memory/l1/chat_sessions.py:60-70`.
- `backend/src/magi/runtime_trace/schema.py:157-189` (turn + detail helpers; also add the missing `thinking_content` / `result_json` columns to baseline DDL).
- `backend/src/magi/memory/l0/working/schema.py:107-139`.
- `backend/src/magi/memory/l3/storage/schema.py:86-103`.
- `backend/src/magi/memory/l4/storage/schema.py:90-114` (also add `turn_id` and `deleted_at` to the baseline DDL).
- `backend/src/magi/memory/l2/projection/queue.py:38-56` (verify baseline coverage first).
- `backend/src/magi/memory/l2/entities/facets.py:187-200` (verify baseline coverage first).
- `backend/src/magi/llm/usage_store.py:65-78`.
- `backend/src/magi/personality/persona_repository.py:108-121` (the two `ADD COLUMN` calls themselves; baseline `_CREATE_SCHEMA` should declare `description`/`deleted_at`).

KEEP:
- `crates/magi-gateway/src/db.rs:188-218` — idempotent index ensure.
- All baseline `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` statements (these are the fresh-install schema, not compat).

---

## Notes / caveats

- Before consolidating each group, confirm the baseline `CREATE TABLE` is in fact a strict superset of what the helpers add (this audit spot-checked the obvious ones; mechanical verification recommended).
- After deletion, on-disk DBs from earlier development builds will silently fail to upgrade. Document that a clean release requires deleting `~/.magi/runtime/*.db` (or whichever runtime path applies). The release notes should call this out.
- `_ensure_event_identity_schema` and `_ensure_tom_assertion_schema` are the two heaviest pieces; deleting them is the largest LoC win.
- `backend/src/magi/core/database_initializer.py` more broadly looks like dead duplicate-init code: each subsystem owns its own `ensure_*_schema`. Worth a follow-up audit beyond schema-compat scope.
