"""Orchestrates a /system-suggestions/check: gate -> throttle -> classify -> build."""
from __future__ import annotations

from typing import Awaitable, Callable, Iterable

from magi.core.logger import get_logger
from magi.system_suggestions.contracts import SuggestionProposal
from magi.system_suggestions.matcher import (
    CategoryCandidate,
    build_proposals,
    candidate_categories,
)
from magi.system_suggestions.throttle import SuggestionThrottle

logger = get_logger(__name__)

# classify(recent_text, [{category, rationale, keywords}], locale) -> {category: confidence}
ClassifyFn = Callable[[str, list[dict], str], Awaitable[dict[str, float]]]


async def run_suggestion_check(
    *,
    recent_text: str,
    locale: str,
    session_id: str,
    plugin_manifests: Iterable,
    is_available: Callable[[str], bool],
    is_dismissed: Callable[[str], bool],
    classify: ClassifyFn,
    throttle: SuggestionThrottle,
) -> list[SuggestionProposal]:
    cands = candidate_categories(
        recent_text=recent_text,
        locale=locale,
        plugin_manifests=plugin_manifests,
        is_available=is_available,
        is_dismissed=is_dismissed,
    )
    if not cands:
        return []
    sig = frozenset(cands.keys())
    if not throttle.should_classify(session_id, sig):
        return throttle.get_cached(session_id)

    confidences: dict[str, float] | None = None
    try:
        confidences = await classify(recent_text, _classify_payload(cands, locale), locale)
    except Exception as exc:  # degrade to keyword
        logger.warning("suggestion classify failed; degrading to keyword", error=str(exc))
        confidences = None

    proposals = build_proposals(cands, confidences)
    throttle.store(session_id, sig, proposals)
    return proposals


def _classify_payload(cands: dict[str, CategoryCandidate], locale: str) -> list[dict]:
    return [
        {
            "category": c.category,
            "rationale": c.rationale.get(locale, c.rationale.get("en", "")),
            "keywords": c.keywords,
        }
        for c in cands.values()
    ]
