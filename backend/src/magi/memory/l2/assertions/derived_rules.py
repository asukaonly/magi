"""Graph-derived assertion rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ....identity.defaults import CANONICAL_LOCAL_USER
from ..entities.catalog.lookup import get_canonical_names
from ..ontology import ASSERTION_FAMILY_ALLOWLIST, ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY

logger = get_logger(__name__)

_VALUE_STRATEGIES = frozenset({"canonical_name", "object_id", "object_slug"})
_DEFAULT_USER_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"
_PROFILE_INTEREST_OBJECT_TYPES = (
    "topic",
    "media",
    "person",
    "group",
    "organization",
    "product",
    "technology",
    "activity",
)
_PROFILE_INTEREST_MIN_DISTINCT_DAYS = 2
_LONG_HEX_VALUE_RE = re.compile(r"^[0-9a-f]{12,}$", re.IGNORECASE)
_COORDINATE_VALUE_RE = re.compile(r"^[-+]?\d{1,3}(?:\.\d+)?\s*,\s*[-+]?\d{1,3}(?:\.\d+)?$")
_URL_VALUE_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|www\.)", re.IGNORECASE)
_DOMAIN_VALUE_RE = re.compile(
    r"^[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?::\d+)?/?$",
    re.IGNORECASE,
)
_EMAIL_VALUE_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PATH_VALUE_RE = re.compile(
    r"(?:^~?/|^\./|^\.\./|[\\/].+\.[a-z0-9]{1,8}(?:$|[?#]))",
    re.IGNORECASE,
)
_FILEISH_VALUE_RE = re.compile(
    r"^(?:img_\d+|dsc_\d+|screenshot[-_]\d+|[\w.-]+[-_][\w.-]+)"
    r"\.(?:log|tmp|cache|json|ya?ml|toml|py|pyi|ts|tsx|js|jsx|css|html?|md|txt|csv|db|sqlite|"
    r"jpg|jpeg|png|gif|webp|heic|mov|mp4|zip|gz|dmg)$",
    re.IGNORECASE,
)


class _DerivedAssertionProfile(Protocol):
    profile_id: str
    source_types: frozenset[str]
    derived_assertion_specs: tuple[dict[str, Any], ...]
    allowed_assertion_families: frozenset[str]
    allowed_assertion_traits: frozenset[str] | None

    @property
    def effective_structured_allowed_predicates(self) -> frozenset[str]:
        ...

    @property
    def effective_structured_allowed_entity_types(self) -> frozenset[str]:
        ...


@dataclass(slots=True, frozen=True)
class GraphDerivedAssertionRule:
    """Declarative rule for deriving assertions from accumulated graph edges."""

    rule_id: str
    source_predicates: tuple[str, ...]
    trait_family: str
    trait_name_template: str
    min_observations: int = 1
    min_distinct_days: int = 0
    source_types: tuple[str, ...] = field(default_factory=tuple)
    source_domains: tuple[str, ...] = field(default_factory=lambda: ("external_activity",))
    value_strategy: str = "canonical_name"
    object_types: tuple[str, ...] = field(default_factory=tuple)

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
            "source_types",
            tuple(
                str(source_type).strip().casefold()
                for source_type in self.source_types
                if str(source_type).strip()
            ),
        )
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
        object.__setattr__(
            self,
            "object_types",
            tuple(
                str(object_type).strip().casefold()
                for object_type in self.object_types
                if str(object_type).strip()
            ),
        )


def builtin_interest_rule(*, min_observations: int = 3) -> GraphDerivedAssertionRule:
    """Return the host fallback rule for stable profile-worthy interests."""
    return GraphDerivedAssertionRule(
        rule_id="builtin.interested_in",
        source_predicates=("INTERESTED_IN",),
        trait_family="preference_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        min_distinct_days=_PROFILE_INTEREST_MIN_DISTINCT_DAYS,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
        object_types=_PROFILE_INTEREST_OBJECT_TYPES,
    )


def build_graph_derived_rules_from_profiles(
    profiles: Mapping[str, _DerivedAssertionProfile] | Iterable[_DerivedAssertionProfile],
) -> tuple[GraphDerivedAssertionRule, ...]:
    """Compile plugin-contributed derived assertion specs into host-owned rules."""
    profile_values: Iterable[_DerivedAssertionProfile]
    if isinstance(profiles, Mapping):
        profile_values = profiles.values()
    else:
        profile_values = cast(Iterable[_DerivedAssertionProfile], profiles)
    rules: list[GraphDerivedAssertionRule] = []
    for profile in profile_values:
        for index, spec in enumerate(profile.derived_assertion_specs):
            rule = _rule_from_profile_spec(profile=profile, spec=spec, index=index)
            if rule is not None:
                rules.append(rule)
    return tuple(rules)


async def evaluate_graph_derived_assertion_rule(
    store: Any,
    rule: GraphDerivedAssertionRule,
    *,
    entity_id: str = _DEFAULT_USER_ENTITY_ID,
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
    if rule.source_types:
        source_type = str(edge.get("source_type") or "").strip().casefold()
        if source_type not in rule.source_types:
            return False
    if rule.object_types:
        object_type = str(edge.get("object_type") or "").strip().casefold()
        if object_type not in rule.object_types:
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
    if _is_low_quality_profile_value(raw_slug=raw_slug, trait_value=trait_value):
        logger.debug(
            "graph-derived assertion rule skipped low-quality profile value",
            rule_id=rule.rule_id,
            object_id=object_id,
            trait_value=trait_value,
        )
        return None

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


def _is_low_quality_profile_value(*, raw_slug: str, trait_value: str) -> bool:
    labels = [
        str(label).strip()
        for label in (trait_value, raw_slug)
        if str(label).strip()
    ]
    if not labels:
        return True
    return all(_looks_like_profile_noise(label) for label in labels)


def _looks_like_profile_noise(label: str) -> bool:
    value = label.strip().strip("\"'`()[]{}")
    if len(value) <= 1:
        return True
    compact = value.replace(" ", "")
    if _LONG_HEX_VALUE_RE.fullmatch(compact):
        return True
    if _COORDINATE_VALUE_RE.fullmatch(compact):
        return True
    if _URL_VALUE_RE.match(value):
        return True
    if _EMAIL_VALUE_RE.fullmatch(value):
        return True
    if _DOMAIN_VALUE_RE.fullmatch(value):
        return True
    if _PATH_VALUE_RE.search(value):
        return True
    return bool(_FILEISH_VALUE_RE.fullmatch(value))


def _object_slug(object_id: str) -> str:
    if ":" in object_id:
        return object_id.split(":", 1)[1]
    return object_id


def _safe_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", slug.lower())


def _rule_from_profile_spec(
    *,
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> GraphDerivedAssertionRule | None:
    source_predicates = _normalize_predicates(spec.get("source_predicates") or spec.get("source_predicate"))
    if not source_predicates or any(predicate not in PREDICATE_REGISTRY for predicate in source_predicates):
        logger.warning(
            "skipping invalid derived assertion spec predicate",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    if any(predicate not in profile.effective_structured_allowed_predicates for predicate in source_predicates):
        logger.warning(
            "skipping derived assertion spec outside profile predicates",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None

    trait_family = str(spec.get("trait_family") or "").strip().casefold()
    if (
        trait_family not in ASSERTION_FAMILY_ALLOWLIST
        or trait_family not in profile.allowed_assertion_families
    ):
        logger.warning(
            "skipping invalid derived assertion spec family",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None

    trait_name_template = str(spec.get("trait_name_template") or "").strip()
    if not trait_name_template or not _trait_template_allowed_by_profile(
        trait_name_template,
        profile.allowed_assertion_traits,
    ):
        logger.warning(
            "skipping derived assertion spec outside trait allowlist",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None

    source_types = _normalize_source_types(spec.get("source_types"), fallback=profile.source_types)
    if not source_types or not set(source_types).issubset(profile.source_types):
        logger.warning(
            "skipping derived assertion spec outside profile source_types",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None

    value_strategy = str(spec.get("value_strategy") or "canonical_name").strip()
    if value_strategy not in _VALUE_STRATEGIES:
        logger.warning(
            "skipping invalid derived assertion spec value_strategy",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None

    object_types = _normalize_object_types(spec.get("object_types"))
    if object_types:
        unknown_object_types = set(object_types) - ENTITY_TYPE_REGISTRY
        if unknown_object_types:
            logger.warning(
                "skipping derived assertion spec with unknown object types",
                profile_id=profile.profile_id,
                spec_index=index,
                object_types=sorted(unknown_object_types),
            )
            return None
        if not set(object_types).issubset(profile.effective_structured_allowed_entity_types):
            logger.warning(
                "skipping derived assertion spec outside profile object type allowlist",
                profile_id=profile.profile_id,
                spec_index=index,
                object_types=sorted(object_types),
            )
            return None

    return GraphDerivedAssertionRule(
        rule_id=str(spec.get("rule_id") or f"{profile.profile_id}.derived.{index}").strip(),
        source_predicates=source_predicates,
        source_types=source_types,
        trait_family=trait_family,
        trait_name_template=trait_name_template,
        min_observations=max(1, int(spec.get("min_observations") or 1)),
        min_distinct_days=max(0, int(spec.get("min_distinct_days") or 0)),
        source_domains=_normalize_source_domains(spec.get("source_domains")),
        value_strategy=value_strategy,
        object_types=object_types,
    )


def _normalize_predicates(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        return tuple()
    return tuple(str(item).strip().upper() for item in values if str(item).strip())


def _normalize_source_types(value: Any, *, fallback: frozenset[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = list(fallback)
    return tuple(str(item).strip().casefold() for item in values if str(item).strip())


def _normalize_source_domains(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = ["external_activity"]
    normalized = tuple(str(item).strip().casefold() for item in values if str(item).strip())
    return normalized or ("external_activity",)


def _normalize_object_types(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        return tuple()
    return tuple(str(item).strip().casefold() for item in values if str(item).strip())


def _trait_template_allowed_by_profile(
    trait_name_template: str,
    allowed_traits: frozenset[str] | None,
) -> bool:
    if allowed_traits is None:
        return False
    template = trait_name_template.casefold()
    for allowed in allowed_traits:
        pattern = str(allowed).strip().casefold()
        if pattern.endswith(".*") and template.startswith(pattern[:-1]):
            return True
        if "{" not in template and template == pattern:
            return True
    return False


__all__ = [
    "GraphDerivedAssertionRule",
    "build_graph_derived_rules_from_profiles",
    "builtin_interest_rule",
    "evaluate_graph_derived_assertion_rule",
]
