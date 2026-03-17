"""Structured graph-conflict rules for L2 knowledge edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Literal

GraphConflictAction = Literal["mark_deprecated", "mark_conflicted"]
GraphExclusiveScope = Literal["same_subject"]


@dataclass(frozen=True)
class GraphConflictRule:
    """Defines how a predicate conflicts with existing graph edges."""

    predicate: str
    opposite_predicates: tuple[str, ...] = ()
    opposite_resolution: GraphConflictAction = "mark_deprecated"
    exclusive_group: str | None = None
    exclusive_scope: GraphExclusiveScope = "same_subject"
    exclusive_resolution: GraphConflictAction = "mark_deprecated"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GraphConflictRule":
        """Build a rule from a plain mapping."""
        opposite_predicates = payload.get("opposite_predicates", ())
        return cls(
            predicate=str(payload["predicate"]),
            opposite_predicates=tuple(str(item) for item in opposite_predicates),
            opposite_resolution=str(payload.get("opposite_resolution", "mark_deprecated")),  # type: ignore[arg-type]
            exclusive_group=(
                str(payload["exclusive_group"]) if payload.get("exclusive_group") is not None else None
            ),
            exclusive_scope=str(payload.get("exclusive_scope", "same_subject")),  # type: ignore[arg-type]
            exclusive_resolution=str(payload.get("exclusive_resolution", "mark_deprecated")),  # type: ignore[arg-type]
        )


DEFAULT_GRAPH_CONFLICT_RULES: dict[str, GraphConflictRule] = {
    "LIKES": GraphConflictRule(
        predicate="LIKES",
        opposite_predicates=("DISLIKES",),
        opposite_resolution="mark_deprecated",
    ),
    "DISLIKES": GraphConflictRule(
        predicate="DISLIKES",
        opposite_predicates=("LIKES",),
        opposite_resolution="mark_deprecated",
    ),
    "CURRENT_WORKS_AT": GraphConflictRule(
        predicate="CURRENT_WORKS_AT",
        exclusive_group="current_work",
    ),
    "CURRENT_LIVES_IN": GraphConflictRule(
        predicate="CURRENT_LIVES_IN",
        exclusive_group="current_residence",
    ),
    "CURRENT_RELATIONSHIP_WITH": GraphConflictRule(
        predicate="CURRENT_RELATIONSHIP_WITH",
        exclusive_group="current_relationship",
    ),
}


def build_graph_conflict_matrix(
    overrides: Mapping[str, GraphConflictRule | Mapping[str, Any]] | None = None,
) -> dict[str, GraphConflictRule]:
    """Return the default rule matrix with optional predicate-level overrides."""
    matrix = dict(DEFAULT_GRAPH_CONFLICT_RULES)
    if not overrides:
        return matrix

    for predicate, rule in overrides.items():
        normalized = rule if isinstance(rule, GraphConflictRule) else GraphConflictRule.from_mapping(rule)
        matrix[str(predicate)] = normalized
    return matrix


def build_exclusive_group_index(
    rules: Mapping[str, GraphConflictRule],
) -> dict[str, tuple[str, ...]]:
    """Group predicates by shared exclusivity bucket."""
    grouped: dict[str, list[str]] = {}
    for predicate, rule in rules.items():
        if not rule.exclusive_group:
            continue
        grouped.setdefault(rule.exclusive_group, []).append(predicate)
    return {
        group: tuple(sorted(set(predicates)))
        for group, predicates in grouped.items()
    }


def iter_opposite_predicates(rule: GraphConflictRule) -> Iterable[str]:
    """Expose opposite predicates in a stable order."""
    return tuple(rule.opposite_predicates)
