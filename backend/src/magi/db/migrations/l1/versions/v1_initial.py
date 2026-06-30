"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fact_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    source_item_id TEXT,
    idempotency_key TEXT,
    memory_domain INTEGER NOT NULL,
    cognition_eligible INTEGER NOT NULL DEFAULT 0,
    retention_class INTEGER NOT NULL DEFAULT 2,
    session_id TEXT,
    turn_id TEXT,
    session_seq INTEGER,
    user_id TEXT,
    content TEXT NOT NULL,
    author_type INTEGER NOT NULL,
    content_type INTEGER NOT NULL,
    importance_score REAL NOT NULL DEFAULT 0.5,
    media_path TEXT,
    metadata_json TEXT,
    deleted_at REAL,
    evidence_status INTEGER NOT NULL DEFAULT 1,
    evidence_class INTEGER NOT NULL DEFAULT 1,
    evidence_rule_version INTEGER NOT NULL DEFAULT 1,
    l1_retrieval_scope INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS l1_session_sequences (
    session_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS l1_event_embedding_state (
    event_id TEXT PRIMARY KEY,
    embedding_status INTEGER NOT NULL DEFAULT 1,
    embedding_profile_id TEXT,
    embedding_chunk_count INTEGER NOT NULL DEFAULT 0,
    last_embedded_at REAL,
    updated_at REAL NOT NULL
);

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

CREATE TABLE IF NOT EXISTS l1_event_payload (
    event_id   TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS l1_source_facets (
    event_id TEXT NOT NULL,
    source TEXT NOT NULL,
    facet_name TEXT NOT NULL,
    text_value TEXT,
    normalized_text_value TEXT,
    numeric_value REAL,
    timestamp_value REAL,
    json_value TEXT,
    created_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
    FOREIGN KEY(event_id) REFERENCES fact_events(event_id) ON DELETE CASCADE
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

CREATE INDEX IF NOT EXISTS idx_fact_events_evidence_status ON fact_events(evidence_status);

CREATE INDEX IF NOT EXISTS idx_fact_events_evidence_class ON fact_events(evidence_class);

CREATE INDEX IF NOT EXISTS idx_fact_events_l1_retrieval_scope
    ON fact_events(l1_retrieval_scope, user_id, timestamp DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fact_events_business_idempotency
    ON fact_events(source, event_type, idempotency_key);

CREATE INDEX IF NOT EXISTS idx_l1_event_embedding_state_status
    ON l1_event_embedding_state(embedding_status);

CREATE INDEX IF NOT EXISTS idx_l1_event_embedding_state_profile
    ON l1_event_embedding_state(embedding_profile_id);

CREATE INDEX IF NOT EXISTS idx_l1_event_chunks_event ON l1_event_chunks(event_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_l1_event_entities_entity
    ON l1_event_entities(entity_id);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions(user_id, deleted_at, archived_at, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_last_message
    ON chat_sessions(user_id, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_l1_event_payload_created_at
    ON l1_event_payload(created_at);

CREATE INDEX IF NOT EXISTS idx_fact_events_session_seq
    ON fact_events(session_id, session_seq);

CREATE INDEX IF NOT EXISTS idx_fact_events_session_timestamp
    ON fact_events(session_id, timestamp, id);

CREATE INDEX IF NOT EXISTS idx_l1_source_facets_event
    ON l1_source_facets(event_id);

CREATE INDEX IF NOT EXISTS idx_l1_source_facets_text
    ON l1_source_facets(source, facet_name, normalized_text_value);

CREATE INDEX IF NOT EXISTS idx_l1_source_facets_numeric
    ON l1_source_facets(source, facet_name, numeric_value);

CREATE INDEX IF NOT EXISTS idx_l1_source_facets_timestamp
    ON l1_source_facets(source, facet_name, timestamp_value);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_l1_source_facets_timestamp;

DROP INDEX IF EXISTS idx_l1_source_facets_numeric;

DROP INDEX IF EXISTS idx_l1_source_facets_text;

DROP INDEX IF EXISTS idx_l1_source_facets_event;

DROP INDEX IF EXISTS idx_fact_events_session_timestamp;

DROP INDEX IF EXISTS idx_fact_events_session_seq;

DROP INDEX IF EXISTS idx_l1_event_payload_created_at;

DROP INDEX IF EXISTS idx_chat_sessions_user_last_message;

DROP INDEX IF EXISTS idx_chat_sessions_user_updated;

DROP INDEX IF EXISTS idx_l1_event_entities_entity;

DROP INDEX IF EXISTS idx_l1_event_chunks_event;

DROP INDEX IF EXISTS idx_l1_event_embedding_state_profile;

DROP INDEX IF EXISTS idx_l1_event_embedding_state_status;

DROP INDEX IF EXISTS idx_fact_events_business_idempotency;

DROP INDEX IF EXISTS idx_fact_events_l1_retrieval_scope;

DROP INDEX IF EXISTS idx_fact_events_evidence_class;

DROP INDEX IF EXISTS idx_fact_events_evidence_status;

DROP INDEX IF EXISTS idx_fact_events_retention;

DROP INDEX IF EXISTS idx_fact_events_importance;

DROP INDEX IF EXISTS idx_fact_events_user;

DROP INDEX IF EXISTS idx_fact_events_turn;

DROP INDEX IF EXISTS idx_fact_events_session;

DROP INDEX IF EXISTS idx_fact_events_domain;

DROP INDEX IF EXISTS idx_fact_events_idempotency_key;

DROP INDEX IF EXISTS idx_fact_events_source;

DROP INDEX IF EXISTS idx_fact_events_type;

DROP INDEX IF EXISTS idx_fact_events_timestamp;

DROP TABLE IF EXISTS l1_source_facets;

DROP TABLE IF EXISTS l1_event_payload;

DROP TABLE IF EXISTS chat_sessions;

DROP TABLE IF EXISTS l1_event_entities;

DROP TABLE IF EXISTS l1_events_fts;

DROP TABLE IF EXISTS l1_event_chunks;

DROP TABLE IF EXISTS embedding_profiles;

DROP TABLE IF EXISTS l1_event_embedding_state;

DROP TABLE IF EXISTS l1_session_sequences;

DROP TABLE IF EXISTS fact_events;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
