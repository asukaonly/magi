"""Anchor-based repeated-goal seed discovery for L2 experiences."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence

from .seed_anchors import _project_anchor_items, _seed_id, readable_anchor_label
from .seed_features import _passes_repeated_goal_gate, _repeated_goal_confidence
from .seed_models import ExperienceSeedDiscoveryStats, _EpisodeSeedFeatures
from .seed_writes import _create_repeated_seed_from_features


async def _discover_anchor_repeated_goal_seeds(
    store: Any,
    features: Sequence[_EpisodeSeedFeatures],
) -> ExperienceSeedDiscoveryStats:
    grouped_by_anchor: dict[tuple[str, str], list[_EpisodeSeedFeatures]] = defaultdict(list)
    labels: dict[tuple[str, str], str] = {}
    for feature in features:
        for kind, anchors in (
            ("place", feature.place_ids),
            ("topic", feature.topic_keys),
        ):
            for anchor in anchors:
                lowered = anchor.casefold()
                if lowered.startswith("project:") or "/" in anchor:
                    continue
                label = readable_anchor_label(anchor)
                if not label:
                    continue
                key = (kind, anchor)
                grouped_by_anchor[key].append(feature)
                labels[key] = label

    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []
    for (kind, anchor), grouped in sorted(grouped_by_anchor.items()):
        unique_by_id = {
            str(feature.episode["episode_id"]): feature
            for feature in grouped
        }
        ordered = sorted(unique_by_id.values(), key=lambda item: float(item.episode["time_start"]))
        if any(_project_anchor_items(feature.episode) for feature in ordered):
            continue
        if not _passes_repeated_goal_gate(ordered):
            continue
        candidates += 1
        label = labels[(kind, anchor)]
        seed_id = _seed_id("repeated", f"{kind}:{anchor}")
        anchor_entity_ids = [anchor] if kind == "entity" else []
        anchor_place_ids = [anchor] if kind == "place" else []
        anchor_topic_keys = [anchor] if kind == "topic" else []
        was_created, _ = await _create_repeated_seed_from_features(
            store,
            seed_id=seed_id,
            title=label,
            description=f"这些片段在一段连续时间里反复围绕「{label}」展开。",
            features=ordered,
            anchor_entity_ids=anchor_entity_ids,
            anchor_place_ids=anchor_place_ids,
            anchor_topic_keys=anchor_topic_keys,
            confidence=_repeated_goal_confidence(ordered),
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
        created_seed_ids=created_seed_ids,
    )
