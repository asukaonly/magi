"""Graph-derived assertion rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from ....core.logger import get_logger
from ..entities.catalog.lookup import get_canonical_names

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class GraphDerivedAssertionRule:
    """Declarative rule for deriving assertions from accumulated graph edges."""

    rule_id: str
    source_predicates: tuple[str, ...]
    trait_family: str
    trait_name_template: str
    min_observations: int = 1
    min_distinct_days: int = 0
    source_domains: tuple[str, ...] = field(default_factory=lambda: ("external_activity",))
    value_strategy: str = "canonical_name"

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", str(self.rule_id).strip())
        object.__setattr__(
            self,
            "source_predicates",
            tuple(
                str(predicate).strip().upper()
                for predicate in self.source_predicates
                if str(predicate).strip()
            ),
        )
        object.__setattr__(self, "trait_family", str(self.trait_family).strip().casefold())
        object.__setattr__(self, "trait_name_template", str(self.trait_name_template).strip())
        object.__setattr__(self, "min_observations", max(1, int(self.min_observations or 1)))
        object.__setattr__(self, "min_distinct_days", max(0, int(self.min_distinct_days or 0)))
        object.__setattr__(
            self,
            "source_domains",
            tuple(
                str(domain).strip().casefold()
                for domain in self.source_domains
                if str(domain).strip()
            ),
        )
        object.__setattr__(self, "value_strategy", str(self.value_strategy).strip() or "canonical_name")


def builtin_interest_rule(*, min_observations: int = 3) -> GraphDerivedAssertionRule:
    """Return the host rule equivalent to the legacy interest aggregation."""
    return GraphDerivedAssertionRule(
        rule_id="builtin.interested_in",
        source_predicates=("INTERESTED_IN",),
        trait_family="preference_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
    )


async def evaluate_graph_derived_assertion_rule(
    store: Any,
    rule: GraphDerivedAssertionRule,
    *,
    entity_id: str = "user:self",
    entity_type: str = "user",
    limit: int = 500,
) -> dict[str, int]:
    """Evaluate one graph-derived assertion rule and persist matching assertions."""
    edges: list[dict[str, Any]] = await store.get_relationships(
        subject_id=entity_id,
        predicates=list(rule.source_predicates),
        status="active",
        limit=limit,
    )
    edges_seen = len(edges)
    if edges_seen >= limit:
        logger.warning(
            "graph-derived assertion rule hit edge limit",
            rule_id=rule.rule_id,
            entity_id=entity_id,
            limit=limit,
        )

    qualifying = [
        edge
        for edge in edges
        if _edge_meets_rule(edge=edge, rule=rule)
    ]
    if not qualifying:
        logger.debug(
            "graph-derived assertion rule had no qualifying edges",
            rule_id=rule.rule_id,
            entity_id=entity_id,
            edges_seen=edges_seen,
        )
        return {"edges_seen": edges_seen, "assertions_written": 0}

    object_ids = [str(edge.get("object_id") or "") for edge in qualifying]
    canonical_names = await get_canonical_names(store.db_path, object_ids)

    assertions_written = 0
    for edge in qualifying:
        candidate = _candidate_from_edge(
            edge=edge,
            rule=rule,
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_names=canonical_names,
        )
        if candidate is None:
            continue
        await store.upsert_assertion_candidate(candidate)
        assertions_written += 1
        logger.debug(
            "graph-derived assertion rule wrote assertion",
            rule_id=rule.rule_id,
            entity_id=entity_id,
            trait_name=candidate["trait_name"],
            object_id=candidate["target_entity_id"],
            evidence_count=len(candidate["evidence_events"]),
        )

    logger.info(
        "graph-derived assertion rule completed",
        rule_id=rule.rule_id,
        entity_id=entity_id,
        edges_seen=edges_seen,
        assertions_written=assertions_written,
    )
    return {"edges_seen": edges_seen, "assertions_written": assertions_written}


def _edge_meets_rule(*, edge: dict[str, Any], rule: GraphDerivedAssertionRule) -> bool:
    if int(edge.get("observation_count", 0) or 0) < rule.min_observations:
        return False
    if rule.min_distinct_days <= 1:
        return True
    first_observed_at = float(edge.get("first_observed_at", 0.0) or 0.0)
    last_observed_at = float(edge.get("last_observed_at", 0.0) or 0.0)
    if first_observed_at <= 0 or last_observed_at <= 0:
        return False
    first_day = int(first_observed_at // 86_400)
    last_day = int(last_observed_at // 86_400)
    return (last_day - first_day + 1) >= rule.min_distinct_days


def _candidate_from_edge(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    entity_type: str,
    canonical_names: dict[str, str],
) -> dict[str, Any] | None:
    object_id = str(edge.get("object_id") or "").strip()
    object_type = str(edge.get("object_type") or "topic").strip().casefold() or "topic"
    predicate = str(edge.get("predicate") or "").strip().upper()
    raw_slug = _object_slug(object_id)
    slug = _safe_slug(raw_slug)
    if not slug:
        logger.warning(
            "graph-derived assertion rule skipped empty object slug",
            rule_id=rule.rule_id,
            object_id=object_id,
        )
        return None
    if slug != raw_slug.lower():
        slug = f"{slug}-{hashlib.sha1(object_id.encode('utf-8')).hexdigest()[:6]}"

    trait_name = rule.trait_name_template.format(
        object_id=object_id,
        object_type=object_type,
        object_slug=slug,
        raw_object_slug=raw_slug,
        predicate=predicate,
    )
    trait_value = _trait_value_for_edge(
        edge=edge,
        rule=rule,
        object_id=object_id,
        object_slug=raw_slug,
        canonical_names=canonical_names,
    )
    obs_count = int(edge.get("observation_count", 1) or 1)
    confidence_score = min(
        0.9,
        float(edge.get("confidence", 0.5) or 0.5) * (1 + 0.1 * min(obs_count, 5)),
    )
    evidence_events = list(edge.get("evidence_event_ids") or [])
    source_domain = rule.source_domains[0] if rule.source_domains else "external_activity"

    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "trait_family": rule.trait_family,
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": confidence_score,
        "evidence_events": evidence_events,
        "volatility_index": 0.2,
        "source_domain": source_domain,
        "inference_depth": "topology_only",
        "validation_state": "tentative",
        "first_inferred_at": float(edge.get("first_observed_at", 0.0) or 0.0),
        "last_validated_at": float(edge.get("last_observed_at", 0.0) or 0.0),
        "target_entity_id": object_id,
        "target_entity_type": object_type,
        "target_scope": "entity_bound",
        "temporal_scope": "stable",
        "decay_policy": "evidence_only",
        "natural_summary": f"Recurring {predicate.lower()} signal for {trait_value}",
    }


def _trait_value_for_edge(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
    object_id: str,
    object_slug: str,
    canonical_names: dict[str, str],
) -> str:
    if rule.value_strategy == "object_id":
        return object_id
    if rule.value_strategy == "object_slug":
        return object_slug
    return canonical_names.get(object_id, object_slug)


def _object_slug(object_id: str) -> str:
    if ":" in object_id:
        return object_id.split(":", 1)[1]
    return object_id


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", slug.lower())


__all__ = [
    "GraphDerivedAssertionRule",
    "builtin_interest_rule",
    "evaluate_graph_derived_assertion_rule",
]
