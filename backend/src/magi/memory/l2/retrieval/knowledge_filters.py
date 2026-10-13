"""Shared list/count filters for the product knowledge browser."""

from typing import Literal

KnowledgeStatusGroup = Literal["needsReview", "active", "conflicted", "deprecated"]

RELATION_STATUS_GROUP_SQL = """CASE
    WHEN status IN ('deprecated', 'superseded', 'expired', 'archived', 'rejected', 'user_rejected') THEN 'deprecated'
    WHEN status IN ('conflicted', 'contradicted') THEN 'conflicted'
    ELSE 'active' END"""

ASSERTION_STATUS_GROUP_SQL = """CASE
    WHEN user_feedback = 'rejected'
      OR validation_state IN ('deprecated', 'user_rejected', 'rejected', 'superseded', 'expired', 'archived')
      OR status IN ('deprecated', 'user_rejected', 'rejected', 'superseded', 'expired', 'archived') THEN 'deprecated'
    WHEN validation_state IN ('conflicted', 'contradicted')
      OR status IN ('conflicted', 'contradicted') THEN 'conflicted'
    WHEN user_feedback = 'confirmed' OR validation_state IN ('stable', 'corroborated')
      OR status = 'stable' THEN 'active'
    ELSE 'needsReview' END"""


def status_group_clause(
    expression: str, status_group: KnowledgeStatusGroup | None
) -> tuple[str, list[str]]:
    """Return the same status classification for paginated rows and totals."""
    if status_group is None:
        return "", []
    return f" AND ({expression}) = ?", [status_group]
