"""Indexical reference detection — routes follow-up queries to L1.

Phase 3: when a user query contains indexical references like '当时' / '我之前
说' / 'just now', route the query to L1 conversation log retrieval (not L2 KG)
by forcing ``query_mode=episode_recall`` and
``l1_retrieval_scope=conversation_only``.

The resolver runs BEFORE the intent decider chain and produces authoritative
routing overrides. Pure heuristic — no LLM. Conservative: returns
``is_indexical=False`` on ambiguous queries so the existing intent-decider
chain handles them.

Design correction (2026-05-22)
------------------------------

Earlier versions extracted a ``temporal_anchor`` (±120s around the most
recent assistant turn) and overlaid it as a ``time_range`` filter on the
retrieval request. That assumption was semantically wrong: in Chinese,
'当时' / '那时' / '上次' (and similar English cues) typically reference
*deep historical context* — a topic discussed days/weeks/months ago —
not the immediate prior turn. ±120s anchoring on the last assistant turn
would systematically filter OUT the actually-referenced events.

A defensive guard (``_MIN_REALISTIC_TIMESTAMP_SECONDS``) accidentally
made production correct by dropping the anchor when callers forgot to
thread real wall-clock timestamps. Threading real timestamps in (a once-
planned follow-up) would have started firing the buggy anchor in
production. The fix is to remove anchor extraction entirely: Phase 3 is
now pure routing override; L1 content matching (BM25 + vector) handles
the actual event finding across all conversation history.

The ``conversation_context`` parameter is retained because it gates
detection — without ANY context to ground the follow-up intent, a cue
match at session start is more likely accidental than indexical.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import ConversationTurn


@dataclass(frozen=True)
class IndexicalResolution:
    """Result of indexical resolution. Authoritative routing overrides
    for the downstream retrieval pipeline when ``is_indexical=True``.

    No temporal anchor — see module docstring for the design correction.
    """
    is_indexical: bool
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


def resolve(
    *,
    query: str,
    conversation_context: Optional[list[ConversationTurn]],
) -> IndexicalResolution:
    """Detect indexical references and produce routing overrides.

    ``is_indexical=True`` requires:
      1. Query contains an indexical cue.
      2. Conversation context is non-empty (at least one prior turn).

    Condition (2) gates accidental cue matches at session start — when no
    prior turn exists, the follow-up intent can't be grounded. Role
    distribution within context is irrelevant (we no longer anchor on
    assistant turns).

    When detected, returns force_mode='episode_recall' and
    l1_retrieval_scope='conversation_only'. L1 content matching (BM25 +
    vector) finds the actually-referenced events across all history.
    """
    cue = _detect_cue(query)
    if not cue:
        return IndexicalResolution(is_indexical=False)

    if not conversation_context:
        # Orphan cue (no context to ground): record but don't override routing.
        return IndexicalResolution(
            is_indexical=False,
            confidence=0.5,
            cue_matched=cue,
        )

    return IndexicalResolution(
        is_indexical=True,
        force_mode="episode_recall",
        l1_retrieval_scope="conversation_only",
        confidence=0.95,
        cue_matched=cue,
    )
