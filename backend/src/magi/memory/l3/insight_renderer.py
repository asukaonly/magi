"""Render L3 insights only from complete host-owned fact descriptions.

L2 producers resolve references and determine description completeness before
constructing reconcile outcomes. This consumer never turns storage values or
trait codes into substitute facts and never calls a wording model.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from ..l2.models import ReconciledTraitOutcome

logger = logging.getLogger(__name__)

InsightKind = Literal["state_change", "trend_shift", "conflict_resolution"]

_RAW_SIGNAL_PATTERNS = (
    re.compile(r"\bRecurring\b.*\bsignal for\b", re.IGNORECASE),
    re.compile(r"\b[a-z][a-z0-9_]*_[a-z0-9_]+\s+signal\b", re.IGNORECASE),
)


def render_insight_content(
    *,
    insight_kind: InsightKind,
    outcomes: list[ReconciledTraitOutcome],
    user_lang_zh: bool,
) -> str | None:
    """Join complete facts; callers skip candidates with incomplete wording."""
    if not outcomes:
        return None
    summaries: list[str] = []
    for outcome in outcomes:
        summary = outcome.natural_summary.strip().rstrip("。.")
        if outcome.fact_completeness != "complete" or not _is_clean_natural_summary(summary):
            logger.info(
                "L3 insight rendering skipped because a fact description is incomplete",
                extra={"insight_kind": insight_kind, "fact_completeness": outcome.fact_completeness},
            )
            return None
        if summary not in summaries:
            summaries.append(summary)
    joined = ("；" if user_lang_zh else "; ").join(summaries[:3])
    return f"{joined}。" if user_lang_zh else f"{joined}."


def _is_clean_natural_summary(summary: str) -> bool:
    return bool(summary) and not any(pattern.search(summary) for pattern in _RAW_SIGNAL_PATTERNS)


__all__ = ["render_insight_content", "InsightKind"]
