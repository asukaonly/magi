"""Shared 3-tier renderer for L3 insight content.

Strategy (in order):
  1. natural_summary — if every outcome carries non-empty natural_summary
     (the L2 Phase 2 LLM already wrote a natural-language sentence per
     assertion), join them as a sentence.
  2. trait_family — if every outcome's trait_family is in the closed enum,
     render via "[family_label]: [value]" style template.
     Uses NO raw trait_name strings.
  3. None — caller must skip the insight. We refuse to render content
     that would leak schema identifiers (e.g. "state.sleep_quality")
     to the user.

This module is the single chokepoint for insight content generation.
Adding new insight kinds means extending this file, not duplicating
the rendering logic per service.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from ... import i18n as core_i18n
from ..l2.models import ReconciledTraitOutcome
from .insight_utils import compact_values, decode_value, locale_for_zh, trait_family_label

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
    """Render insight content with 3-tier degradation. None = skip.

    Args:
        insight_kind: which insight service is calling. Affects framing
            phrases (e.g. "长期趋势..." for trend_shift).
        outcomes: the L2 reconcile outcomes that triggered the insight.
        user_lang_zh: True for Chinese output, False for English.

    Returns:
        Rendered content string, or None if no clean rendering is possible.
        Callers must propagate the None (i.e., return None from build_candidate)
        rather than fabricate output.
    """
    if not outcomes:
        return None

    # ─── Tier 1: natural_summary ────────────────────────────────────
    summaries: list[str] = []
    for outcome in outcomes:
        summary = str(getattr(outcome, "natural_summary", "") or "").strip().rstrip("。.")
        if summary and _is_clean_natural_summary(summary) and summary not in summaries:
            summaries.append(summary)
    if len(summaries) == len(outcomes) and summaries:
        # All outcomes had a natural_summary — premium path.
        return _frame(summaries[:3], insight_kind=insight_kind, zh=user_lang_zh, source="natural_summary")

    # ─── Tier 2: trait_family fallback ──────────────────────────────
    family_fragments: list[str] = []
    all_families_known = True
    for outcome in outcomes:
        family = str(getattr(outcome, "trait_family", "") or "").strip()
        family_lbl = trait_family_label(family, zh=user_lang_zh) if family else None
        if not family_lbl:
            all_families_known = False
            break
        value_decoded = decode_value(str(outcome.winning_value or ""))
        readable_value = compact_values([value_decoded], zh=user_lang_zh)
        if not readable_value:
            all_families_known = False
            break
        family_fragments.append(_family_phrase(family_lbl, readable_value, zh=user_lang_zh))
    if all_families_known and family_fragments:
        return _frame(family_fragments[:3], insight_kind=insight_kind, zh=user_lang_zh, source="trait_family")

    # ─── Tier 3: skip ────────────────────────────────────────────────
    logger.info(
        "L3 insight rendering skipped — no clean rendering available",
        extra={
            "insight_kind": insight_kind,
            "outcome_count": len(outcomes),
            "missing_natural_summary": sum(1 for o in outcomes if not getattr(o, "natural_summary", "")),
            "missing_trait_family": sum(1 for o in outcomes if not getattr(o, "trait_family", "")),
        },
    )
    return None


def _is_clean_natural_summary(summary: str) -> bool:
    text = str(summary or "").strip()
    if not text:
        return False
    return not any(pattern.search(text) for pattern in _RAW_SIGNAL_PATTERNS)


def _family_phrase(family_label: str, value: str, *, zh: bool) -> str:
    """Render '<family>: <value>' style fragment."""
    if zh:
        return f"{family_label}：{value}"
    return f"{family_label}: {value}"


def _frame(
    fragments: list[str],
    *,
    insight_kind: InsightKind,
    zh: bool,
    source: str,
) -> str:
    """Wrap fragments in a kind-specific introductory frame."""
    if source == "natural_summary":
        # The L2 LLM already wrote natural sentences — just join them.
        joined = ("；" if zh else "; ").join(fragments)
        return f"{joined}。" if zh else f"{joined}."

    # source == "trait_family" — add a kind-specific frame for context.
    joined = ("；" if zh else "; ").join(fragments)
    fallback = joined
    if zh:
        if insight_kind == "state_change":
            fallback = f"你的{joined}。"
        if insight_kind == "trend_shift":
            fallback = f"长期趋势 — 你的{joined}。"
        if insight_kind == "conflict_resolution":
            fallback = f"出现冲突 — 你的{joined}。"
    else:
        if insight_kind == "state_change":
            fallback = f"Your {joined}."
        if insight_kind == "trend_shift":
            fallback = f"Longer-span trend — your {joined}."
        if insight_kind == "conflict_resolution":
            fallback = f"Conflict detected — your {joined}."
    return core_i18n.t(
        f"memory.l3.insight.frames.{insight_kind}",
        language=locale_for_zh(zh),
        fallback=fallback,
        fragments=joined,
    )


__all__ = ["render_insight_content", "InsightKind"]
