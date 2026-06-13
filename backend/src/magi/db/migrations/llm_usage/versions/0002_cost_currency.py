"""llm_usage: record native-currency cost

Revision ID: 0002_cost_currency
Revises: 0001_initial
Create Date: 2026-06-13

Adds a nullable ``cost_currency`` column to ``llm_usage`` so a call's cost can be
stored in the model's native billing currency (CNY, USD, ...) instead of being
silently dropped whenever it was not USD.

A NULL ``cost_currency`` is the sentinel for "no pricing data available" — which
is distinct from a genuine zero cost — so the UI can render an em dash instead of
a misleading $0.00.

Existing rows were written by the old USD-only pricing path, which stored a
USD-or-zero ``cost_usd``. Rows with a positive cost are therefore backfilled to
'USD'; zero-cost legacy rows are left NULL because they never carried a real
cost figure (non-USD models were dropped to 0 under the old code).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_cost_currency"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("cost_currency", sa.Text(), nullable=True))
    op.execute(
        "UPDATE llm_usage SET cost_currency = 'USD' "
        "WHERE cost_currency IS NULL AND cost_usd > 0"
    )


def downgrade() -> None:
    # batch_alter_table rebuilds the table, so the drop works on every SQLite
    # version (plain ALTER ... DROP COLUMN needs SQLite >= 3.35).
    with op.batch_alter_table("llm_usage") as batch_op:
        batch_op.drop_column("cost_currency")
