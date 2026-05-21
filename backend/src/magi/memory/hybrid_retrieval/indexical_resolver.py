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


def _extract_anchor_from_context(
    conversation_context: list[ConversationTurn],
) -> Optional[tuple[float, float]]:
    """Anchor on the most recent assistant turn — that's typically what
    'when I said back then' references in a follow-up.

    Returns (start, end) timestamp range, ±ANCHOR_WINDOW_SECONDS around the
    anchor turn. Returns None if no assistant turn in context.
    """
    if not conversation_context:
        return None
    for turn in reversed(conversation_context):
        if turn.role == "assistant":
            return (
                turn.timestamp - ANCHOR_WINDOW_SECONDS,
                turn.timestamp + ANCHOR_WINDOW_SECONDS,
            )
    return None


def resolve(
    *,
    query: str,
    conversation_context: Optional[list[ConversationTurn]],
) -> IndexicalResolution:
    """Detect indexical references and produce routing overrides.

    Two conditions must both be true for is_indexical=True:
    1. Query contains an indexical cue
    2. Conversation context contains at least one assistant turn (to anchor on)

    If only the cue is present but context is missing or has no assistant turn,
    returns is_indexical=False with confidence=0.5 and cue_matched populated —
    downstream sees the cue annotation in the trace but doesn't force a route.
    """
    cue = _detect_cue(query)
    if not cue:
        return IndexicalResolution(is_indexical=False)

    anchor = _extract_anchor_from_context(conversation_context or [])
    if anchor is None:
        return IndexicalResolution(
            is_indexical=False,
            confidence=0.5,
            cue_matched=cue,
        )

    return IndexicalResolution(
        is_indexical=True,
        temporal_anchor=anchor,
        force_mode="episode_recall",
        l1_retrieval_scope="conversation_only",
        confidence=0.95,
        cue_matched=cue,
    )
