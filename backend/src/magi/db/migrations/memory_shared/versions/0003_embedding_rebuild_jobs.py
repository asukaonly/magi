"""Track embedding rebuild jobs and edge profiles

Revision ID: 0003_embedding_rebuild_jobs
Revises: 0002_seed_graph_conflict_rules
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_embedding_rebuild_jobs"
down_revision = "0002_seed_graph_conflict_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_graph") as batch_op:
        batch_op.add_column(sa.Column("embedding_profile_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("last_embedded_at", sa.REAL(), nullable=True))

    op.create_index(
        "idx_knowledge_graph_embedding_profile",
        "knowledge_graph",
        ["embedding_profile_id"],
    )
    op.create_table(
        "embedding_rebuild_jobs",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("requested_layers_json", sa.Text(), nullable=False),
        sa.Column("active_layer", sa.Text(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.REAL(), nullable=False),
        sa.Column("started_at", sa.REAL(), nullable=True),
        sa.Column("finished_at", sa.REAL(), nullable=True),
        sa.Column("updated_at", sa.REAL(), nullable=False),
    )
    op.create_index(
        "idx_embedding_rebuild_jobs_status_updated",
        "embedding_rebuild_jobs",
        ["status", "updated_at"],
    )
    op.create_table(
        "embedding_rebuild_job_layers",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.REAL(), nullable=True),
        sa.Column("finished_at", sa.REAL(), nullable=True),
        sa.Column("updated_at", sa.REAL(), nullable=False),
        sa.PrimaryKeyConstraint("job_id", "layer"),
    )
    op.create_index(
        "idx_embedding_rebuild_job_layers_status",
        "embedding_rebuild_job_layers",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_embedding_rebuild_job_layers_status", table_name="embedding_rebuild_job_layers"
    )
    op.drop_table("embedding_rebuild_job_layers")
    op.drop_index("idx_embedding_rebuild_jobs_status_updated", table_name="embedding_rebuild_jobs")
    op.drop_table("embedding_rebuild_jobs")
    op.drop_index("idx_knowledge_graph_embedding_profile", table_name="knowledge_graph")
    with op.batch_alter_table("knowledge_graph") as batch_op:
        batch_op.drop_column("last_embedded_at")
        batch_op.drop_column("embedding_profile_id")
