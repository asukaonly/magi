"""Presentation projection for the memory story feed."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ....memory.l3.insight_utils import decode_value

INSIGHT_CATEGORIES = [
    "state_change",
    "trend_shift",
    "conflict_resolution",
    "task_reflection",
    "goal_refinement",
    "preference_emergence",
    "risk_escalation",
    "milestone_review",
]
TEMPORAL_CATEGORIES = ["day", "week", "month", "quarter", "year"]

STORY_FEED_GROUPS = {"periodic", "observations", "tasks", "memory_update", "other"}
SUMMARY_STORY_GROUPS = {"periodic", "observations", "tasks", "other"}

_OBSERVATION_CATEGORIES = {
    "trend_shift",
    "preference_emergence",
    "conflict_resolution",
    "risk_escalation",
}
_TASK_CATEGORIES = {"task_reflection", "goal_refinement", "milestone_review"}
_MEMORY_UPDATE_CATEGORIES = {"state_change"}
_FEATURED_PERIODIC_CATEGORIES = {"week", "month", "quarter", "year"}

_STORY_PREVIEW_MAX_CHARS = 180
_MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_LIST_PATTERN = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)")
_MARKDOWN_LINK_PATTERN = re.compile(r"!?\[([^\]]+)\]\([^)]*\)")

_INTEREST_TREND_GROUP = "interest_profile"
_INTEREST_PROFILE_CATEGORIES = {"state_change", "trend_shift"}

# Detects schema identifiers that should never reach the user. Patterns like
# "state.sleep_quality", "engagement.gaming_focus" — lowercase letters
# separated by '.', optionally with underscores.
_TRAIT_LEAK_PATTERN = re.compile(r"(?<![a-zA-Z0-9])([a-z][a-z_]*\.[a-z][a-z_]+)(?![a-zA-Z0-9])")

_SAFE_EXTENSIONS = {
    "com",
    "org",
    "net",
    "io",
    "cn",
    "jp",
    "ai",
    "co",
    "dev",
    "app",
    "py",
    "ts",
    "tsx",
    "js",
    "jsx",
    "md",
    "html",
    "css",
    "json",
    "yaml",
    "yml",
    "sh",
    "txt",
    "log",
    "csv",
}


def empty_story_feed_stats() -> dict[str, int]:
    return {"highlights": 0, "periodic": 0, "observations": 0, "tasks": 0}


def prepare_story_feed_items(
    rows: list[dict[str, Any]],
    *,
    now: float | None = None,
) -> list[dict[str, Any]]:
    items = [_row_to_story_item(row) for row in rows]
    items = [
        item
        for item in items
        if item["summary_type"] != "insight" or _is_legible_insight_content(item["content"])
    ]
    items = _dedupe_trend_shift_items(items)
    items = [
        item
        for item in items
        if not (
            item["summary_type"] == "temporal" and item.get("generated_by_model") == "rule-summary"
        )
    ]
    items = _filter_expired_state_items(items, now=now)
    items.sort(
        key=lambda item: (
            0 if item["review_state"] == "pending_confirmation" else 1,
            -(item["display_timestamp"] or 0),
        )
    )
    return items


def filter_story_feed_items(
    items: list[dict[str, Any]],
    *,
    surface: str = "all",
    group: str | None = None,
) -> list[dict[str, Any]]:
    filtered = list(items)
    if surface == "summary":
        filtered = [item for item in filtered if bool(item.get("summary_feed_visible"))]
    if group:
        filtered = [item for item in filtered if item.get("feed_group") == group]
    return filtered


def build_story_feed_stats(items: list[dict[str, Any]]) -> dict[str, int]:
    stats = empty_story_feed_stats()
    for item in items:
        if item.get("review_state") == "archived" or not item.get("summary_feed_visible"):
            continue
        feed_group = str(item.get("feed_group") or "")
        if item.get("summary_type") == "insight":
            stats["highlights"] += 1
        if feed_group in {"periodic", "observations", "tasks"}:
            stats[feed_group] += 1
    return stats


def _row_to_story_item(row: dict[str, Any]) -> dict[str, Any]:
    """Project a raw L3 summary row into a story-feed item."""
    metadata = _decode_metadata(row.get("insight_metadata") or {})
    content = str(row.get("content") or "")
    title = str(row.get("title") or "").strip()
    summary_type = str(row.get("summary_type") or "")
    summary_category = str(row.get("summary_category") or "")

    if summary_category in _INTEREST_PROFILE_CATEGORIES:
        interest_item = {"summary_category": summary_category, "insight_metadata": metadata}
        should_project = (
            summary_category == "trend_shift"
            or _is_raw_interest_template(str(content))
            or _is_raw_interest_template(title)
        )
        if should_project and _is_interest_profile_item(interest_item):
            rendered = _render_interest_trend_content(metadata)
            if rendered is not None:
                content = rendered
                if _is_raw_interest_template(title):
                    title = ""

    feed_group = _story_feed_group(summary_type, summary_category)
    essence_prose = row.get("essence_prose") or None
    display_timestamp = _display_timestamp(row)
    preview_text = _story_preview_text(
        essence_prose=essence_prose,
        title=title,
        content=content,
    )
    detail_lead_text = str(essence_prose or content).strip() if title else ""
    return {
        "summary_id": row.get("summary_id") or row.get("id"),
        "summary_type": row.get("summary_type"),
        "summary_category": row.get("summary_category"),
        "title": title or _derive_title(row),
        "content": content,
        "essence_prose": essence_prose,
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "updated_at": row.get("updated_at"),
        "review_state": row.get("review_state") or "neutral",
        "insight_key": row.get("insight_key"),
        "insight_metadata": metadata,
        "evidence_event_count": int(row.get("source_event_count") or 0),
        "generated_by_model": row.get("generated_by_model"),
        "narrative_style": row.get("narrative_style") or "default",
        "salience_until": _salience_until(metadata),
        "feed_group": feed_group,
        "summary_feed_visible": feed_group in SUMMARY_STORY_GROUPS,
        "featured_rank": _featured_rank(feed_group, summary_category),
        "display_timestamp": display_timestamp,
        "preview_text": preview_text,
        "detail_lead_text": detail_lead_text,
    }


def _decode_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            value = {}
    return value if isinstance(value, dict) else {}


def _derive_title(row: dict[str, Any]) -> str:
    # When the L3 record has no human title we deliberately return "" so the
    # frontend can show the category chip + lede instead of a machine name.
    return ""


def _story_feed_group(summary_type: str, summary_category: str) -> str:
    if summary_type != "insight" or summary_category in TEMPORAL_CATEGORIES:
        return "periodic"
    if summary_category in _MEMORY_UPDATE_CATEGORIES:
        return "memory_update"
    if summary_category in _OBSERVATION_CATEGORIES:
        return "observations"
    if summary_category in _TASK_CATEGORIES:
        return "tasks"
    return "other"


def _featured_rank(feed_group: str, summary_category: str) -> int | None:
    if feed_group == "periodic" and summary_category in _FEATURED_PERIODIC_CATEGORIES:
        return 0
    return None


def _display_timestamp(row: dict[str, Any]) -> float:
    for key in ("period_end", "updated_at", "period_start"):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _story_preview_text(
    *,
    essence_prose: Any,
    title: str,
    content: str,
) -> str:
    preview = ""
    for candidate in (essence_prose, title, content):
        source = re.sub(r"```.*?```", " ", str(candidate or "").strip(), flags=re.DOTALL)
        preview_lines: list[str] = []
        for raw_line in source.splitlines():
            if _MARKDOWN_HEADING_PATTERN.match(raw_line):
                continue
            line = _MARKDOWN_LIST_PATTERN.sub("", raw_line.strip())
            line = _MARKDOWN_LINK_PATTERN.sub(r"\1", line)
            line = re.sub(r"(?:\*\*|__|`)", "", line)
            line = re.sub(r"\s+", " ", line).strip()
            if not line or line in preview_lines:
                continue
            preview_lines.append(line)
            if len(preview_lines) == 2:
                break
        preview = " ".join(preview_lines).strip()
        if preview:
            break

    if len(preview) <= _STORY_PREVIEW_MAX_CHARS:
        return preview

    clipped = preview[:_STORY_PREVIEW_MAX_CHARS].rstrip()
    sentence_ends = [clipped.rfind(mark) for mark in "。！？.!?"]
    sentence_end = max(sentence_ends)
    if sentence_end >= _STORY_PREVIEW_MAX_CHARS // 2:
        return clipped[: sentence_end + 1]
    return clipped.rstrip("，、；;：: ") + "…"


def _salience_until(metadata: dict[str, Any]) -> float | None:
    salience_until_raw = metadata.get("salience_until")
    if isinstance(salience_until_raw, (int, float)):
        return float(salience_until_raw)
    return None


def _filter_expired_state_items(
    items: list[dict[str, Any]],
    *,
    now: float | None,
) -> list[dict[str, Any]]:
    reference_time = time.time() if now is None else now
    return [
        item
        for item in items
        if not (
            item["feed_group"] == "memory_update"
            and item.get("salience_until") is not None
            and item["salience_until"] < reference_time
        )
    ]


def _metadata_outcomes(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    outcomes = metadata.get("outcomes")
    if not isinstance(outcomes, list):
        return []
    return [outcome for outcome in outcomes if isinstance(outcome, dict)]


def _is_interest_trait_name(value: Any) -> bool:
    return str(value or "").strip().lower().startswith("interest.")


def _trend_groups_from_metadata(metadata: dict[str, Any]) -> list[str]:
    trend_groups = metadata.get("trend_groups")
    if isinstance(trend_groups, list):
        groups = [str(group).strip() for group in trend_groups if str(group).strip()]
        if groups:
            return groups

    outcomes = _metadata_outcomes(metadata)
    if outcomes and all(_is_interest_trait_name(outcome.get("trait_name")) for outcome in outcomes):
        return [_INTEREST_TREND_GROUP]
    return []


def _interest_values_from_metadata(metadata: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for outcome in _metadata_outcomes(metadata):
        raw_value = outcome.get("winning_value")
        if raw_value is None:
            raw_value = outcome.get("value")
        decoded_value = decode_value(raw_value) if isinstance(raw_value, str) else raw_value
        if isinstance(decoded_value, (dict, list)):
            value = json.dumps(decoded_value, ensure_ascii=False, sort_keys=True)
        else:
            value = str(decoded_value or "").strip()
        if not value:
            continue
        if value.casefold() in {item.casefold() for item in values}:
            continue
        values.append(value)
        if len(values) >= 6:
            break
    return values


def _is_interest_profile_item(item: dict[str, Any]) -> bool:
    if item.get("summary_category") not in _INTEREST_PROFILE_CATEGORIES:
        return False
    metadata = item.get("insight_metadata")
    if not isinstance(metadata, dict):
        return False
    return _INTEREST_TREND_GROUP in _trend_groups_from_metadata(metadata)


def _render_interest_trend_content(metadata: dict[str, Any]) -> str | None:
    values = _interest_values_from_metadata(metadata)
    if not values:
        return None
    return f"最近持续关注：{'、'.join(values)}。"


def _is_raw_interest_template(value: str) -> bool:
    lowered = value.strip().lower()
    return "interested_in signal" in lowered or "recurring interested_in" in lowered


def _trend_dedupe_key(item: dict[str, Any]) -> tuple[str, str] | None:
    if item.get("summary_category") != "trend_shift":
        return None
    metadata = item.get("insight_metadata")
    if not isinstance(metadata, dict):
        return None
    groups = _trend_groups_from_metadata(metadata)
    if not groups:
        return None
    entity_id = str(metadata.get("entity_id") or item.get("insight_key") or "").strip()
    if not entity_id:
        return None
    return (entity_id, "|".join(sorted(groups)))


def _latest_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    period_end = item.get("period_end")
    updated_at = item.get("updated_at")
    return (
        float(period_end) if isinstance(period_end, (int, float)) else 0.0,
        float(updated_at) if isinstance(updated_at, (int, float)) else 0.0,
    )


def _dedupe_trend_shift_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in items:
        key = _trend_dedupe_key(item)
        if key is None:
            unkeyed.append(item)
            continue
        existing = keyed.get(key)
        if existing is None or _latest_sort_key(item) > _latest_sort_key(existing):
            keyed[key] = item
    return [*unkeyed, *keyed.values()]


def _is_legible_insight_content(content: str) -> bool:
    """Return False when the content contains raw trait_name schema leakage."""
    matches = _TRAIT_LEAK_PATTERN.findall(content or "")
    if not matches:
        return True
    for match in matches:
        suffix = match.rsplit(".", 1)[-1]
        if suffix in _SAFE_EXTENSIONS:
            continue
        return False
    return True


__all__ = [
    "INSIGHT_CATEGORIES",
    "TEMPORAL_CATEGORIES",
    "STORY_FEED_GROUPS",
    "SUMMARY_STORY_GROUPS",
    "build_story_feed_stats",
    "empty_story_feed_stats",
    "filter_story_feed_items",
    "prepare_story_feed_items",
]
