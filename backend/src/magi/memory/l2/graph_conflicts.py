"""Structured graph-conflict rules for L2 knowledge edges."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Iterable, Mapping, Literal

GraphConflictAction = Literal["mark_deprecated", "mark_conflicted"]
GraphExclusiveScope = Literal["same_subject"]
DEFAULT_GRAPH_CONFLICT_ACTION: GraphConflictAction = "mark_deprecated"
DEFAULT_GRAPH_EXCLUSIVE_SCOPE: GraphExclusiveScope = "same_subject"
_VALID_ACTIONS = {"mark_deprecated", "mark_conflicted"}
_VALID_SCOPES = {"same_subject"}


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
        predicate = _normalize_predicate(payload.get("predicate"), field_name="predicate")
        opposite_predicates = payload.get("opposite_predicates", ())
        if isinstance(opposite_predicates, str):
            try:
                decoded = json.loads(opposite_predicates)
                if isinstance(decoded, list):
                    opposite_predicates = decoded
                else:
                    opposite_predicates = [opposite_predicates]
            except json.JSONDecodeError:
                opposite_predicates = [
                    item.strip() for item in opposite_predicates.split(",") if item.strip()
                ]
        normalized_opposites = _normalize_opposite_predicates(
            opposite_predicates, predicate=predicate
        )
        opposite_resolution = _normalize_action(
            payload.get("opposite_resolution", DEFAULT_GRAPH_CONFLICT_ACTION),
            field_name="opposite_resolution",
        )
        exclusive_group = _normalize_exclusive_group(payload.get("exclusive_group"))
        exclusive_scope = _normalize_scope(
            payload.get("exclusive_scope", DEFAULT_GRAPH_EXCLUSIVE_SCOPE),
            field_name="exclusive_scope",
        )
        exclusive_resolution = _normalize_action(
            payload.get("exclusive_resolution", DEFAULT_GRAPH_CONFLICT_ACTION),
            field_name="exclusive_resolution",
        )
        _validate_rule_combinations(
            predicate=predicate,
            opposite_predicates=normalized_opposites,
            opposite_resolution=opposite_resolution,
            exclusive_group=exclusive_group,
            exclusive_resolution=exclusive_resolution,
        )
        return cls(
            predicate=predicate,
            opposite_predicates=normalized_opposites,
            opposite_resolution=opposite_resolution,
            exclusive_group=exclusive_group,
            exclusive_scope=exclusive_scope,
            exclusive_resolution=exclusive_resolution,
        )

    def to_record(self) -> Dict[str, Any]:
        """Return a JSON-safe representation for storage or API responses."""
        return {
            "predicate": self.predicate,
            "opposite_predicates": list(self.opposite_predicates),
            "opposite_resolution": self.opposite_resolution,
            "exclusive_group": self.exclusive_group,
            "exclusive_scope": self.exclusive_scope,
            "exclusive_resolution": self.exclusive_resolution,
        }


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
        normalized = (
            rule if isinstance(rule, GraphConflictRule) else GraphConflictRule.from_mapping(rule)
        )
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
    return {group: tuple(sorted(set(predicates))) for group, predicates in grouped.items()}


def relationship_predicate_slot(
    rules: Mapping[str, GraphConflictRule],
    *,
    predicate: str,
    object_id: str,
) -> str | None:
    """Return the conflict-aware predicate slot shared by writes and corrections."""
    normalized_predicate = str(predicate).strip().upper()
    rule = rules.get(normalized_predicate)
    if rule is None:
        return None
    if rule.exclusive_group:
        return f"exclusive:{rule.exclusive_group}"
    if rule.opposite_predicates:
        family = ":".join(sorted({normalized_predicate, *rule.opposite_predicates}))
        return f"opposites:{family}:{object_id}"
    return None


def iter_opposite_predicates(rule: GraphConflictRule) -> Iterable[str]:
    """Expose opposite predicates in a stable order."""
    return tuple(rule.opposite_predicates)


def _normalize_predicate(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _normalize_opposite_predicates(values: Any, *, predicate: str) -> tuple[str, ...]:
    if values is None:
        raw_values: list[Any] = []
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = [values]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip().upper()
        if not text:
            continue
        if text == predicate:
            raise ValueError("opposite_predicates cannot reference itself")
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_action(value: Any, *, field_name: str) -> GraphConflictAction:
    text = str(value or DEFAULT_GRAPH_CONFLICT_ACTION).strip()
    if text not in _VALID_ACTIONS:
        raise ValueError(f"{field_name} must be one of: {', '.join(sorted(_VALID_ACTIONS))}")
    return text  # type: ignore[return-value]


def _normalize_scope(value: Any, *, field_name: str) -> GraphExclusiveScope:
    text = str(value or DEFAULT_GRAPH_EXCLUSIVE_SCOPE).strip()
    if text not in _VALID_SCOPES:
        raise ValueError(f"{field_name} must be one of: {', '.join(sorted(_VALID_SCOPES))}")
    return text  # type: ignore[return-value]


def _normalize_exclusive_group(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_rule_combinations(
    *,
    predicate: str,
    opposite_predicates: tuple[str, ...],
    opposite_resolution: GraphConflictAction,
    exclusive_group: str | None,
    exclusive_resolution: GraphConflictAction,
) -> None:
    del predicate
    if not opposite_predicates and opposite_resolution != DEFAULT_GRAPH_CONFLICT_ACTION:
        raise ValueError(
            "opposite_predicates are required when opposite_resolution overrides the default"
        )
    if exclusive_group is None and exclusive_resolution != DEFAULT_GRAPH_CONFLICT_ACTION:
        raise ValueError(
            "exclusive_group is required when exclusive_resolution overrides the default"
        )
    if not opposite_predicates and not exclusive_group:
        raise ValueError("graph conflict rule must define at least one conflict mechanism")
