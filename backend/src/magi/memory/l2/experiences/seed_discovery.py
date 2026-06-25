"""Discover durable candidate seeds for L2 experiences."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..storage.utils import _l2_setting


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
TEXT_TOKEN_SPLIT_PATTERN = re.compile(r"[\n,，;；、|]+")
QUOTE_PATTERN = re.compile(r"[「“\"]([^」”\"]{2,40})[」”\"]")
MAX_REPEATED_GOAL_WINDOW_SECONDS = 30 * 24 * 60 * 60
MAX_REPEATED_GOAL_GAP_SECONDS = 7 * 24 * 60 * 60
MIN_REPEATED_GOAL_EPISODES = 3
MIN_REPEATED_GOAL_EVENTS = 8
TEXT_SOURCE_NOISE = {
    "about",
    "apple",
    "browse",
    "browsing",
    "browser",
    "chrome",
    "com",
    "edge",
    "firefox",
    "gmail",
    "google",
    "github",
    "homepage",
    "iphone",
    "local",
    "login",
    "mail",
    "media",
    "notification",
    "notifications",
    "page",
    "reddit",
    "safari",
    "search",
    "software",
    "tabs",
    "timeline",
    "user",
    "visited",
    "youtube",
    "关于",
    "使用",
    "查看",
    "浏览",
    "浏览器",
    "搜索",
    "访问",
    "通知",
    "邮件",
    "收件箱",
    "首页",
    "页面",
    "时间线",
    "相关",
    "登录",
    "动态",
    "应用",
}
OPERATIONAL_ARTIFACT_EXTENSIONS = {
    ".db",
    ".env",
    ".json",
    ".lock",
    ".log",
    ".md",
    ".pid",
    ".sh",
    ".sock",
    ".sqlite",
    ".sqlite3",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
CODE_ARTIFACT_EXTENSIONS = {
    ".js",
    ".jsx",
    ".py",
    ".ts",
    ".tsx",
}
ARTIFACT_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_@~./\\-]+\.[A-Za-z0-9_@./\\-]+")
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


@dataclass(frozen=True)
class _EpisodeSeedFeatures:
    """Normalized signal packet used by deterministic repeated-goal discovery."""

    episode: dict[str, Any]
    text: str
    entity_ids: list[str]
    place_ids: list[str]
    topic_keys: list[str]
    text_tokens: list[str]


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


def _normalized_match_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def is_generic_experience_anchor(value: Any) -> bool:
    """Return True when an anchor is too generic to justify an experience."""
    raw = str(value or "").strip()
    leaf = _anchor_leaf(raw)
    canonical_values = {_canonical_anchor(raw), _canonical_anchor(leaf)}
    if not raw or not leaf:
        return True
    if _canonical_anchor(raw).startswith("hardware:"):
        return True
    if MACHINE_ID_PATTERN.fullmatch(raw) or MACHINE_ID_PATTERN.fullmatch(leaf):
        return True
    return any(item in GENERIC_EXPERIENCE_ANCHORS for item in canonical_values)


def is_technical_artifact_experience_token(value: Any) -> bool:
    """Return True when text is a low-level file/script/log artifact."""
    text = str(value or "").strip().casefold()
    if not text:
        return False
    for match in ARTIFACT_TOKEN_PATTERN.findall(text):
        token = match.strip(" \t\r\n.。:：()（）[]【】<>《》")
        if not token:
            continue
        leaf = re.split(r"[/\\]", token)[-1]
        if "." not in leaf:
            continue
        stem, extension = leaf.rsplit(".", 1)
        extension = f".{extension}"
        if extension in OPERATIONAL_ARTIFACT_EXTENSIONS:
            return True
        is_file_like = (
            "/" in token
            or "\\" in token
            or "-" in stem
            or "_" in stem
            or stem in {"app", "client", "config", "index", "main", "server", "test", "tests"}
        )
        if extension in CODE_ARTIFACT_EXTENSIONS and is_file_like:
            return True
    return False


def readable_anchor_label(value: Any) -> str:
    """Convert a concrete anchor into a compact human-readable label."""
    leaf = _anchor_leaf(value)
    if not leaf or is_generic_experience_anchor(value) or is_technical_artifact_experience_token(value):
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
        and not is_technical_artifact_experience_token(topic)
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


def _readable_text_token(token: str) -> str:
    text = str(token or "").strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text):
        return text
    return " ".join(part.capitalize() for part in text.replace("_", " ").split())


def _is_text_noise(token: str) -> bool:
    text = str(token or "").strip().casefold()
    if not text:
        return True
    if len(text) > 40:
        return True
    if is_technical_artifact_experience_token(text):
        return True
    if is_generic_experience_anchor(text):
        return True
    canonical = _canonical_anchor(text)
    if canonical in TEXT_SOURCE_NOISE:
        return True
    if MACHINE_ID_PATTERN.fullmatch(text):
        return True
    return False


def _text_tokens(value: str) -> list[str]:
    """Extract explicit reusable text anchors without free-form n-gram slicing."""
    tokens: list[str] = []
    for raw in TEXT_TOKEN_SPLIT_PATTERN.split(value or ""):
        token = raw.strip(" \t\r\n.。:：()（）[]【】<>《》")
        if not token or _is_text_noise(token):
            continue
        if re.search(r"[\u4e00-\u9fff]", token):
            if len(_normalized_match_text(token)) < 3:
                continue
            tokens.append(token)
        else:
            if len(_normalized_match_text(token)) < 4:
                continue
            if not re.search(r"[\s./_-]", token):
                continue
            tokens.append(token.casefold())
    return _ordered_unique(tokens)


def _source_entity_label_variants(anchor: Any) -> set[str]:
    text = str(anchor or "").strip()
    if not text.casefold().startswith(("software:", "hardware:")):
        return set()
    leaf = _anchor_leaf(text)
    variants = {
        leaf,
        leaf.replace("-", " "),
        leaf.replace("_", " "),
        readable_anchor_label(text),
    }
    if "." in leaf:
        variants.add(leaf.split(".", 1)[0])
    return {
        normalized
        for value in variants
        if (normalized := _normalized_match_text(value))
    }


def _token_matches_source_entity(
    token: str,
    features: Sequence[_EpisodeSeedFeatures],
) -> bool:
    normalized_token = _normalized_match_text(token)
    if not normalized_token:
        return True
    matched = 0
    for feature in features:
        variants = {
            variant
            for entity_id in feature.episode.get("primary_entity_ids") or []
            for variant in _source_entity_label_variants(entity_id)
        }
        if normalized_token in variants:
            matched += 1
    return matched > 0


def _summary_metadata_terms(raw_metadata: Any, content: str) -> list[str]:
    try:
        metadata = json.loads(str(raw_metadata or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    terms: list[str] = []
    for topic in metadata.get("key_topics") or []:
        if isinstance(topic, str):
            terms.append(topic)
        elif isinstance(topic, Mapping):
            terms.append(str(topic.get("label") or topic.get("id") or ""))
    terms.extend(match.strip() for match in QUOTE_PATTERN.findall(content or ""))

    if not terms:
        label = str(metadata.get("label") or "").strip()
        if label:
            terms.append(label)
    return _ordered_unique(terms)


async def _load_episodic_summary_texts(
    store: Any,
    episode_ids: list[str],
) -> dict[str, str]:
    db_path = str(getattr(store, "db_path", "") or "")
    if not db_path or not episode_ids:
        return {}
    placeholders = ", ".join("?" for _ in episode_ids)
    try:
        await store.initialize()
        async with sqlite_connection_async(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT json_extract(insight_metadata, '$.source_episode_id') AS episode_id,
                       content,
                       insight_metadata,
                       updated_at
                FROM summaries
                WHERE summary_category = 'episodic'
                  AND json_extract(insight_metadata, '$.source_episode_id') IN ({placeholders})
                ORDER BY updated_at DESC
                """,
                tuple(episode_ids),
            ) as cursor:
                rows = await cursor.fetchall()
    except Exception:
        return {}

    summaries: dict[str, str] = {}
    for row in rows:
        episode_id = str(row["episode_id"] or "").strip()
        content = str(row["content"] or "").strip()
        terms = _summary_metadata_terms(row["insight_metadata"], content)
        if episode_id and terms and episode_id not in summaries:
            summaries[episode_id] = "\n".join(terms)
    return summaries


def _episode_seed_text(
    episode: Mapping[str, Any],
    summary_texts: Mapping[str, str],
) -> str:
    episode_id = str(episode.get("episode_id") or "")
    parts = [
        episode.get("user_label"),
        summary_texts.get(episode_id),
    ]
    return "\n".join(str(part).strip() for part in parts if str(part or "").strip())


def _episode_features(
    episodes: Sequence[dict[str, Any]],
    summary_texts: Mapping[str, str],
) -> list[_EpisodeSeedFeatures]:
    features: list[_EpisodeSeedFeatures] = []
    for episode in episodes:
        text = _episode_seed_text(episode, summary_texts)
        features.append(
            _EpisodeSeedFeatures(
                episode=episode,
                text=text,
                entity_ids=_episode_concrete_entity_ids(episode),
                place_ids=_episode_concrete_place_ids(episode),
                topic_keys=_episode_concrete_topic_keys(episode),
                text_tokens=_text_tokens(text),
            )
        )
    return features


def _total_source_events(features: Sequence[_EpisodeSeedFeatures]) -> int:
    return sum(int(item.episode.get("source_event_count") or 0) for item in features)


def _time_bounds(features: Sequence[_EpisodeSeedFeatures]) -> tuple[float, float]:
    return (
        min(float(item.episode["time_start"]) for item in features),
        max(float(item.episode["time_end"]) for item in features),
    )


def _passes_repeated_goal_gate(features: Sequence[_EpisodeSeedFeatures]) -> bool:
    min_episodes = int(_l2_setting("experience", "min_repeated_goal_episodes", MIN_REPEATED_GOAL_EPISODES))
    min_events = int(_l2_setting("experience", "min_repeated_goal_events", MIN_REPEATED_GOAL_EVENTS))
    max_window = float(
        _l2_setting("experience", "max_repeated_goal_window_seconds", MAX_REPEATED_GOAL_WINDOW_SECONDS)
    )
    max_gap = float(
        _l2_setting("experience", "max_repeated_goal_gap_seconds", MAX_REPEATED_GOAL_GAP_SECONDS)
    )
    if len(features) < min_episodes:
        return False
    if _total_source_events(features) < min_events:
        return False
    ordered = sorted(features, key=lambda item: float(item.episode["time_start"]))
    start, end = _time_bounds(ordered)
    if end - start > max_window:
        return False
    for left, right in zip(ordered, ordered[1:]):
        gap = float(right.episode["time_start"]) - float(left.episode["time_end"])
        if gap > max_gap:
            return False
    return True


def _repeated_goal_confidence(
    features: Sequence[_EpisodeSeedFeatures],
    *,
    token: str = "",
) -> float:
    base = 0.56 + 0.06 * min(len(features), 4)
    event_bonus = min(0.08, _total_source_events(features) / 200.0)
    token_bonus = min(0.06, len(token) / 100.0)
    return min(0.88, base + event_bonus + token_bonus)


def _candidate_episode_ids(features: Sequence[_EpisodeSeedFeatures]) -> list[str]:
    return [
        str(item.episode["episode_id"])
        for item in sorted(features, key=lambda feature: float(feature.episode["time_start"]))
    ]


async def _create_repeated_seed_from_features(
    store: Any,
    *,
    seed_id: str,
    title: str,
    description: str,
    features: Sequence[_EpisodeSeedFeatures],
    anchor_entity_ids: list[str] | None = None,
    anchor_place_ids: list[str] | None = None,
    anchor_topic_keys: list[str] | None = None,
    confidence: float,
) -> tuple[bool, str]:
    start, end = _time_bounds(features)
    return await _create_seed_if_missing(
        store,
        seed_id=seed_id,
        seed_type="repeated_goal",
        status="candidate",
        title=title,
        description=description,
        anchor_entity_ids=anchor_entity_ids or [],
        anchor_place_ids=anchor_place_ids or [],
        anchor_topic_keys=anchor_topic_keys or [],
        time_start=start,
        time_end=end,
        confidence=confidence,
        source_ref_type="episode_group",
        source_ref_id=",".join(_candidate_episode_ids(features)),
        evidence_episode_ids=_candidate_episode_ids(features),
    )


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


def _contiguous_feature_runs(
    features: Sequence[_EpisodeSeedFeatures],
) -> list[list[_EpisodeSeedFeatures]]:
    ordered = sorted(features, key=lambda item: float(item.episode["time_start"]))
    runs: list[list[_EpisodeSeedFeatures]] = []
    current: list[_EpisodeSeedFeatures] = []
    max_gap = float(
        _l2_setting("experience", "max_repeated_goal_gap_seconds", MAX_REPEATED_GOAL_GAP_SECONDS)
    )
    for feature in ordered:
        if not current:
            current = [feature]
            continue
        gap = float(feature.episode["time_start"]) - float(current[-1].episode["time_end"])
        if gap > max_gap:
            runs.append(current)
            current = [feature]
        else:
            current.append(feature)
    if current:
        runs.append(current)
    return runs


def _overlaps_selected_episode_set(
    episode_ids: tuple[str, ...],
    selected_sets: Sequence[set[str]],
) -> bool:
    current = set(episode_ids)
    for selected in selected_sets:
        overlap = len(current & selected)
        if overlap and overlap / min(len(current), len(selected)) >= 0.66:
            return True
    return False


async def _discover_text_repeated_goal_seeds(
    store: Any,
    features: Sequence[_EpisodeSeedFeatures],
) -> ExperienceSeedDiscoveryStats:
    token_groups: dict[str, list[_EpisodeSeedFeatures]] = defaultdict(list)
    for feature in features:
        for token in feature.text_tokens:
            token_groups[token].append(feature)

    best_by_episode_set: dict[tuple[str, ...], tuple[str, list[_EpisodeSeedFeatures], float]] = {}
    for token, grouped in token_groups.items():
        unique_by_id = {
            str(feature.episode["episode_id"]): feature
            for feature in grouped
        }
        for run in _contiguous_feature_runs(list(unique_by_id.values())):
            if any(_project_anchor_items(feature.episode) for feature in run):
                continue
            if _token_matches_source_entity(token, run):
                continue
            if not _passes_repeated_goal_gate(run):
                continue
            episode_ids = tuple(_candidate_episode_ids(run))
            score = len(token) * len(run)
            previous = best_by_episode_set.get(episode_ids)
            if previous is None or score > previous[2]:
                best_by_episode_set[episode_ids] = (token, run, float(score))

    selected_sets: list[set[str]] = []
    selected_candidates: list[
        tuple[tuple[str, ...], tuple[str, list[_EpisodeSeedFeatures], float]]
    ] = []
    for item in sorted(
        best_by_episode_set.items(),
        key=lambda item: (-len(item[0]), -item[1][2], float(item[1][1][0].episode["time_start"])),
    ):
        episode_ids, candidate = item
        if _overlaps_selected_episode_set(episode_ids, selected_sets):
            continue
        selected_sets.append(set(episode_ids))
        selected_candidates.append(item)

    candidates = 0
    created = 0
    skipped_duplicates = 0
    created_seed_ids: list[str] = []
    for episode_ids, (token, grouped, _) in sorted(
        selected_candidates,
        key=lambda item: (float(item[1][1][0].episode["time_start"]), item[0]),
    ):
        candidates += 1
        title = _readable_text_token(token)
        if not title:
            continue
        seed_id = _seed_id("repeated", f"text:{token}:{'|'.join(episode_ids)}")
        was_created, _ = await _create_repeated_seed_from_features(
            store,
            seed_id=seed_id,
            title=title,
            description=f"这些片段在一段连续时间里反复围绕「{title}」展开。",
            features=grouped,
            anchor_topic_keys=[token],
            confidence=_repeated_goal_confidence(grouped, token=token),
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
    summary_texts = await _load_episodic_summary_texts(
        store,
        [str(episode["episode_id"]) for episode in sorted_episodes],
    )
    features = _episode_features(sorted_episodes, summary_texts)
    project_stats = await _discover_project_seeds(store, sorted_episodes)
    anchor_stats = await _discover_anchor_repeated_goal_seeds(store, features)
    text_stats = await _discover_text_repeated_goal_seeds(store, features)
    repeated_stats = await _discover_repeated_goal_seeds(
        store,
        sorted_episodes,
        repeated_goal_selector,
    )
    return _merge_stats(project_stats, anchor_stats, text_stats, repeated_stats)


__all__ = [
    "ExperienceSeedDiscoveryStats",
    "GENERIC_EXPERIENCE_ANCHORS",
    "discover_experience_seeds",
    "discover_manual_experience_seed",
    "is_generic_experience_anchor",
    "is_technical_artifact_experience_token",
    "readable_anchor_label",
]
