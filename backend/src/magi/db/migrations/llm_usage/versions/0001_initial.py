"""llm_usage baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06

Materialises the canonical llm_usage schema (single ``llm_usage`` table
plus its supporting indexes) on a fresh database. This revision is the
snapshot of the schema as it stood the day Alembic took ownership; any
further evolution is a new revision file.
"""
from __future__ import annotations

from alembic import op


revision = "0001_initial"
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
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at
    ON llm_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_provider_model
    ON llm_usage(provider, model);
CREATE INDEX IF NOT EXISTS idx_llm_usage_request_kind
    ON llm_usage(request_kind);
"""

DROP_SQL = """
DROP TABLE IF EXISTS llm_usage;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
