"""Shared rendering utilities for memory recall output.

Used by both the tool path (compact_historical_recall) and the eval
answering path (prompt_builder) to ensure consistent timestamp
formatting, text truncation, finding aggregation, and asset manifests.
"""

from __future__ import annotations

import time
from datetime import datetime, tzinfo
from typing import Any


def _local_tz() -> tzinfo:
    """Return the system local timezone."""
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

def format_timestamp(ts: float | None, *, now: float | None = None) -> str:
    """Unix epoch → ``'2026-05-06 Tue 22:54'`` in system local timezone."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=_local_tz())
        return dt.strftime("%Y-%m-%d %a %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def format_date(ts: float | None) -> str:
    """Unix epoch → ``'2026-05-06'`` in system local timezone."""
    if ts is None:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=_local_tz())
        return dt.strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def format_time_range(
    start: float | None,
    end: float | None,
) -> str:
    """Two timestamps → ``'2026-05-02 ~ 2026-05-06'`` or a single date."""
    s = format_date(start)
    e = format_date(end)
    if s and e and s != e:
        return f"{s} ~ {e}"
    return s or e


def format_relative(ts: float | None, *, now: float | None = None) -> str:
    """Unix epoch → ``'3 天前'`` / ``'2 小时前'``."""
    if ts is None:
        return ""
    ref = now if now is not None else time.time()
    delta = ref - ts
    if delta < 0:
        return ""
    if delta < 3600:
        minutes = max(int(delta / 60), 1)
        return f"{minutes} 分钟前"
    if delta < 86400:
        hours = int(delta / 3600)
        return f"{hours} 小时前"
    days = int(delta / 86400)
    if days <= 30:
        return f"{days} 天前"
    months = int(days / 30)
    if months <= 12:
        return f"{months} 个月前"
    return format_date(ts)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def truncate_statement(text: str, *, max_chars: int = 200) -> tuple[str, bool]:
    """Truncate preserving meaning, return ``(text, was_truncated)``."""
    normalized = str(text or "").strip()
    if len(normalized) <= max_chars:
        return normalized, False
    return normalized[:max_chars].rsplit(" ", 1)[0].rstrip() + "…", True


# ---------------------------------------------------------------------------
# Finding aggregation
# ---------------------------------------------------------------------------

def aggregate_by_statement(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge findings with identical *statement* text.

    Returns a new list where each entry has extra keys:
    ``count``, ``first_at``, ``last_at``.
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for f in findings:
        key = str(f.get("statement") or "").strip()
        if not key:
            continue
        if key not in groups:
            groups[key] = {
                **f,
                "count": 1,
                "first_at": f.get("occurred_at"),
                "last_at": f.get("occurred_at"),
            }
            order.append(key)
        else:
            g = groups[key]
            g["count"] += 1
            ts = f.get("occurred_at")
            if ts is not None:
                if g["first_at"] is None or ts < g["first_at"]:
                    g["first_at"] = ts
                if g["last_at"] is None or ts > g["last_at"]:
                    g["last_at"] = ts
            if f.get("confidence") is not None:
                existing = g.get("confidence")
                if existing is None or f["confidence"] > existing:
                    g["confidence"] = f["confidence"]

    return [groups[k] for k in order]


# ---------------------------------------------------------------------------
# Echo detection
# ---------------------------------------------------------------------------

def is_echo_finding(finding: dict[str, Any], query: str) -> bool:
    """Return *True* when *finding* is a conversation echo of *query*.

    A conversation echo is an L1 event whose statement is essentially the
    query text itself (recorded by the event pipeline) or the assistant's
    previous answer to that same query.
    """
    if finding.get("kind") != "event":
        return False
    if finding.get("source_layer") != "L1":
        return False

    statement = str(finding.get("statement") or "").strip()
    query_normalized = query.strip()
    if not statement or not query_normalized:
        return False

    if statement == query_normalized:
        return True

    shorter, longer = (
        (query_normalized, statement)
        if len(query_normalized) <= len(statement)
        else (statement, query_normalized)
    )
    if len(shorter) >= 4 and shorter in longer:
        ratio = len(shorter) / len(longer)
        if ratio > 0.85:
            return True

    return False


# ---------------------------------------------------------------------------
# Asset manifest
# ---------------------------------------------------------------------------

_LLM_USEFUL_ATTRIBUTES = frozenset({
    "domain",
    "canonical_url",
    "tags",
    "browser",
    "merged_visit_count",
})


def build_asset_manifest(
    asset_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate *asset_refs* into an LLM-friendly manifest.

    Groups by ``(source_type, display_name_normalized)`` and keeps only
    the minimal fields the LLM needs for decision-making.
    """
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []

    for ref in asset_refs:
        if not isinstance(ref, dict):
            continue
        source_type = str(ref.get("source_type") or ref.get("kind") or "").strip()
        display = str(
            ref.get("display_name")
            or ref.get("original_name")
            or ""
        ).strip()
        if not display:
            continue

        key = (source_type, display)
        if key not in groups:
            attrs = ref.get("attributes") or {}
            domain = str(attrs.get("domain") or "").strip() if isinstance(attrs, dict) else ""
            kind = str(ref.get("kind") or "").strip()
            groups[key] = {
                "source_type": source_type,
                "display_name": display,
                "kind": kind,
                "domain": domain,
                "count": 1,
            }
            order.append(key)
        else:
            groups[key]["count"] += 1

    return [groups[k] for k in order]
