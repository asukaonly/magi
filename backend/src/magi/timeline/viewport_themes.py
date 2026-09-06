"""Theme card assembly for the timeline viewport.

Extracted from viewport_builder.py to keep that file navigable. The
"themes row" chip set is one of the more involved derivations — it
pulls entity_ids out of episode clusters, ranks by frequency, resolves
to canonical names, applies a quality filter, and falls back to L3
reflection titles + cluster labels when entity coverage is sparse.

The class is instantiated once per ViewportBuilder and called per
viewport-build. Stateless across calls.

Behavior of this module must remain identical to the pre-extraction
inline code in viewport_builder.py — only the file boundary changed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

# Maximum chars allowed in a theme chip title. Above this we treat the
# string as a summary sentence that leaked into the title slot and drop
# it. 20 is the sweet spot — comfortably above multi-word project names
# ("Recurring Project", "sleep agency 论文") but well under sentence
# length.
MAX_THEME_TITLE_LEN = 20

# Title suffixes that indicate an internal L3 insight_key (e.g.
# "Day反思", "Week反思") rather than a user-facing label. Filtered out
# of the chip row.
BAD_THEME_TITLE_SUFFIXES: tuple[str, ...] = ("反思", "总结", "summary", "Summary")

# Source-telemetry-style entity names that source plugins create as
# parent buckets for their events ("Chrome 历史" → all browsing events).
# These are catalog entries but are not "things the user cares about"
# — they're internal categorization. Filtered out of theme chips.
BAD_THEME_TITLE_EXACT: frozenset[str] = frozenset(
    {
        "Chrome 历史",
        "chrome 历史",
        "应用使用情况",
        "应用使用",
        "屏幕使用",
        "屏幕活动",
        "屏幕时间",
        "系统媒体",
        "Application Usage",
        "Screen Time",
        "Chrome History",
    }
)

# Minimum number of distinct episode clusters an entity must appear in
# before it's promoted to a theme chip. A one-off mention is rarely
# "what you cared about" — recurring mentions are.
MIN_THEME_EPISODE_COUNT = 2

MAX_THEME_CARDS = 5


@dataclass(frozen=True)
class EntityThemeIndex:
    counts: Counter[str]
    clusters_by_entity: dict[str, list[dict[str, Any]]]


def is_acceptable_theme_title(title: str) -> bool:
    """Whether a string is fit to render as a theme chip.

    Themes are short noun phrases — names, projects, articles. Reject:
      - Empty / whitespace
      - Longer than MAX_THEME_TITLE_LEN (sentence-shaped data leak)
      - Ends in a known internal-key suffix ("Day反思" etc.)
      - In the exact-match blacklist of source-bucket names
    """
    stripped = title.strip()
    if not stripped or len(stripped) > MAX_THEME_TITLE_LEN:
        return False
    if stripped in BAD_THEME_TITLE_EXACT:
        return False
    for suffix in BAD_THEME_TITLE_SUFFIXES:
        if stripped.endswith(suffix):
            return False
    return True


def cluster_anchor(cluster: dict[str, Any]) -> dict[str, Any]:
    """Build the `anchor` sub-dict for a theme card pointing at a cluster.

    Anchor lets the frontend "click a chip → jump to the originating
    moment". Episode-backed clusters get an episode anchor; transient
    clusters get an event anchor pointing at their representatives.
    """
    episode_id = str(cluster.get("episode_id") or "")
    representative_ids = [
        str(event_id)
        for event_id in cluster.get("representative_event_ids") or []
        if str(event_id).strip()
    ]
    if episode_id:
        anchor_type = "episode"
        anchor_id = f"episode:{episode_id}"
    elif representative_ids:
        anchor_type = "event"
        anchor_id = representative_ids[0]
    else:
        anchor_type = "cluster"
        anchor_id = str(cluster.get("block_id") or "")
    return {
        "anchor_type": anchor_type,
        "anchor_id": anchor_id,
        "representative_event_ids": representative_ids[:5],
        # Both `episode_id` and the time_end-fallback-to-time_start are
        # required for byte-identical parity with the pre-extraction
        # implementation — the frontend treats `episode_id: null` as a
        # signal that anchor_type is non-episode, and clusters built
        # from a single event have time_end == time_start.
        "episode_id": episode_id or None,
        "time_start": float(cluster.get("time_start") or 0.0),
        "time_end": float(cluster.get("time_end") or cluster.get("time_start") or 0.0),
    }


def source_types_for_event_ids(
    event_ids: list[str],
    clusters: list[dict[str, Any]],
) -> list[str]:
    """Which source_types do the clusters containing these event_ids cover?

    Used to attach source-type tags to a theme card derived from L3
    reflections (where source_types aren't stored directly but can be
    inferred from the events that contributed to the reflection).
    """
    event_id_set = set(event_ids)
    source_types: list[str] = []
    if not event_id_set:
        return source_types
    for cluster in clusters:
        representative_ids = {
            str(event_id) for event_id in cluster.get("representative_event_ids") or []
        }
        if not (representative_ids & event_id_set):
            continue
        source_types.extend(
            str(source) for source in cluster.get("source_types") or [] if str(source).strip()
        )
    return list(dict.fromkeys(source_types))


def reflection_theme_cards(
    *,
    reflections: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    seen_titles: set[str],
    existing_count: int,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for reflection in reflections:
        if existing_count + len(cards) >= MAX_THEME_CARDS:
            break
        title = str(reflection.get("title") or "").strip()
        if not _reserve_theme_title(title, seen_titles):
            continue
        cards.append(_reflection_theme_card(reflection, title, clusters))
    return cards


def cluster_label_theme_cards(
    *,
    clusters: list[dict[str, Any]],
    seen_titles: set[str],
    existing_count: int,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for cluster in _clusters_by_event_count(clusters):
        if existing_count + len(cards) >= MAX_THEME_CARDS:
            break
        if not cluster.get("label_is_themeable"):
            continue
        title = str(cluster.get("label") or "").strip()
        if not _reserve_theme_title(title, seen_titles):
            continue
        cards.append(_cluster_label_theme_card(cluster, title, existing_count + len(cards)))
    return cards


def _reserve_theme_title(title: str, seen_titles: set[str]) -> bool:
    if not is_acceptable_theme_title(title):
        return False
    normalized = title.casefold()
    if normalized in seen_titles:
        return False
    seen_titles.add(normalized)
    return True


def _reflection_theme_card(
    reflection: dict[str, Any],
    title: str,
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    event_ids = [
        str(event_id)
        for event_id in reflection.get("source_event_ids") or []
        if str(event_id).strip()
    ]
    return {
        "theme_id": f"reflection:{reflection.get('reflection_id')}",
        "title": title,
        "summary": str(reflection.get("summary") or ""),
        "source_types": source_types_for_event_ids(event_ids, clusters),
        "event_count": len(event_ids),
        "anchor": {
            "anchor_type": "event" if event_ids else "reflection",
            "anchor_id": event_ids[0] if event_ids else "",
            "representative_event_ids": event_ids[:5],
            "time_start": float(reflection.get("time_start") or 0.0),
            "time_end": float(reflection.get("time_end") or 0.0),
        },
    }


def _cluster_label_theme_card(
    cluster: dict[str, Any],
    title: str,
    fallback_index: int,
) -> dict[str, Any]:
    return {
        "theme_id": str(cluster.get("block_id") or f"cluster:{fallback_index}"),
        "title": title,
        "summary": str(cluster.get("summary") or ""),
        "source_types": [str(s) for s in cluster.get("source_types") or [] if str(s).strip()],
        "event_count": int(cluster.get("event_count") or 0),
        "anchor": cluster_anchor(cluster),
    }


def _clusters_by_event_count(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        clusters,
        key=lambda item: int(item.get("event_count") or 0),
        reverse=True,
    )


class ThemeCardBuilder:
    """Per-viewport assembly of the "你那时关心的" chip row.

    Priority order:
      1. Entity catalog — aggregate primary_entity_ids across the
         window's episode clusters, resolve to canonical_names. Yields
         concrete nouns ("Anthropic", "sleep agency") the user actually
         touched.
      2. L3 reflection titles (quality-filtered) — fallback when entity
         data is sparse.
      3. Cluster labels (quality-filtered) — last resort. Tends to
         surface abstract source names ("screen_time"); kept only when
         nothing better is available.

    At each step we stop once we have MAX_THEME_CARDS unique cards.
    """

    def __init__(self, *, entity_catalog: Any | None = None) -> None:
        self._entity_catalog = entity_catalog

    async def build(
        self,
        *,
        reflections: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        locale: str,  # noqa: ARG002 — accepted for future localization
    ) -> list[dict[str, Any]]:
        cards = await self._collect_entity_themes(clusters=clusters)
        if len(cards) >= MAX_THEME_CARDS:
            return cards

        seen_titles: set[str] = {str(c["title"]).casefold() for c in cards}
        cards.extend(
            reflection_theme_cards(
                reflections=reflections,
                clusters=clusters,
                seen_titles=seen_titles,
                existing_count=len(cards),
            )
        )
        if len(cards) >= MAX_THEME_CARDS:
            return cards

        cards.extend(
            cluster_label_theme_cards(
                clusters=clusters,
                seen_titles=seen_titles,
                existing_count=len(cards),
            )
        )

        return cards

    async def _collect_entity_themes(
        self,
        *,
        clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Aggregate entity_ids from episode clusters and resolve canonical names.

        Episode-style cluster ``keywords`` carry up to 4 entity_ids each
        (set by ``TimelineClusterBuilder._episode_to_cluster``).
        Transient clusters' keywords are tag strings — those get skipped
        here and handled later in the reflection/cluster fallback.

        Returns up to ``MAX_THEME_CARDS`` cards, one per top-frequency
        entity. Returns empty list when no entity catalog is configured,
        no episode clusters have entities, or none of the resolved names
        pass the quality filter.
        """
        if self._entity_catalog is None:
            return []

        index = _index_entity_theme_clusters(clusters)
        ranked_ids = _rank_eligible_entity_ids(index)
        if not ranked_ids:
            return []

        name_by_id = await self._resolve_entity_names(ranked_ids[: MAX_THEME_CARDS * 2])
        if not name_by_id:
            return []

        return _build_entity_theme_cards(
            ranked_ids=ranked_ids,
            index=index,
            name_by_id=name_by_id,
        )

    async def _resolve_entity_names(self, entity_ids: list[str]) -> dict[str, str]:
        try:
            resolved = await self._entity_catalog.list_entities(
                entity_ids=entity_ids,
                limit=len(entity_ids),
            )
        except Exception:
            return {}
        return {
            str(entity.get("entity_id") or ""): str(entity.get("canonical_name") or "").strip()
            for entity in resolved
        }


def _index_entity_theme_clusters(clusters: list[dict[str, Any]]) -> EntityThemeIndex:
    entity_id_counts: Counter[str] = Counter()
    clusters_by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for cluster in clusters:
        block_id = str(cluster.get("block_id") or "")
        if not block_id.startswith("episode:"):
            continue
        weight = max(1, int(cluster.get("event_count") or 1))
        for entity_id in cluster.get("keywords") or []:
            eid = str(entity_id).strip()
            if not eid:
                continue
            entity_id_counts[eid] += weight
            clusters_by_entity[eid].append(cluster)

    return EntityThemeIndex(
        counts=entity_id_counts,
        clusters_by_entity=dict(clusters_by_entity),
    )


def _rank_eligible_entity_ids(index: EntityThemeIndex) -> list[str]:
    eligible_ids = [
        eid
        for eid, _ in index.counts.items()
        if len(index.clusters_by_entity[eid]) >= MIN_THEME_EPISODE_COUNT
    ]
    return sorted(eligible_ids, key=lambda eid: index.counts[eid], reverse=True)


def _build_entity_theme_cards(
    *,
    ranked_ids: list[str],
    index: EntityThemeIndex,
    name_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for entity_id in ranked_ids:
        if len(cards) >= MAX_THEME_CARDS:
            break
        name = name_by_id.get(entity_id, "").strip()
        if not is_acceptable_theme_title(name) or name.casefold() in seen_names:
            continue
        seen_names.add(name.casefold())
        cards.append(_build_entity_theme_card(entity_id, name, index))
    return cards


def _build_entity_theme_card(
    entity_id: str,
    name: str,
    index: EntityThemeIndex,
) -> dict[str, Any]:
    anchor_clusters = index.clusters_by_entity.get(entity_id) or []
    return {
        "theme_id": f"entity:{entity_id}",
        "title": name,
        "summary": "",
        "source_types": _source_types_for_clusters(anchor_clusters),
        "event_count": int(index.counts[entity_id]),
        "anchor": _entity_anchor(entity_id, anchor_clusters),
    }


def _source_types_for_clusters(clusters: list[dict[str, Any]]) -> list[str]:
    source_types: list[str] = []
    for cluster in clusters:
        for source in cluster.get("source_types") or []:
            if str(source).strip() and str(source) not in source_types:
                source_types.append(str(source))
    return source_types


def _entity_anchor(
    entity_id: str,
    clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    if clusters:
        return cluster_anchor(clusters[0])
    return {
        "anchor_type": "entity",
        "anchor_id": f"entity:{entity_id}",
        "representative_event_ids": [],
        "time_start": 0.0,
        "time_end": 0.0,
    }
