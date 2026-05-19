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
    # Step 1: keep events with non-empty content, normalize.
    candidates: list[tuple[float, str]] = []
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
        candidates.append((ts, text))

    if not candidates:
        return []

    # Step 2: sort by length desc so the most-informative survives dedup;
    # longer strings tend to carry titles + context, shorter ones are
    # boilerplate window names.
    candidates.sort(key=lambda pair: len(pair[1]), reverse=True)

    # Step 3: dedupe by lowercased 40-char prefix.
    seen_prefixes: set[str] = set()
    kept: list[tuple[float, str]] = []
    for ts, text in candidates:
        prefix = text[:DEDUP_PREFIX_LEN].lower().strip()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        kept.append((ts, text))
        if len(kept) >= max_excerpts:
            break

    # Step 4: re-sort chronologically; LLM reads events in user-experienced order.
    kept.sort(key=lambda pair: pair[0])

    # Step 5: truncate to per-excerpt char budget.
    return [_truncate(text, max_chars_per_excerpt) for _, text in kept]


def _truncate(text: str, max_chars: int) -> str:
    """Truncate to ``max_chars`` characters, appending ``…`` if cut.

    Counts characters, not bytes — works for CJK without surprises.
    """
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
