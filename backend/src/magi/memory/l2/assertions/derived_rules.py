"""Graph-derived assertion rule evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
import time
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, cast

from ....core.logger import get_logger
from ....identity.defaults import CANONICAL_LOCAL_USER
from ..entities.catalog.lookup import get_canonical_names
from ..ontology import ASSERTION_FAMILY_ALLOWLIST, ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY
from ..phase1_models import L2TemporalCue
from .promotion import (
    AssertionPromotionInput,
    PromotionHorizon,
    SourceStrengthPreset,
    evaluate_assertion_promotion,
)

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
    def effective_structured_allowed_predicates(self) -> frozenset[str]: ...

    @property
    def effective_structured_allowed_entity_types(self) -> frozenset[str]: ...


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
    signal_preset: SourceStrengthPreset | str = SourceStrengthPreset.PASSIVE_EXPOSURE
    durable_permitted: bool = False
    durable_min_observations: int = 6
    durable_min_distinct_days: int = 3
    durable_min_span_days: float = 14.0

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
        object.__setattr__(
            self, "value_strategy", str(self.value_strategy).strip() or "canonical_name"
        )
        object.__setattr__(
            self,
            "object_types",
            tuple(
                str(object_type).strip().casefold()
                for object_type in self.object_types
                if str(object_type).strip()
            ),
        )
        object.__setattr__(
            self,
            "signal_preset",
            SourceStrengthPreset.from_value(self.signal_preset),
        )
        object.__setattr__(self, "durable_permitted", bool(self.durable_permitted))
        object.__setattr__(
            self,
            "durable_min_observations",
            max(1, int(self.durable_min_observations or 1)),
        )
        object.__setattr__(
            self,
            "durable_min_distinct_days",
            max(1, int(self.durable_min_distinct_days or 1)),
        )
        object.__setattr__(
            self,
            "durable_min_span_days",
            max(0.0, float(self.durable_min_span_days or 0.0)),
        )


@dataclass(slots=True, frozen=True)
class _EdgeCandidateContext:
    object_id: str
    object_type: str
    predicate: str
    raw_object_slug: str
    object_slug: str


@dataclass(slots=True, frozen=True)
class _EdgeEvidenceStats:
    event_ids: tuple[str, ...]
    observation_count: int
    evidence_count: int
    distinct_days: int
    first_observed_at: float
    last_observed_at: float
    span_days: float
    recency_days: float | None


def builtin_interest_rule(*, min_observations: int = 3) -> GraphDerivedAssertionRule:
    """Return the host fallback rule for recent profile-worthy interests."""
    return GraphDerivedAssertionRule(
        rule_id="builtin.interested_in",
        source_predicates=("INTERESTED_IN",),
        trait_family="interest_profile",
        trait_name_template="interest.{object_slug}",
        min_observations=min_observations,
        min_distinct_days=_PROFILE_INTEREST_MIN_DISTINCT_DAYS,
        source_domains=("external_activity",),
        value_strategy="canonical_name",
        object_types=_PROFILE_INTEREST_OBJECT_TYPES,
        signal_preset=SourceStrengthPreset.PASSIVE_EXPOSURE,
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
    l1_store: Any,
    entity_id: str = _DEFAULT_USER_ENTITY_ID,
    entity_type: str = "user",
    limit: int = 500,
    now: float | None = None,
) -> dict[str, int]:
    """Evaluate one graph-derived assertion rule and persist matching assertions."""
    edges, edges_seen = await _fetch_rule_edges(
        store=store,
        rule=rule,
        entity_id=entity_id,
        limit=limit,
    )
    evaluation_time = float(now if now is not None else time.time())
    evidence_stats = await _load_edge_evidence_stats(
        edges=edges,
        l1_store=l1_store,
        now=evaluation_time,
    )
    qualifying = _qualifying_edges(
        edges=edges,
        rule=rule,
        evidence_stats=evidence_stats,
    )
    if not qualifying:
        _log_no_qualifying_edges(rule=rule, entity_id=entity_id, edges_seen=edges_seen)
        return {"edges_seen": edges_seen, "assertions_written": 0}

    object_ids = [str(edge.get("object_id") or "") for edge in qualifying]
    canonical_names = await get_canonical_names(store.db_path, object_ids)
    assertions_written = await _write_derived_assertion_candidates(
        store=store,
        rule=rule,
        entity_id=entity_id,
        entity_type=entity_type,
        qualifying=qualifying,
        canonical_names=canonical_names,
        evidence_stats=evidence_stats,
    )
    _log_rule_completed(
        rule=rule,
        entity_id=entity_id,
        edges_seen=edges_seen,
        assertions_written=assertions_written,
    )
    return {"edges_seen": edges_seen, "assertions_written": assertions_written}


async def _fetch_rule_edges(
    *,
    store: Any,
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
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
    return edges, edges_seen


def _qualifying_edges(
    *,
    edges: list[dict[str, Any]],
    rule: GraphDerivedAssertionRule,
    evidence_stats: dict[str, _EdgeEvidenceStats],
) -> list[dict[str, Any]]:
    return [
        edge
        for edge in edges
        if _edge_meets_rule(
            edge=edge,
            rule=rule,
            evidence_stats=evidence_stats.get(_edge_key(edge)),
        )
    ]


async def _load_edge_evidence_stats(
    *,
    edges: list[dict[str, Any]],
    l1_store: Any,
    now: float,
) -> dict[str, _EdgeEvidenceStats]:
    event_ids = _unique_edge_event_ids(edges)
    timestamps = await l1_store.get_event_timestamps(event_ids)
    return {
        _edge_key(edge): _evidence_stats_for_edge(
            edge,
            timestamps=timestamps,
            now=now,
        )
        for edge in edges
    }


def _unique_edge_event_ids(edges: list[dict[str, Any]]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        for raw_event_id in edge.get("evidence_event_ids") or []:
            event_id = str(raw_event_id or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            unique.append(event_id)
    return unique


def _evidence_stats_for_edge(
    edge: dict[str, Any],
    *,
    timestamps: Mapping[str, float],
    now: float,
) -> _EdgeEvidenceStats:
    event_times = [
        (str(raw_event_id), float(timestamps[str(raw_event_id)]))
        for raw_event_id in edge.get("evidence_event_ids") or []
        if str(raw_event_id) in timestamps and float(timestamps[str(raw_event_id)]) > 0
    ]
    event_times.sort(key=lambda item: (item[1], item[0]))
    if not event_times:
        return _EdgeEvidenceStats(
            event_ids=(),
            observation_count=int(edge.get("observation_count", 0) or 0),
            evidence_count=0,
            distinct_days=0,
            first_observed_at=0.0,
            last_observed_at=0.0,
            span_days=0.0,
            recency_days=None,
        )
    ordered_times = [timestamp for _event_id, timestamp in event_times]
    distinct_days = {
        (time.localtime(timestamp).tm_year, time.localtime(timestamp).tm_yday)
        for timestamp in ordered_times
    }
    first_observed_at = ordered_times[0]
    last_observed_at = ordered_times[-1]
    return _EdgeEvidenceStats(
        event_ids=tuple(event_id for event_id, _timestamp in event_times),
        observation_count=int(edge.get("observation_count", 0) or 0),
        evidence_count=len(event_times),
        distinct_days=len(distinct_days),
        first_observed_at=first_observed_at,
        last_observed_at=last_observed_at,
        span_days=max(0.0, (last_observed_at - first_observed_at) / 86_400),
        recency_days=max(0.0, (now - last_observed_at) / 86_400),
    )


def _edge_key(edge: Mapping[str, Any]) -> str:
    triple_id = str(edge.get("triple_id") or "").strip()
    if triple_id:
        return triple_id
    return "\x1f".join(
        str(edge.get(field) or "").strip()
        for field in ("subject_id", "predicate", "object_id", "source_type")
    )


def _log_no_qualifying_edges(
    *,
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    edges_seen: int,
) -> None:
    logger.debug(
        "graph-derived assertion rule had no qualifying edges",
        rule_id=rule.rule_id,
        entity_id=entity_id,
        edges_seen=edges_seen,
    )


async def _write_derived_assertion_candidates(
    *,
    store: Any,
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    entity_type: str,
    qualifying: list[dict[str, Any]],
    canonical_names: dict[str, str],
    evidence_stats: dict[str, _EdgeEvidenceStats],
) -> int:
    assertions_written = 0
    for edge in qualifying:
        candidate = _candidate_from_edge(
            edge=edge,
            rule=rule,
            entity_id=entity_id,
            entity_type=entity_type,
            canonical_names=canonical_names,
            evidence_stats=evidence_stats[_edge_key(edge)],
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
    return assertions_written


def _log_rule_completed(
    *,
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    edges_seen: int,
    assertions_written: int,
) -> None:
    logger.info(
        "graph-derived assertion rule completed",
        rule_id=rule.rule_id,
        entity_id=entity_id,
        edges_seen=edges_seen,
        assertions_written=assertions_written,
    )


def _edge_meets_rule(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
    evidence_stats: _EdgeEvidenceStats | None,
) -> bool:
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
    if evidence_stats is None:
        return False
    return bool(
        evidence_stats.evidence_count >= rule.min_observations
        and evidence_stats.distinct_days >= max(1, rule.min_distinct_days)
    )


def _candidate_from_edge(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    entity_type: str,
    canonical_names: dict[str, str],
    evidence_stats: _EdgeEvidenceStats,
) -> dict[str, Any] | None:
    context = _edge_candidate_context(edge=edge, rule=rule)
    if context is None:
        return None
    trait_value = _trait_value_for_edge(
        edge=edge,
        rule=rule,
        object_id=context.object_id,
        object_slug=context.raw_object_slug,
        canonical_names=canonical_names,
    )
    if _is_low_quality_profile_value(
        raw_slug=context.raw_object_slug,
        trait_value=trait_value,
    ):
        logger.debug(
            "graph-derived assertion rule skipped low-quality profile value",
            rule_id=rule.rule_id,
            object_id=context.object_id,
            trait_value=trait_value,
        )
        return None
    return _build_derived_assertion_candidate(
        edge=edge,
        rule=rule,
        entity_id=entity_id,
        entity_type=entity_type,
        context=context,
        trait_value=trait_value,
        evidence_stats=evidence_stats,
    )


def _edge_candidate_context(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
) -> _EdgeCandidateContext | None:
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
    return _EdgeCandidateContext(
        object_id=object_id,
        object_type=object_type,
        predicate=predicate,
        raw_object_slug=raw_slug,
        object_slug=slug,
    )


def _trait_name_for_edge(
    *,
    rule: GraphDerivedAssertionRule,
    context: _EdgeCandidateContext,
) -> str:
    return rule.trait_name_template.format(
        object_id=context.object_id,
        object_type=context.object_type,
        object_slug=context.object_slug,
        raw_object_slug=context.raw_object_slug,
        predicate=context.predicate,
    )


def _confidence_for_edge(edge: dict[str, Any], *, evidence_count: int) -> float:
    return min(
        0.9,
        float(edge.get("confidence", 0.5) or 0.5)
        * (1 + 0.1 * min(evidence_count, 5)),
    )


def _build_derived_assertion_candidate(
    *,
    edge: dict[str, Any],
    rule: GraphDerivedAssertionRule,
    entity_id: str,
    entity_type: str,
    context: _EdgeCandidateContext,
    trait_value: str,
    evidence_stats: _EdgeEvidenceStats,
) -> dict[str, Any] | None:
    trait_name = _trait_name_for_edge(
        rule=rule,
        context=context,
    )
    source_domain = rule.source_domains[0] if rule.source_domains else "external_activity"
    promotion = evaluate_assertion_promotion(
        AssertionPromotionInput(
            trait_family=rule.trait_family,
            fact_kind="interaction_evidence",
            predicate=context.predicate,
            evidence_class=(
                "external_observation"
                if source_domain == "external_activity"
                else "unknown"
            ),
            temporal_cue=L2TemporalCue.UNSPECIFIED,
            source_strength=rule.signal_preset,
            observation_count=evidence_stats.observation_count,
            evidence_count=evidence_stats.evidence_count,
            distinct_days=evidence_stats.distinct_days,
            span_days=evidence_stats.span_days,
            recency_days=evidence_stats.recency_days,
            durable_permitted=rule.durable_permitted,
            recent_min_observations=rule.min_observations,
            recent_min_evidence=rule.min_observations,
            recent_min_distinct_days=max(1, rule.min_distinct_days),
            durable_min_observations=rule.durable_min_observations,
            durable_min_evidence=rule.durable_min_observations,
            durable_min_distinct_days=rule.durable_min_distinct_days,
            durable_min_span_days=rule.durable_min_span_days,
        )
    )
    if promotion.horizon is PromotionHorizon.EVENT_ONLY:
        return None
    expiry = promotion.expiry
    expires_at = (
        evidence_stats.last_observed_at + expiry.ttl_seconds
        if expiry.ttl_seconds is not None
        else None
    )

    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "trait_family": rule.trait_family,
        "trait_name": trait_name,
        "trait_value": trait_value,
        "confidence_score": _confidence_for_edge(
            edge,
            evidence_count=evidence_stats.evidence_count,
        ),
        "evidence_events": list(evidence_stats.event_ids),
        "volatility_index": (
            0.7 if promotion.horizon is PromotionHorizon.RECENT else 0.2
        ),
        "source_domain": source_domain,
        "inference_depth": "topology_only",
        "validation_state": "tentative",
        "first_inferred_at": evidence_stats.first_observed_at,
        "last_validated_at": evidence_stats.last_observed_at,
        "target_entity_id": context.object_id,
        "target_entity_type": context.object_type,
        "target_scope": "entity_bound",
        "temporal_scope": expiry.temporal_scope,
        "decay_policy": expiry.decay_policy,
        "decay_anchor_at": evidence_stats.last_observed_at,
        "expires_at": expires_at,
        "memory_subdomain": (
            "state" if promotion.horizon is PromotionHorizon.RECENT else "semantic"
        ),
        "natural_summary": f"Recurring {context.predicate.lower()} signal for {trait_value}",
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
    labels = [str(label).strip() for label in (trait_value, raw_slug) if str(label).strip()]
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
    source_predicates = _profile_rule_source_predicates(profile, spec, index)
    if not source_predicates:
        return None
    trait_family = _profile_rule_trait_family(profile, spec, index)
    if trait_family is None:
        return None
    trait_name_template = _profile_rule_trait_name_template(profile, spec, index)
    if trait_name_template is None:
        return None
    source_types = _profile_rule_source_types(profile, spec, index)
    if not source_types:
        return None
    value_strategy = _profile_rule_value_strategy(profile, spec, index)
    if value_strategy is None:
        return None
    object_types = _profile_rule_object_types(profile, spec, index)
    if object_types is None:
        return None
    signal_preset = _profile_rule_signal_preset(profile, spec, index)
    if signal_preset is None:
        return None
    durable_permitted = bool(spec.get("durable_permitted", False))
    if (
        durable_permitted
        and signal_preset is SourceStrengthPreset.PASSIVE_EXPOSURE
    ):
        logger.warning(
            "skipping passive derived assertion spec with durable promotion",
            profile_id=profile.profile_id,
            spec_index=index,
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
        signal_preset=signal_preset,
        durable_permitted=durable_permitted,
        durable_min_observations=max(
            1,
            int(spec.get("durable_min_observations") or 6),
        ),
        durable_min_distinct_days=max(
            1,
            int(spec.get("durable_min_distinct_days") or 3),
        ),
        durable_min_span_days=max(
            0.0,
            float(spec.get("durable_min_span_days") or 14.0),
        ),
    )


def _profile_rule_signal_preset(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> SourceStrengthPreset | None:
    raw_preset = str(spec.get("signal_preset") or "passive_exposure").strip()
    try:
        preset = SourceStrengthPreset.from_value(raw_preset)
    except ValueError:
        logger.warning(
            "skipping derived assertion spec with invalid signal preset",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    if preset in {SourceStrengthPreset.AUTO, SourceStrengthPreset.DIRECT_USER}:
        logger.warning(
            "skipping derived assertion spec with host-reserved signal preset",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    return preset


def _profile_rule_source_predicates(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> tuple[str, ...] | None:
    source_predicates = _normalize_predicates(
        spec.get("source_predicates") or spec.get("source_predicate")
    )
    if not source_predicates or any(
        predicate not in PREDICATE_REGISTRY for predicate in source_predicates
    ):
        logger.warning(
            "skipping invalid derived assertion spec predicate",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    if any(
        predicate not in profile.effective_structured_allowed_predicates
        for predicate in source_predicates
    ):
        logger.warning(
            "skipping derived assertion spec outside profile predicates",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    return source_predicates


def _profile_rule_trait_family(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> str | None:
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
    return trait_family


def _profile_rule_trait_name_template(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> str | None:
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
    return trait_name_template


def _profile_rule_source_types(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> tuple[str, ...] | None:
    source_types = _normalize_source_types(spec.get("source_types"), fallback=profile.source_types)
    if not source_types or not set(source_types).issubset(profile.source_types):
        logger.warning(
            "skipping derived assertion spec outside profile source_types",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    return source_types


def _profile_rule_value_strategy(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> str | None:
    value_strategy = str(spec.get("value_strategy") or "canonical_name").strip()
    if value_strategy not in _VALUE_STRATEGIES:
        logger.warning(
            "skipping invalid derived assertion spec value_strategy",
            profile_id=profile.profile_id,
            spec_index=index,
        )
        return None
    return value_strategy


def _profile_rule_object_types(
    profile: _DerivedAssertionProfile,
    spec: dict[str, Any],
    index: int,
) -> tuple[str, ...] | None:
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

    return object_types


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
