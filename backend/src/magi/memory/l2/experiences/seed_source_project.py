"""Project-anchor seed discovery for L2 experiences."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from .seed_anchors import _project_anchor_items, _seed_id
from .seed_models import ExperienceSeedDiscoveryStats
from .seed_writes import _create_seed_if_missing


async def _discover_project_seeds(
    store: Any,
    episodes: Sequence[dict[str, Any]],
) -> ExperienceSeedDiscoveryStats:
    anchor_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    anchor_labels: dict[str, str] = {}
    generic_seen = 0
    for episode in episodes:
        concrete_items = _project_anchor_items(episode)
        if not concrete_items and (
            episode.get("primary_entity_ids")
            or episode.get("primary_place_ids")
            or episode.get("primary_topic_keys")
        ):
            generic_seen += 1
        for raw, label in concrete_items:
            anchor_groups[raw].append(episode)
            anchor_labels[raw] = label

    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []
    for anchor, grouped in sorted(anchor_groups.items()):
        if len(grouped) < 2:
            continue
        candidates += 1
        sorted_group = sorted(grouped, key=lambda item: float(item["time_start"]))
        episode_ids = [str(episode["episode_id"]) for episode in sorted_group]
        seed_id = _seed_id("project", anchor)
        was_created, _ = await _create_seed_if_missing(
            store,
            seed_id=seed_id,
            seed_type="project",
            status="candidate",
            title=anchor_labels[anchor],
            description=f"Repeated activity around {anchor_labels[anchor]}.",
            anchor_entity_ids=[anchor],
            time_start=min(float(episode["time_start"]) for episode in sorted_group),
            time_end=max(float(episode["time_end"]) for episode in sorted_group),
            confidence=min(0.9, 0.55 + 0.1 * len(sorted_group)),
            source_ref_type="anchor",
            source_ref_id=anchor,
            evidence_episode_ids=episode_ids,
        )
        if was_created:
            created += 1
            created_seed_ids.append(seed_id)
        else:
            skipped_duplicates += 1
    return ExperienceSeedDiscoveryStats(
        candidates=candidates,
        created=created,
        skipped_duplicates=skipped_duplicates,
        skipped_generic=generic_seen,
        created_seed_ids=created_seed_ids,
    )
