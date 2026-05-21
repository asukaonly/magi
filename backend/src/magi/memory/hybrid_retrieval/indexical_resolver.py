"""Indexical reference detection and temporal anchor extraction.

Phase 3: when a user query contains indexical references like '当时' / '我之前
说' / 'just now', route the query to L1 conversation log retrieval (not L2 KG)
with a temporal anchor extracted from recent conversation context.

The resolver runs BEFORE the intent decider chain and produces authoritative
overrides for query_mode + l1_retrieval_scope + time_range.

Pure heuristic — no LLM. Conservative: returns is_indexical=False on
ambiguous queries so the existing intent-decider chain handles them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import ConversationTurn


@dataclass(frozen=True)
class IndexicalResolution:
    """Result of indexical resolution. Authoritative overrides for the
    downstream retrieval pipeline when is_indexical=True."""
    is_indexical: bool
    temporal_anchor: Optional[tuple[float, float]] = None
    force_mode: Optional[str] = None
    l1_retrieval_scope: Optional[str] = None
    confidence: float = 0.0
    cue_matched: Optional[str] = None


_INDEXICAL_CUES_CJK: tuple[str, ...] = (
    "当时", "那时", "刚才", "上次", "上回",
    "我说过", "我说的", "我刚说", "我之前说",
    "我刚问", "我之前问",
)

_INDEXICAL_CUES_EN = re.compile(
    r"\b("
    r"just\s+now|earlier|last\s+time|last\s+turn|"
    r"what\s+i\s+(?:said|told|asked)|"
    r"i\s+(?:said|told|mentioned|asked)\s+(?:before|earlier|previously)"
    r")\b",
    re.IGNORECASE,
)

# ±2 minutes around the anchor turn. Configurable as a module-level constant.
ANCHOR_WINDOW_SECONDS = 120.0

# Defensive sanity check: real chat events occur after 2001-09-09 (unix sec
# 1_000_000_000). If a caller forgets to thread real timestamps in and the
# turns default to ``0.0``, the naive anchor would be ``(-120, +120)`` —
# epoch ± 2min — which actively prunes ALL real L1 events from indexical
# query results. Below this threshold we drop the anchor (keeping the
# ``force_mode`` + ``l1_retrieval_scope`` overrides intact) so the indexical
# routing still fires but the time filter is omitted.
_MIN_REALISTIC_TIMESTAMP_SECONDS = 1_000_000_000.0


def _detect_cue(query: str) -> Optional[str]:
    """Return the matched cue (for observability) or None."""
    if not query:
        return None
    for cue in _INDEXICAL_CUES_CJK:
        if cue in query:
            return cue
    en_match = _INDEXICAL_CUES_EN.search(query)
    if en_match:
        return en_match.group(0)
    return None


def _find_latest_assistant_turn(
    conversation_context: list[ConversationTurn],
) -> Optional[ConversationTurn]:
    """Return the most recent assistant turn in context, or None."""
    if not conversation_context:
        return None
    for turn in reversed(conversation_context):
        if turn.role == "assistant":
            return turn
    return None


def _extract_anchor_from_context(
    conversation_context: list[ConversationTurn],
) -> Optional[tuple[float, float]]:
    """Anchor on the most recent assistant turn — that's typically what
    'when I said back then' references in a follow-up.

    Returns (start, end) timestamp range, ±ANCHOR_WINDOW_SECONDS around the
    anchor turn. Returns None if no assistant turn in context OR if the
    most-recent assistant turn carries a clearly-bogus timestamp (e.g. the
    epoch-default ``0.0`` when callers forget to thread real wall-clock
    times). The bogus-timestamp guard prevents an actively-harmful
    ``(-120, +120)`` window from pruning every real L1 event.
    """
    turn = _find_latest_assistant_turn(conversation_context)
    if turn is None:
        return None
    if turn.timestamp < _MIN_REALISTIC_TIMESTAMP_SECONDS:
        # Refuse to anchor on a fake/epoch timestamp; the upstream is
        # responsible for threading real timestamps but we must not
        # silently corrupt retrieval when they fail to do so.
        return None
    return (
        turn.timestamp - ANCHOR_WINDOW_SECONDS,
        turn.timestamp + ANCHOR_WINDOW_SECONDS,
    )


def resolve(
    *,
    query: str,
    conversation_context: Optional[list[ConversationTurn]],
) -> IndexicalResolution:
    """Detect indexical references and produce routing overrides.

    ``is_indexical=True`` requires:
    1. Query contains an indexical cue
    2. Conversation context contains at least one assistant turn

    A realistic timestamp on that assistant turn is preferred but not
    required — when the timestamp is missing/epoch we still fire the
    routing overrides (``force_mode`` + ``l1_retrieval_scope``) but omit
    ``temporal_anchor`` so downstream does not apply a bogus time filter.
    """
    cue = _detect_cue(query)
    if not cue:
        return IndexicalResolution(is_indexical=False)

    context = conversation_context or []
    assistant_turn = _find_latest_assistant_turn(context)
    if assistant_turn is None:
        # No assistant turn to anchor against; the cue alone is too weak
        # to override routing.
        return IndexicalResolution(
            is_indexical=False,
            confidence=0.5,
            cue_matched=cue,
        )

    anchor = _extract_anchor_from_context(context)
    # Confidence drops slightly when we have a turn but no usable timestamp,
    # so observers can see the degraded mode in traces.
    confidence = 0.95 if anchor is not None else 0.85
    return IndexicalResolution(
        is_indexical=True,
        temporal_anchor=anchor,
        force_mode="episode_recall",
        l1_retrieval_scope="conversation_only",
        confidence=confidence,
        cue_matched=cue,
    )
