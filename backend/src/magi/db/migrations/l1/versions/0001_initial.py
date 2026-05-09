"""l1 baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06

Materialises the canonical L1 event-store schema (fact_events,
embedding_profiles, l1_event_chunks, l1_events_fts, l1_event_entities)
plus the canonical chat_sessions projection table that lives in the
same database. This revision is the snapshot of the schema as it
stood the day Alembic took ownership; any further evolution is a
new revision file.
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fact_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,
    idempotency_key TEXT,
    memory_domain INTEGER NOT NULL,
    ingest_target INTEGER NOT NULL,
    cognition_eligible INTEGER NOT NULL DEFAULT 0,
    tom_depth INTEGER NOT NULL DEFAULT 1,
    retention_class INTEGER NOT NULL DEFAULT 2,
    session_id TEXT,
    turn_id TEXT,
    user_id TEXT,
    task_id TEXT,
    content TEXT NOT NULL,
    author_type TEXT NOT NULL,
    content_type TEXT NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    level INTEGER NOT NULL DEFAULT 1,
    media_path TEXT,
    metadata_json TEXT,
    embedding_status TEXT NOT NULL DEFAULT 'disabled',
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    causation_id TEXT,
    trace_id TEXT,
    span_id TEXT,
    parent_span_id TEXT,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_fact_events_timestamp ON fact_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_fact_events_type ON fact_events(event_type);
CREATE INDEX IF NOT EXISTS idx_fact_events_source ON fact_events(source);
CREATE INDEX IF NOT EXISTS idx_fact_events_idempotency_key ON fact_events(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_fact_events_domain ON fact_events(memory_domain);
CREATE INDEX IF NOT EXISTS idx_fact_events_session ON fact_events(session_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_turn ON fact_events(turn_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_user ON fact_events(user_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_importance ON fact_events(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_fact_events_retention ON fact_events(retention_class);
CREATE INDEX IF NOT EXISTS idx_fact_events_trace ON fact_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_causation ON fact_events(causation_id);
CREATE INDEX IF NOT EXISTS idx_fact_events_embedding_status ON fact_events(embedding_status);
CREATE INDEX IF NOT EXISTS idx_fact_events_embedding_profile ON fact_events(embedding_profile_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency
    ON fact_events(source, event_type, idempotency_key);

CREATE TABLE IF NOT EXISTS embedding_profiles (
    profile_id TEXT PRIMARY KEY,
    provider_name TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding_dim INTEGER,
    text_builder_version TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l1_event_chunks (
    chunk_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    token_estimate INTEGER NOT NULL,
    embedding_profile_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_l1_event_chunks_event ON l1_event_chunks(event_id, chunk_index);

CREATE VIRTUAL TABLE IF NOT EXISTS l1_events_fts USING fts5(
    event_id UNINDEXED,
    content,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS l1_event_entities (
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT,
    confidence REAL,
    created_at REAL NOT NULL,
    UNIQUE(event_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_l1_event_entities_entity
    ON l1_event_entities(entity_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    title_overridden INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_message_at REAL,
    last_user_message_at REAL,
    last_message_preview TEXT NOT NULL DEFAULT '',
    last_user_message_preview TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    workspace_path TEXT,
    archived_at REAL,
    deleted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions(user_id, deleted_at, archived_at, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_last_message
    ON chat_sessions(user_id, last_message_at DESC);
"""

DROP_SQL = """
DROP TABLE IF EXISTS chat_sessions;
DROP TABLE IF EXISTS l1_event_entities;
DROP TABLE IF EXISTS l1_events_fts;
DROP TABLE IF EXISTS l1_event_chunks;
DROP TABLE IF EXISTS embedding_profiles;
DROP TABLE IF EXISTS fact_events;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
