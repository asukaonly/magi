"""llm_usage: add prompt-cache observation diagnostics

Revision ID: 0004_cache_observations
Revises: 0003_cache_tokens
Create Date: 2026-06-28

Stores lightweight prompt-cache diagnostics for LLM calls. Rows contain hashes,
lengths, tool counts, optional tool names, and provider-reported cache token
counts; raw prompts and tool schemas are deliberately not persisted.
"""

from __future__ import annotations

from alembic import op


revision = "0004_cache_observations"
down_revision = "0003_cache_tokens"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_cache_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    session_id TEXT,
    turn_id TEXT,
    agent_id TEXT,
    cache_strategy TEXT NOT NULL,
    cache_eligible INTEGER NOT NULL DEFAULT 0,
    system_head_hash TEXT NOT NULL DEFAULT '',
    system_head_chars INTEGER NOT NULL DEFAULT 0,
    turn_context_hash TEXT NOT NULL DEFAULT '',
    turn_context_chars INTEGER NOT NULL DEFAULT 0,
    tools_hash TEXT NOT NULL DEFAULT '',
    tool_count INTEGER NOT NULL DEFAULT 0,
    tool_names_json TEXT NOT NULL DEFAULT '[]',
    system_head_reused INTEGER,
    tools_reused INTEGER,
    predicted_miss_reasons_json TEXT NOT NULL DEFAULT '[]',
    cache_fields_seen INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_created_at
    ON llm_cache_observations(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_session_model
    ON llm_cache_observations(session_id, provider, model, request_kind, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_request_id
    ON llm_cache_observations(request_id);
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript("DROP TABLE IF EXISTS llm_cache_observations;")
