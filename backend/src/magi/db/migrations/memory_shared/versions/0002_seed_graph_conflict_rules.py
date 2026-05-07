"""Seed default graph conflict rules

Revision ID: 0002_seed_graph_conflict_rules
Revises: 0001_initial
Create Date: 2026-05-07

The L2 graph relies on a small fixed set of conflict-resolution rules
(LIKES↔DISLIKES, CURRENT_WORKS_AT/LIVES_IN/RELATIONSHIP_WITH exclusive
groups) to deprecate stale edges. These are part of the system's static
ontology and must exist on a fresh database for conflict handling to
work, so they live with the schema instead of being seeded by app code.
"""
from __future__ import annotations

import json
import time

from alembic import op


revision = "0002_seed_graph_conflict_rules"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


_DEFAULT_RULES: tuple[dict, ...] = (
    {
        "predicate": "LIKES",
        "opposite_predicates": ["DISLIKES"],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": None,
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "DISLIKES",
        "opposite_predicates": ["LIKES"],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": None,
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_WORKS_AT",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_work",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_LIVES_IN",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_residence",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
    {
        "predicate": "CURRENT_RELATIONSHIP_WITH",
        "opposite_predicates": [],
        "opposite_resolution": "mark_deprecated",
        "exclusive_group": "current_relationship",
        "exclusive_scope": "same_subject",
        "exclusive_resolution": "mark_deprecated",
    },
)


def upgrade() -> None:
    bind = op.get_bind().connection
    now = time.time()
    for rule in _DEFAULT_RULES:
        bind.execute(
            """
            INSERT OR IGNORE INTO graph_conflict_rules(
                predicate, opposite_predicates, opposite_resolution,
                exclusive_group, exclusive_scope, exclusive_resolution,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rule["predicate"],
                json.dumps(rule["opposite_predicates"], ensure_ascii=False),
                rule["opposite_resolution"],
                rule["exclusive_group"],
                rule["exclusive_scope"],
                rule["exclusive_resolution"],
                now,
                now,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind().connection
    for rule in _DEFAULT_RULES:
        bind.execute(
            "DELETE FROM graph_conflict_rules WHERE predicate = ?",
            (rule["predicate"],),
        )
