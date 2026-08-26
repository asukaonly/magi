"""Magi v1 release baseline schema."""

from __future__ import annotations

from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    usage_available INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    ttft_ms INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    correlation_id TEXT,
    session_id TEXT,
    turn_id TEXT,
    agent_id TEXT,
    created_at REAL NOT NULL,
    cost_currency TEXT,
    cache_read_tokens INTEGER DEFAULT '0' NOT NULL,
    cache_write_tokens INTEGER DEFAULT '0' NOT NULL,
    cache_write_1h_tokens INTEGER DEFAULT '0' NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_usage_rollups (
    granularity TEXT NOT NULL,
    bucket_start TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_kind TEXT NOT NULL,
    success INTEGER NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    calls_with_usage INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    latency_ms_total INTEGER NOT NULL DEFAULT 0,
    ttft_ms_total INTEGER NOT NULL DEFAULT 0,
    ttft_ms_count INTEGER NOT NULL DEFAULT 0,
    last_rolled_up_at REAL NOT NULL,
    cache_read_tokens INTEGER DEFAULT '0' NOT NULL,
    cache_write_tokens INTEGER DEFAULT '0' NOT NULL,
    cache_write_1h_tokens INTEGER DEFAULT '0' NOT NULL,
    PRIMARY KEY (granularity, bucket_start, provider, model, request_kind, success)
);

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
    dynamic_context_hash TEXT NOT NULL DEFAULT '',
    dynamic_context_chars INTEGER NOT NULL DEFAULT 0,
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

CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at
    ON llm_usage(created_at);

CREATE INDEX IF NOT EXISTS idx_llm_usage_provider_model
    ON llm_usage(provider, model);

CREATE INDEX IF NOT EXISTS idx_llm_usage_request_kind
    ON llm_usage(request_kind);

CREATE INDEX IF NOT EXISTS idx_llm_usage_rollups_bucket
    ON llm_usage_rollups(granularity, bucket_start);

CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_created_at
    ON llm_cache_observations(created_at);

CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_session_model
    ON llm_cache_observations(session_id, provider, model, request_kind, created_at);

CREATE INDEX IF NOT EXISTS idx_llm_cache_observations_request_id
    ON llm_cache_observations(request_id);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_llm_cache_observations_request_id;

DROP INDEX IF EXISTS idx_llm_cache_observations_session_model;

DROP INDEX IF EXISTS idx_llm_cache_observations_created_at;

DROP INDEX IF EXISTS idx_llm_usage_rollups_bucket;

DROP INDEX IF EXISTS idx_llm_usage_request_kind;

DROP INDEX IF EXISTS idx_llm_usage_provider_model;

DROP INDEX IF EXISTS idx_llm_usage_created_at;

DROP TABLE IF EXISTS llm_cache_observations;

DROP TABLE IF EXISTS llm_usage_rollups;

DROP TABLE IF EXISTS llm_usage;
"""

def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
