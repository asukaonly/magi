"""Build episodic evidence packs from L1 events linked to an episode.

The builder folds noisy sources (chrome_history, screen_time) into
compact summary lines, keeps high-signal sources (chat, manual_entry, music)
verbatim, and derives fallback topics from structured_entity_hints when
the L2 layer didn't populate primary_topic_keys.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from .models import EpisodicEvidenceItem, EpisodicEvidencePack

# Sources whose events get folded into a single summary line per episode.
# Source streams that produce many near-identical rows.
_FOLDED_SOURCES = {"chrome_history", "screen_time"}

# Maximum number of folded items to show per source group.
_MAX_FOLDED_ITEMS_PER_SOURCE = 6

# Maximum number of verbatim events to keep after folding.
_MAX_VERBATIM_EVENTS = 30

# Maximum number of derived topics to surface when primary_topic_keys is empty.
_MAX_DERIVED_TOPICS = 5


def _decode_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _role_from_author_type(author_type: Any) -> str | None:
    """L1 author_type code -> human role label.

    L1 fact_events.author_type uses small integer codes:
        1 = user, 2 = assistant, 3 = system, 4 = source (approx).
    """
    try:
        code = int(author_type)
    except (TypeError, ValueError):
        return None
    return {1: "user", 2: "assistant", 3: "system"}.get(code)


def _fold_chrome_history(events: list[dict[str, Any]]) -> str | None:
    """Collapse chrome_history events to: '浏览: A · B · C ... (共 N 次)'.

    Page titles are extracted from content (strip the 'Chrome 浏览 ' prefix
    if present) and deduplicated by first 40 chars to avoid '... (访问 2 次)'
    siblings.
    """
    if not events:
        return None
    titles: list[str] = []
    seen: set[str] = set()
    for event in events:
        content = str(event.get("content") or "").strip()
        if not content:
            continue
        title = content
        for prefix in ("Chrome 浏览 ", "Chrome browsed "):
            if title.startswith(prefix):
                title = title[len(prefix) :]
                break
        key = title[:40].casefold()
        if key in seen:
            continue
        seen.add(key)
        # Strip trailing visit-count suffix like "（访问 2 次）"
        for sep in ("（访问", "(访问", " (访问"):
            idx = title.find(sep)
            if idx > 0:
                title = title[:idx].rstrip()
                break
        if title:
            titles.append(title)
        if len(titles) >= _MAX_FOLDED_ITEMS_PER_SOURCE:
            break
    if not titles:
        return None
    joined = " · ".join(titles)
    return f"浏览：{joined}（共 {len(events)} 次）"


def _fold_screen_time(events: list[dict[str, Any]]) -> str | None:
    """Collapse APP_USAGE_HOURLY events to per-app minute totals.

    Content shape (observed): "Magi 使用 · 00:00-01:00 · 60 分钟".
    Aggregates by leading app name token.
    """
    if not events:
        return None
    minutes_by_app: dict[str, int] = defaultdict(int)
    for event in events:
        content = str(event.get("content") or "").strip()
        if not content:
            continue
        # First token before " · " or " 使用" is the app name.
        first = content.split(" · ")[0]
        app = first.replace(" 使用", "").strip()
        # Try to pull "N 分钟" tail.
        tail = content.rsplit(" · ", 1)[-1]
        mins = 0
        for token in tail.split():
            if token.isdigit():
                mins = int(token)
                break
        minutes_by_app[app or "未知"] += mins
    parts = sorted(minutes_by_app.items(), key=lambda kv: -kv[1])[:_MAX_FOLDED_ITEMS_PER_SOURCE]
    if not parts:
        return None
    rendered = " · ".join(f"{app} {mins}分钟" for app, mins in parts)
    return f"应用使用：{rendered}"


def _derive_topics(events: list[dict[str, Any]]) -> list[str]:
    """Extract top-N topic candidates from metadata.structured_entity_hints.

    Frequency-counts canonical_name_hint (falling back to mention_text) across
    all events. Used when the L2 layer didn't populate primary_topic_keys.
    """
    counter: Counter[str] = Counter()
    for event in events:
        metadata = _decode_metadata(event.get("metadata_json"))
        hints = metadata.get("structured_entity_hints")
        if not isinstance(hints, list):
            continue
        for hint in hints:
            if not isinstance(hint, dict):
                continue
            name = str(hint.get("canonical_name_hint") or hint.get("mention_text") or "").strip()
            if not name:
                continue
            counter[name] += 1
    return [name for name, _ in counter.most_common(_MAX_DERIVED_TOPICS)]


class EpisodicEvidencePackMixin:
    """Helpers for assembling EpisodicEvidencePack from L1 event rows."""

    def build_episodic_evidence_pack(
        self,
        *,
        episode: dict[str, Any],
        events: list[dict[str, Any]],
        max_events: int = _MAX_VERBATIM_EVENTS,
    ) -> EpisodicEvidencePack:
        sorted_events = sorted(events, key=lambda e: float(e.get("timestamp") or 0))
        by_source, verbatim_raw = self._partition_events(sorted_events)
        episode_topics, derived_topics = self._episode_topics(episode, sorted_events)

        return EpisodicEvidencePack(
            episode_id=str(episode.get("episode_id") or ""),
            episode_type=str(episode.get("episode_type") or "activity"),
            time_start=float(episode.get("time_start") or 0),
            time_end=float(episode.get("time_end") or 0),
            primary_entity_ids=list(episode.get("primary_entity_ids") or []),
            primary_topic_keys=episode_topics,
            source_event_count=len(sorted_events),
            source_event_ids=self._source_event_ids(sorted_events),
            events=self._verbatim_items(verbatim_raw, max_events=max_events),
            folded_groups=self._folded_groups(by_source),
            derived_topics=derived_topics,
        )

    @staticmethod
    def _partition_events(
        sorted_events: list[dict[str, Any]],
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        verbatim_raw: list[dict[str, Any]] = []
        for event in sorted_events:
            source = str(event.get("source") or "").strip()
            if source in _FOLDED_SOURCES:
                by_source[source].append(event)
            else:
                verbatim_raw.append(event)
        return by_source, verbatim_raw

    @staticmethod
    def _folded_groups(by_source: dict[str, list[dict[str, Any]]]) -> list[str]:
        folded_groups: list[str] = []
        if "chrome_history" in by_source:
            line = _fold_chrome_history(by_source["chrome_history"])
            if line:
                folded_groups.append(line)
        if "screen_time" in by_source:
            line = _fold_screen_time(by_source["screen_time"])
            if line:
                folded_groups.append(line)
        return folded_groups

    @staticmethod
    def _source_event_ids(sorted_events: list[dict[str, Any]]) -> list[str]:
        source_event_ids: list[str] = []
        for event in sorted_events:
            event_id = str(event.get("event_id") or "").strip()
            if event_id:
                source_event_ids.append(event_id)
        return source_event_ids

    def _verbatim_items(
        self,
        verbatim_raw: list[dict[str, Any]],
        *,
        max_events: int,
    ) -> list[EpisodicEvidenceItem]:
        items: list[EpisodicEvidenceItem] = []
        for event in verbatim_raw[:max_events]:
            item = self._verbatim_item(event)
            if item is not None:
                items.append(item)
        return items

    @staticmethod
    def _verbatim_item(event: dict[str, Any]) -> EpisodicEvidenceItem | None:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            return None
        content = str(event.get("content") or "").strip()
        if len(content) > 200:
            content = content[:200].rstrip() + "..."
        source = str(event.get("source") or "").strip() or None
        return EpisodicEvidenceItem(
            event_id=event_id,
            event_type=str(event.get("event_type") or ""),
            content=content,
            timestamp=(float(event["timestamp"]) if event.get("timestamp") is not None else None),
            importance_score=(
                float(event["importance_score"])
                if event.get("importance_score") is not None
                else None
            ),
            source=source,
            role=_role_from_author_type(event.get("author_type")),
        )

    @staticmethod
    def _episode_topics(
        episode: dict[str, Any],
        sorted_events: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        episode_topics = list(episode.get("primary_topic_keys") or [])
        if episode_topics:
            return episode_topics, []
        return episode_topics, _derive_topics(sorted_events)


__all__ = ["EpisodicEvidencePackMixin"]
