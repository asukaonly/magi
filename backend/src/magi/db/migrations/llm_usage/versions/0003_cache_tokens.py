"""llm_usage: persist prompt cache token counts

Revision ID: 0003_cache_tokens
Revises: 0002_cost_currency
Create Date: 2026-06-28

Adds provider-reported prompt-cache read/write token counts to raw LLM usage
rows and operational rollups so cache utilization can be reported from the
existing usage metrics path.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_cache_tokens"
down_revision = "0002_cost_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_usage",
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_usage",
        sa.Column("cache_write_1h_tokens", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "llm_usage_rollups",
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_usage_rollups",
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_usage_rollups",
        sa.Column("cache_write_1h_tokens", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    with op.batch_alter_table("llm_usage_rollups") as batch_op:
        batch_op.drop_column("cache_write_1h_tokens")
        batch_op.drop_column("cache_write_tokens")
        batch_op.drop_column("cache_read_tokens")

    with op.batch_alter_table("llm_usage") as batch_op:
        batch_op.drop_column("cache_write_1h_tokens")
        batch_op.drop_column("cache_write_tokens")
        batch_op.drop_column("cache_read_tokens")
