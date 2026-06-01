"""Pack L1 event content into concise excerpts for the diary LLM prompt.

The diary LLM previously only saw episode-level metadata (label, topic keys,
entity ids). That made it write generic prose because it had no idea what the
user *actually* did inside each episode. This module produces a small list of
specific content snippets per episode — page titles browsed, messages sent,
window titles — that the prompt builder injects under each episode block.

Design:
  - Pure functions, no I/O. Caller (orchestrator) does the L1 fetch.
  - Pick by content length (longer == usually more informative than "Chrome
    (browsing)" boilerplate), then dedupe by a 40-char prefix to kill the
    "same tab visited 9 times" noise.
  - Final list is re-sorted chronologically so the LLM reads events in the
    order they happened — easier to write coherent narrative.
"""

from __future__ import annotations

from typing import Any, Iterable


DEFAULT_MAX_EXCERPTS = 5
DEFAULT_MAX_CHARS = 80
DEDUP_PREFIX_LEN = 40


def build_excerpts(
    l1_events: Iterable[dict[str, Any]],
    *,
    max_excerpts: int = DEFAULT_MAX_EXCERPTS,
    max_chars_per_excerpt: int = DEFAULT_MAX_CHARS,
) -> list[str]:
    """Pick up to N representative content strings from a window of L1 events.

    Args:
        l1_events: Sequence of L1 event dicts as returned by
            ``L1EventQueriesMixin.query_events``. Reads ``content`` and
            ``timestamp`` fields; everything else is ignored.
        max_excerpts: Upper bound on returned excerpts. Default 5.
        max_chars_per_excerpt: Truncate any single excerpt longer than this.
            A trailing ``…`` is appended on truncation. Default 80 chars.

    Returns:
        List of cleaned content strings, chronologically ordered (oldest
        first). Empty list when there are no events with usable content.
    """
    # Step 1: keep events with non-empty content, normalize. Manual-entry
    # events get a "用户原话：" prefix so the LLM treats them as the
    # highest-signal evidence in the bundle — they ARE the user's words.
    candidates: list[tuple[float, str, bool]] = []  # (ts, text, is_manual)
    for event in l1_events:
        raw = event.get("content")
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        try:
            ts = float(event.get("timestamp") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        is_manual = str(event.get("source") or "") == "manual_entry"
        candidates.append((ts, text, is_manual))

    if not candidates:
        return []

    # Step 2: sort. Manual entries first (regardless of length), then by
    # length desc within each group so the most-informative survives dedup.
    candidates.sort(key=lambda triple: (not triple[2], -len(triple[1])))

    # Step 3: dedupe by lowercased 40-char prefix.
    seen_prefixes: set[str] = set()
    kept: list[tuple[float, str, bool]] = []
    for triple in candidates:
        ts, text, is_manual = triple
        prefix = text[:DEDUP_PREFIX_LEN].lower().strip()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        kept.append(triple)
        if len(kept) >= max_excerpts:
            break

    # Step 4: re-sort chronologically; LLM reads events in user-experienced order.
    kept.sort(key=lambda triple: triple[0])

    # Step 5: truncate to per-excerpt char budget. Manual entries get a
    # tag so the LLM's prompt-side instructions can reference them.
    out: list[str] = []
    for _, text, is_manual in kept:
        body = _truncate(text, max_chars_per_excerpt)
        out.append(f"用户原话：{body}" if is_manual else body)
    return out


def _truncate(text: str, max_chars: int) -> str:
    """Truncate to ``max_chars`` characters, appending ``…`` if cut.

    Counts characters, not bytes — works for CJK without surprises.
    """
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
