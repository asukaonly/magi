"""Drop redundant indexes covered by UNIQUE constraints or PK

Revision ID: 0003_drop_redundant_indexes
Revises: 0002_seed_graph_conflict_rules
Create Date: 2026-05-07

Drops 6 redundant indexes that are fully covered by existing UNIQUE
constraints or composite indexes:

- idx_procedural_skill_name              == UNIQUE(skill_name, skill_category)
- idx_entity_facets_entity_name          ⊂ UNIQUE(entity_id, facet_name, facet_value)
- idx_summary_event_links_summary        ⊂ UNIQUE(summary_id, event_id, link_role)
- idx_summary_task_links_summary         ⊂ UNIQUE(summary_id, task_id, link_role)
- idx_l3_summary_chunks_summary          ⊂ idx_l3_summary_chunks_index(summary_id, chunk_index)
- idx_l4_skill_chunks_skill              ⊂ idx_l4_skill_chunks_index(skill_id, chunk_index)
"""
from __future__ import annotations

from alembic import op


revision = "0003_drop_redundant_indexes"
down_revision = "0002_seed_graph_conflict_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_procedural_skill_name")
    op.execute("DROP INDEX IF EXISTS idx_entity_facets_entity_name")
    op.execute("DROP INDEX IF EXISTS idx_summary_event_links_summary")
    op.execute("DROP INDEX IF EXISTS idx_summary_task_links_summary")
    op.execute("DROP INDEX IF EXISTS idx_l3_summary_chunks_summary")
    op.execute("DROP INDEX IF EXISTS idx_l4_skill_chunks_skill")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_procedural_skill_name "
        "ON procedural_skills(skill_name, skill_category)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_entity_facets_entity_name "
        "ON entity_facets(entity_id, facet_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_summary_event_links_summary "
        "ON summary_event_links(summary_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_summary_task_links_summary "
        "ON summary_task_links(summary_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_l3_summary_chunks_summary "
        "ON l3_summary_chunks(summary_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_l4_skill_chunks_skill "
        "ON l4_skill_chunks(skill_id)"
    )
