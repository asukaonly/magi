"""SQLite schema constants for L3 summary storage.

Schema is owned by alembic (``magi.db.migrations.memory_shared``); this
module only re-exports table names and helper constants.
"""
from __future__ import annotations

import aiosqlite

SUMMARY_CHUNKS_TABLE = "l3_summary_chunks"
EMBEDDING_STATUS_READY = "ready"
EMBEDDING_STATUS_DISABLED = "disabled"

L3_SUMMARY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS summaries (
	summary_id TEXT PRIMARY KEY,
	summary_type TEXT NOT NULL,
	summary_category TEXT NOT NULL,
	period_start REAL NOT NULL,
	period_end REAL NOT NULL,
	content TEXT NOT NULL,
	key_topics TEXT,
	key_entities TEXT,
	sentiment_summary TEXT,
	change_and_pattern TEXT,
	source_event_ids TEXT NOT NULL,
	source_event_count INTEGER NOT NULL,
	importance_aggregate REAL,
	event_type_distribution TEXT,
	generated_by_model TEXT,
	generation_prompt TEXT,
	generation_reason TEXT,
	insight_key TEXT,
	review_state TEXT,
	insight_metadata TEXT,
	narrative_style TEXT NOT NULL DEFAULT 'default',
	essence_prose TEXT,
	embedding_status TEXT NOT NULL DEFAULT 'disabled',
	embedding_profile_id TEXT,
	embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
	last_embedded_at REAL,
	source_revision INTEGER NOT NULL DEFAULT 0,
	derivation_state TEXT NOT NULL DEFAULT 'current'
		CHECK(derivation_state IN ('current', 'stale', 'retired')),
	created_at REAL NOT NULL,
	updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_summaries_period
	ON summaries(summary_type, summary_category, period_start, period_end);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_insight_key
	ON summaries(insight_key) WHERE insight_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_summaries_narrative_style
	ON summaries(narrative_style, summary_type, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_derivation_state
	ON summaries(derivation_state, summary_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS summary_event_links (
	link_id TEXT PRIMARY KEY,
	summary_id TEXT NOT NULL,
	event_id TEXT NOT NULL,
	link_role TEXT NOT NULL,
	evidence_weight REAL NOT NULL DEFAULT 1.0,
	created_at REAL NOT NULL,
	UNIQUE(summary_id, event_id, link_role)
);
CREATE INDEX IF NOT EXISTS idx_summary_event_links_event
	ON summary_event_links(event_id);

CREATE TABLE IF NOT EXISTS summary_task_links (
	link_id TEXT PRIMARY KEY,
	summary_id TEXT NOT NULL,
	task_id TEXT NOT NULL,
	link_role TEXT NOT NULL,
	created_at REAL NOT NULL,
	UNIQUE(summary_id, task_id, link_role)
);
CREATE INDEX IF NOT EXISTS idx_summary_task_links_task
	ON summary_task_links(task_id);

CREATE TABLE IF NOT EXISTS l3_summary_chunks (
	chunk_id TEXT PRIMARY KEY,
	summary_id TEXT NOT NULL,
	chunk_index INTEGER NOT NULL,
	chunk_text TEXT NOT NULL,
	char_start INTEGER NOT NULL,
	char_end INTEGER NOT NULL,
	token_estimate INTEGER NOT NULL,
	created_at REAL NOT NULL,
	updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l3_summary_chunks_index
	ON l3_summary_chunks(summary_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS l3_summaries_fts USING fts5(
	summary_id UNINDEXED,
	content,
	tokenize='unicode61'
);
"""


async def ensure_l3_summary_schema(db: aiosqlite.Connection) -> None:
	await db.executescript(L3_SUMMARY_SCHEMA_SQL)
