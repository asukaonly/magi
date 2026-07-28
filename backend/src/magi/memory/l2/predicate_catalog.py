"""Unified predicate catalog for L2 retrieval grounding.

Consolidates predicate definitions from ontology.py and ontology_aliases.py
into a single PredicateSpec model with derived lookup indexes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class PredicateSpec:
    """Complete specification for one canonical predicate."""
    canonical: str
    family: str
    synonym_group: str
    aliases: tuple[str, ...] = ()
    subject_types: tuple[str, ...] = ()
    object_types: tuple[str, ...] = ()
    answer_kinds: tuple[str, ...] = ()
    direction_hint: str = "outgoing"
    natural_labels: dict[str, str] = field(default_factory=dict)
    embedding_text: str = ""


# ---------------------------------------------------------------------------
# Spec definitions
# ---------------------------------------------------------------------------

_SPECS: list[PredicateSpec] = [
    PredicateSpec(
        canonical="LIKES",
        family="preference",
        synonym_group="affinity",
        aliases=("LIKE",),
        subject_types=("person",),
        object_types=(),
        answer_kinds=("creator", "place", "topic", "software", "food", "media"),
        direction_hint="outgoing",
        natural_labels={"en": "likes", "zh": "喜欢"},
        embedding_text="likes, enjoys, is fond of",
    ),
    PredicateSpec(
        canonical="DISLIKES",
        family="preference",
        synonym_group="aversion",
        aliases=("DISLIKE",),
        subject_types=("person",),
        object_types=(),
        answer_kinds=("creator", "place", "topic", "software", "food", "media"),
        direction_hint="outgoing",
        natural_labels={"en": "dislikes", "zh": "讨厌"},
        embedding_text="dislikes, does not like, hates",
    ),
    PredicateSpec(
        canonical="INTERESTED_IN",
        family="preference",
        synonym_group="affinity",
        aliases=("INTERESTED",),
        subject_types=("person",),
        object_types=(),
        answer_kinds=("topic", "software", "media"),
        direction_hint="outgoing",
        natural_labels={"en": "is interested in", "zh": "感兴趣"},
        embedding_text="is interested in, curious about",
    ),
    PredicateSpec(
        canonical="FOLLOWS",
        family="preference",
        synonym_group="follow",
        aliases=("FOLLOW", "SUBSCRIBED", "SUBSCRIBED_TO"),
        subject_types=("person",),
        object_types=("person", "presence", "media"),
        answer_kinds=("creator", "person"),
        direction_hint="outgoing",
        natural_labels={"en": "follows", "zh": "关注"},
        embedding_text="follows, subscribes to",
    ),
    PredicateSpec(
        canonical="VISITED",
        family="activity",
        synonym_group="visit",
        aliases=("VISIT",),
        subject_types=("person",),
        object_types=("place",),
        answer_kinds=("place",),
        direction_hint="outgoing",
        natural_labels={"en": "visited", "zh": "去过"},
        embedding_text="visited, went to, traveled to",
    ),
    PredicateSpec(
        canonical="VIEWED",
        family="activity",
        synonym_group="view",
        aliases=("VIEW", "WATCHED", "READ", "BROWSED"),
        subject_types=("person",),
        object_types=("media", "software"),
        answer_kinds=("media", "software"),
        direction_hint="outgoing",
        natural_labels={"en": "viewed", "zh": "看过"},
        embedding_text="viewed, watched, read, browsed",
    ),
    PredicateSpec(
        canonical="LISTENED",
        family="activity",
        synonym_group="view",
        aliases=("LISTEN_TO", "LISTENED_TO"),
        subject_types=("person",),
        object_types=("media",),
        answer_kinds=("media",),
        direction_hint="outgoing",
        natural_labels={"en": "listened to", "zh": "听过"},
        embedding_text="listened to, heard",
    ),
    PredicateSpec(
        canonical="ATTENDED",
        family="activity",
        synonym_group="visit",
        aliases=("ATTENDED_TO",),
        subject_types=("person",),
        object_types=("event", "activity"),
        answer_kinds=("event",),
        direction_hint="outgoing",
        natural_labels={"en": "attended", "zh": "参加过"},
        embedding_text="attended, participated in",
    ),
    PredicateSpec(
        canonical="USES",
        family="activity",
        synonym_group="usage",
        aliases=("USE",),
        subject_types=("person",),
        object_types=("software", "hardware", "technology"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "uses", "zh": "使用"},
        embedding_text="uses, works with, utilizes",
    ),
    PredicateSpec(
        canonical="USED",
        family="activity",
        synonym_group="usage",
        aliases=(),
        subject_types=("person",),
        object_types=("software", "hardware", "technology"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "used", "zh": "用过"},
        embedding_text="used, previously used",
    ),
    PredicateSpec(
        canonical="EXECUTED",
        family="activity",
        synonym_group="usage",
        aliases=(),
        subject_types=("person",),
        object_types=("software", "technology"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "executed", "zh": "执行过"},
        embedding_text="executed, ran",
    ),
    PredicateSpec(
        canonical="WORKS_WITH",
        family="relationship",
        synonym_group="coworker",
        aliases=(),
        subject_types=("person",),
        object_types=("person", "software", "technology"),
        answer_kinds=("person", "software"),
        direction_hint="outgoing",
        natural_labels={"en": "works with", "zh": "一起工作"},
        embedding_text="works with, collaborates with",
    ),
    PredicateSpec(
        canonical="COMMITTED",
        family="activity",
        synonym_group="code_activity",
        aliases=("COMMITTED_TO",),
        subject_types=("person",),
        object_types=("software", "project"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "committed to", "zh": "提交到"},
        embedding_text="committed code to, pushed to",
    ),
    PredicateSpec(
        canonical="CHECKED_OUT",
        family="activity",
        synonym_group="code_activity",
        aliases=(),
        subject_types=("person",),
        object_types=("software", "project"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "checked out", "zh": "检出"},
        embedding_text="checked out, switched to branch",
    ),
    PredicateSpec(
        canonical="MERGED",
        family="activity",
        synonym_group="code_activity",
        aliases=(),
        subject_types=("person",),
        object_types=("software", "project"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "merged", "zh": "合并"},
        embedding_text="merged, merged branch",
    ),
    PredicateSpec(
        canonical="REBASED",
        family="activity",
        synonym_group="code_activity",
        aliases=(),
        subject_types=("person",),
        object_types=("software", "project"),
        answer_kinds=("software",),
        direction_hint="outgoing",
        natural_labels={"en": "rebased", "zh": "变基"},
        embedding_text="rebased, rebased branch",
    ),
    PredicateSpec(
        canonical="LIVES_IN",
        family="profile_fact",
        synonym_group="location",
        aliases=("LIVES", "LOCATED_NEAR"),
        subject_types=("person",),
        object_types=("place",),
        answer_kinds=("place",),
        direction_hint="outgoing",
        natural_labels={"en": "lives in", "zh": "住在"},
        embedding_text="lives in, resides in, located at",
    ),
    PredicateSpec(
        canonical="WORKS_AT",
        family="profile_fact",
        synonym_group="membership",
        aliases=("WORKS_FOR", "EMPLOYED_BY"),
        subject_types=("person",),
        object_types=("organization",),
        answer_kinds=("person",),
        direction_hint="outgoing",
        natural_labels={"en": "works at", "zh": "在...工作"},
        embedding_text="works at, employed by",
    ),
    PredicateSpec(
        canonical="MEMBER_OF",
        family="profile_fact",
        synonym_group="membership",
        aliases=("MEMBER", "BELONGS_TO"),
        subject_types=("person",),
        object_types=("organization", "group"),
        answer_kinds=("person",),
        direction_hint="outgoing",
        natural_labels={"en": "member of", "zh": "属于"},
        embedding_text="member of, belongs to, part of",
    ),
    PredicateSpec(
        canonical="OWNS",
        family="profile_fact",
        synonym_group="ownership",
        aliases=("OWN", "OWNED"),
        subject_types=("person",),
        object_types=(),
        answer_kinds=(),
        direction_hint="outgoing",
        natural_labels={"en": "owns", "zh": "拥有"},
        embedding_text="owns, possesses",
    ),
    PredicateSpec(
        canonical="CREATES",
        family="profile_fact",
        synonym_group="creation",
        aliases=("CREATE", "CREATED", "MODIFIED", "MODIFIES", "EDITED"),
        subject_types=("person",),
        object_types=("software", "media", "project"),
        answer_kinds=("software", "media"),
        direction_hint="outgoing",
        natural_labels={"en": "creates", "zh": "创建"},
        embedding_text="creates, authored, made",
    ),
    PredicateSpec(
        canonical="PROFICIENT_IN",
        family="profile_fact",
        synonym_group="skill_level",
        aliases=(),
        subject_types=("person",),
        object_types=("skill", "technology"),
        answer_kinds=("skill",),
        direction_hint="outgoing",
        natural_labels={"en": "proficient in", "zh": "擅长"},
        embedding_text="proficient in, skilled at, expert in",
    ),
    PredicateSpec(
        canonical="KNOWS",
        family="relationship",
        synonym_group="acquaintance",
        aliases=("KNOW",),
        subject_types=("person",),
        object_types=("person",),
        answer_kinds=("person",),
        direction_hint="outgoing",
        natural_labels={"en": "knows", "zh": "认识"},
        embedding_text="knows, is acquainted with",
    ),
    PredicateSpec(
        canonical="FAMILY_OF",
        family="relationship",
        synonym_group="family",
        aliases=("RELATED_TO",),
        subject_types=("person",),
        object_types=("person",),
        answer_kinds=("person",),
        direction_hint="both",
        natural_labels={"en": "family of", "zh": "是...的家人"},
        embedding_text="family of, related to",
    ),
    PredicateSpec(
        canonical="INTERACTED_WITH",
        family="relationship",
        synonym_group="interaction",
        aliases=("INTERACT_WITH",),
        subject_types=("person",),
        object_types=("person",),
        answer_kinds=("person",),
        direction_hint="outgoing",
        natural_labels={"en": "interacted with", "zh": "交互过"},
        embedding_text="interacted with, communicated with",
    ),
    PredicateSpec(
        canonical="HAS_METRIC",
        family="profile_fact",
        synonym_group="metric",
        aliases=(),
        subject_types=("person",),
        object_types=("health_metric",),
        answer_kinds=(),
        direction_hint="outgoing",
        natural_labels={"en": "has metric", "zh": "指标"},
        embedding_text="health metric, measurement",
    ),
    PredicateSpec(
        canonical="ON_PLATFORM",
        family="topology",
        synonym_group="platform",
        aliases=(),
        subject_types=("presence",),
        object_types=("software",),
        answer_kinds=(),
        direction_hint="outgoing",
        natural_labels={"en": "on platform", "zh": "在平台上"},
        embedding_text="on platform, present on",
    ),
    PredicateSpec(
        canonical="PRESENCE_OF",
        family="topology",
        synonym_group="identity",
        aliases=(),
        subject_types=("presence",),
        object_types=("person", "organization", "group"),
        answer_kinds=(),
        direction_hint="outgoing",
        natural_labels={"en": "presence of", "zh": "是...的身份"},
        embedding_text="presence of, identity of, account of",
    ),
    PredicateSpec(
        canonical="LOCATED_IN",
        family="topology",
        synonym_group="location",
        aliases=("LOCATED",),
        subject_types=("place",),
        object_types=("place",),
        answer_kinds=("place",),
        direction_hint="outgoing",
        natural_labels={"en": "located in", "zh": "位于"},
        embedding_text="located in, situated in, part of",
    ),
    PredicateSpec(
        canonical="PLANS_TO",
        family="activity",
        synonym_group="intention",
        aliases=("PLAN_TO", "PLANNED", "WILL"),
        subject_types=("person",),
        object_types=(),
        answer_kinds=(),
        direction_hint="outgoing",
        natural_labels={"en": "plans to", "zh": "计划"},
        embedding_text="plans to, intends to, will",
    ),
    PredicateSpec(
        canonical="REFERENCES",
        family="reference",
        synonym_group="reference",
        aliases=(),
        subject_types=(),
        object_types=(),
        answer_kinds=("topic", "concept", "person", "software", "media"),
        direction_hint="outgoing",
        natural_labels={"en": "references", "zh": "引用"},
        embedding_text="references, links to, cites, refers to",
    ),
]

# ---------------------------------------------------------------------------
# Derived indexes (built at module load time)
# ---------------------------------------------------------------------------


def _build_indexes() -> Tuple[
    Dict[str, PredicateSpec],
    Dict[str, PredicateSpec],
    Dict[str, List[PredicateSpec]],
    Dict[str, List[PredicateSpec]],
]:
    by_canonical: Dict[str, PredicateSpec] = {}
    by_alias: Dict[str, PredicateSpec] = {}
    by_family: Dict[str, List[PredicateSpec]] = {}
    by_synonym_group: Dict[str, List[PredicateSpec]] = {}

    for spec in _SPECS:
        by_canonical[spec.canonical] = spec
        for alias in spec.aliases:
            by_alias[alias] = spec
        by_family.setdefault(spec.family, []).append(spec)
        by_synonym_group.setdefault(spec.synonym_group, []).append(spec)

    return by_canonical, by_alias, by_family, by_synonym_group


SPEC_BY_CANONICAL, SPEC_BY_ALIAS, SPECS_BY_FAMILY, SPECS_BY_SYNONYM_GROUP = _build_indexes()


# ---------------------------------------------------------------------------
# Public lookup API
# ---------------------------------------------------------------------------


def get_spec(predicate: str) -> PredicateSpec | None:
    """Look up a PredicateSpec by canonical name or alias."""
    upper = predicate.strip().upper()
    spec = SPEC_BY_CANONICAL.get(upper)
    if spec is not None:
        return spec
    return SPEC_BY_ALIAS.get(upper)


def resolve_predicate(raw: str) -> str | None:
    """Resolve a raw predicate string to its canonical form via the catalog."""
    spec = get_spec(raw)
    return spec.canonical if spec is not None else None


def get_family_predicates(family: str) -> list[str]:
    """Return all canonical predicates in a family."""
    specs = SPECS_BY_FAMILY.get(family, [])
    return [s.canonical for s in specs]


def get_synonym_group_predicates(group: str) -> list[str]:
    """Return all canonical predicates in a synonym group."""
    specs = SPECS_BY_SYNONYM_GROUP.get(group, [])
    return [s.canonical for s in specs]


def expand_predicates_via_catalog(predicates: list[str]) -> list[str]:
    """Expand predicates to include all synonyms from the same synonym group."""
    expanded: set[str] = set()
    groups_seen: set[str] = set()
    for pred in predicates:
        spec = get_spec(pred)
        if spec is not None:
            expanded.add(spec.canonical)
            groups_seen.add(spec.synonym_group)
        else:
            expanded.add(pred.strip().upper())
    for group in groups_seen:
        for p in get_synonym_group_predicates(group):
            expanded.add(p)
    return sorted(expanded)


def get_natural_label(predicate: str, lang: str = "en") -> str | None:
    """Return the human-readable label for a predicate in the given language."""
    spec = get_spec(predicate)
    if spec is None:
        return None
    return spec.natural_labels.get(lang)


def get_compatible_object_types(predicate: str) -> tuple[str, ...] | None:
    """Return allowed object types for a predicate, or None if unrestricted."""
    spec = get_spec(predicate)
    if spec is None:
        return None
    return spec.object_types if spec.object_types else None


def get_answer_kinds(predicate: str) -> tuple[str, ...]:
    """Return the answer kinds associated with a predicate."""
    spec = get_spec(predicate)
    if spec is None:
        return ()
    return spec.answer_kinds


ALL_SPECS = list(_SPECS)


__all__ = [
    "PredicateSpec",
    "ALL_SPECS",
    "SPEC_BY_CANONICAL",
    "SPEC_BY_ALIAS",
    "SPECS_BY_FAMILY",
    "SPECS_BY_SYNONYM_GROUP",
    "get_spec",
    "resolve_predicate",
    "get_family_predicates",
    "get_synonym_group_predicates",
    "expand_predicates_via_catalog",
    "get_natural_label",
    "get_compatible_object_types",
    "get_answer_kinds",
]
