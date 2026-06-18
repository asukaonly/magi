"""Discover durable candidate seeds for L2 experiences."""

from __future__ import annotations

import hashlib
import inspect
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence


GENERIC_EXPERIENCE_ANCHORS = {
    "browser",
    "chrome",
    "gmail",
    "google",
    "google search",
    "github",
    "local user",
    "local_user",
    "self",
    "software:chrome",
    "software:gmail",
    "software:google",
    "software:github",
    "twitter",
    "user",
    "user local user",
    "user self",
    "user:local_user",
    "x",
    "x formerly twitter",
}
MACHINE_ID_PATTERN = re.compile(r"^(?:[0-9a-f]{10,}|[0-9A-HJKMNP-TV-Z]{12,})$", re.IGNORECASE)
RepeatedGoalSelector = Callable[
    [Sequence[dict[str, Any]]],
    Sequence[Mapping[str, Any]] | Awaitable[Sequence[Mapping[str, Any]]],
]


@dataclass(frozen=True)
class ExperienceSeedDiscoveryStats:
    """Counters returned by experience seed discovery runs."""

    candidates: int = 0
    created: int = 0
    skipped_duplicates: int = 0
    skipped_generic: int = 0
    created_seed_ids: list[str] = field(default_factory=list)


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _canonical_anchor(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def _anchor_leaf(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        _, _, text = text.partition(":")
    return text.strip()


def is_generic_experience_anchor(value: Any) -> bool:
    """Return True when an anchor is too generic to justify an experience."""
    raw = str(value or "").strip()
    leaf = _anchor_leaf(raw)
    canonical_values = {_canonical_anchor(raw), _canonical_anchor(leaf)}
    if not raw or not leaf:
        return True
    if MACHINE_ID_PATTERN.fullmatch(raw) or MACHINE_ID_PATTERN.fullmatch(leaf):
        return True
    return any(item in GENERIC_EXPERIENCE_ANCHORS for item in canonical_values)


def readable_anchor_label(value: Any) -> str:
    """Convert a concrete anchor into a compact human-readable label."""
    leaf = _anchor_leaf(value)
    if not leaf or is_generic_experience_anchor(value):
        return ""
    label = leaf.replace("_", " ").replace("-", " ").strip()
    if "/" in label:
        return label
    return " ".join(word.capitalize() for word in label.split())


def _seed_id(seed_type: str, key: str) -> str:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"seed-{seed_type}-{digest}"


def _episode_title(episode: Mapping[str, Any]) -> str:
    for key in ("user_label", "label", "summary"):
        value = str(episode.get(key) or "").strip()
        if value:
            return value
    return "Selected experience"


def _episode_concrete_entity_ids(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        entity
        for entity in episode.get("primary_entity_ids") or []
        if not is_generic_experience_anchor(entity)
    )


def _episode_concrete_place_ids(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        place
        for place in episode.get("primary_place_ids") or []
        if not is_generic_experience_anchor(place)
    )


def _episode_concrete_topic_keys(episode: Mapping[str, Any]) -> list[str]:
    return _ordered_unique(
        topic
        for topic in episode.get("primary_topic_keys") or []
        if not is_generic_experience_anchor(topic)
    )


def _project_anchor_items(episode: Mapping[str, Any]) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    for raw in episode.get("primary_entity_ids") or []:
        text = str(raw or "").strip()
        if is_generic_experience_anchor(text):
            continue
        label = readable_anchor_label(text)
        if not label:
            continue
        lowered = text.casefold()
        if lowered.startswith("project:") or "/" in text:
            anchors.append((text, label))
    return anchors


async def _create_seed_if_missing(
    store: Any,
    *,
    seed_id: str,
    seed_type: str,
    status: str,
    title: str,
    description: str | None = None,
    anchor_entity_ids: list[str] | None = None,
    anchor_place_ids: list[str] | None = None,
    anchor_topic_keys: list[str] | None = None,
    time_start: float | None = None,
    time_end: float | None = None,
    confidence: float = 0.0,
    created_by: str = "system",
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    evidence_episode_ids: list[str] | None = None,
) -> tuple[bool, str]:
    if await store.get_experience_seed(seed_id=seed_id):
        return False, seed_id
    await store.create_experience_seed(
        seed_id=seed_id,
        seed_type=seed_type,
        status=status,
        title=title,
        description=description,
        anchor_entity_ids=anchor_entity_ids or [],
        anchor_place_ids=anchor_place_ids or [],
        anchor_topic_keys=anchor_topic_keys or [],
        time_start=time_start,
        time_end=time_end,
        confidence=confidence,
        created_by=created_by,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    if evidence_episode_ids:
        await store.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=[
                {
                    "ref_type": "episode",
                    "ref_id": episode_id,
                    "role": "trigger" if index == 0 else "support",
                    "confidence": confidence,
                }
                for index, episode_id in enumerate(evidence_episode_ids)
            ],
        )
    return True, seed_id


async def discover_manual_experience_seed(
    store: Any,
    *,
    episode_id: str,
    title: str | None = None,
    created_by: str = "user",
) -> str:
    """Create an accepted seed from a user-selected episode."""
    episode = await store.get_episode(episode_id=episode_id)
    if episode is None:
        raise ValueError(f"Episode not found for experience seed: {episode_id}")
    seed_id = _seed_id("manual", episode_id)
    created, _ = await _create_seed_if_missing(
        store,
        seed_id=seed_id,
        seed_type="manual",
        status="accepted",
        title=title or _episode_title(episode),
        description=str(episode.get("summary") or "") or None,
        anchor_entity_ids=_episode_concrete_entity_ids(episode),
        anchor_place_ids=_episode_concrete_place_ids(episode),
        anchor_topic_keys=_episode_concrete_topic_keys(episode),
        time_start=float(episode["time_start"]),
        time_end=float(episode["time_end"]),
        confidence=0.9,
        created_by=created_by,
        source_ref_type="episode",
        source_ref_id=episode_id,
        evidence_episode_ids=[episode_id],
    )
    if not created:
        await store.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=[{"ref_type": "episode", "ref_id": episode_id, "role": "trigger"}],
        )
    return seed_id


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


async def _selector_proposals(
    selector: RepeatedGoalSelector | None,
    episodes: Sequence[dict[str, Any]],
) -> Sequence[Mapping[str, Any]]:
    if selector is None:
        return []
    proposals = selector(episodes)
    if inspect.isawaitable(proposals):
        proposals = await proposals
    return proposals or []


async def _discover_repeated_goal_seeds(
    store: Any,
    episodes: Sequence[dict[str, Any]],
    selector: RepeatedGoalSelector | None,
) -> ExperienceSeedDiscoveryStats:
    proposals = await _selector_proposals(selector, episodes)
    episodes_by_id = {str(episode["episode_id"]): episode for episode in episodes}
    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []

    for proposal in proposals:
        title = str(proposal.get("title") or "").strip()
        episode_ids = [
            str(item)
            for item in proposal.get("episode_ids") or []
            if str(item) in episodes_by_id
        ]
        if not title or not episode_ids:
            continue
        candidates += 1
        grouped = [episodes_by_id[episode_id] for episode_id in episode_ids]
        entity_ids = _ordered_unique(
            proposal.get("anchor_entity_ids")
            or [
                entity
                for episode in grouped
                for entity in _episode_concrete_entity_ids(episode)
            ]
        )
        place_ids = _ordered_unique(
            proposal.get("anchor_place_ids")
            or [
                place
                for episode in grouped
                for place in _episode_concrete_place_ids(episode)
            ]
        )
        topic_keys = _ordered_unique(
            proposal.get("anchor_topic_keys")
            or [
                topic
                for episode in grouped
                for topic in _episode_concrete_topic_keys(episode)
            ]
        )
        confidence = float(proposal.get("confidence") or 0.0)
        seed_id = _seed_id("repeated", f"{title}:{'|'.join(episode_ids)}")
        was_created, _ = await _create_seed_if_missing(
            store,
            seed_id=seed_id,
            seed_type="repeated_goal",
            status="candidate",
            title=title,
            description=str(proposal.get("description") or "").strip() or None,
            anchor_entity_ids=entity_ids,
            anchor_place_ids=place_ids,
            anchor_topic_keys=topic_keys,
            time_start=min(float(episode["time_start"]) for episode in grouped),
            time_end=max(float(episode["time_end"]) for episode in grouped),
            confidence=confidence,
            source_ref_type="repeated_goal_selector",
            source_ref_id=episode_ids[0],
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
        created_seed_ids=created_seed_ids,
    )


def _merge_stats(*stats: ExperienceSeedDiscoveryStats) -> ExperienceSeedDiscoveryStats:
    return ExperienceSeedDiscoveryStats(
        candidates=sum(item.candidates for item in stats),
        created=sum(item.created for item in stats),
        skipped_duplicates=sum(item.skipped_duplicates for item in stats),
        skipped_generic=sum(item.skipped_generic for item in stats),
        created_seed_ids=[
            seed_id
            for item in stats
            for seed_id in item.created_seed_ids
        ],
    )


async def discover_experience_seeds(
    store: Any,
    *,
    repeated_goal_selector: RepeatedGoalSelector | None = None,
    limit: int = 500,
) -> ExperienceSeedDiscoveryStats:
    """Discover candidate seeds from active episode substrate."""
    episodes = await store.list_episodes(status="active", limit=limit)
    if not episodes:
        return ExperienceSeedDiscoveryStats()
    sorted_episodes = sorted(episodes, key=lambda item: float(item["time_start"]))
    project_stats = await _discover_project_seeds(store, sorted_episodes)
    repeated_stats = await _discover_repeated_goal_seeds(
        store,
        sorted_episodes,
        repeated_goal_selector,
    )
    return _merge_stats(project_stats, repeated_stats)


__all__ = [
    "ExperienceSeedDiscoveryStats",
    "GENERIC_EXPERIENCE_ANCHORS",
    "discover_experience_seeds",
    "discover_manual_experience_seed",
    "is_generic_experience_anchor",
    "readable_anchor_label",
]
