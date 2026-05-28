"""Signal matcher — given recent text + plugin manifests, surface suggestions.

This implementation is keyword-only (v1). Future enhancement: hook in the
question_classifier output to consume Triggers.intents and Triggers.entities
as well — for v1, those fields are reserved but unused.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from magi.system_suggestions.contracts import SuggestionProposal
from magi_plugin_sdk.contracts import PluginManifest, SuggestionDescriptor


def _keyword_match_score(
    descriptor: SuggestionDescriptor,
    *,
    recent_text_lower: str,
    locale: str,
) -> float:
    """Compute a 0-1 confidence based on number of keyword hits in the given locale.

    Returns 0.0 if no keywords match. The score saturates at 1.0 after 3+ hits.
    """
    keywords = descriptor.triggers.keywords.get(locale, [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in recent_text_lower)
    if hits == 0:
        return 0.0
    return min(1.0, 0.5 + 0.25 * (hits - 1))


def find_suggestions(
    *,
    recent_text: str,
    locale: str,
    plugin_manifests: Iterable[PluginManifest],
    is_available: Callable[[str], bool],
    is_dismissed: Callable[[str], bool],
) -> list[SuggestionProposal]:
    """Run the matcher.

    Args:
        recent_text: User message + agent response concatenated.
        locale: 'zh' or 'en' — picks which keyword list to match against.
        plugin_manifests: All installed plugin manifests (matcher filters to
            those with a suggestion_descriptor).
        is_available: Callable returning True if the plugin can run on this
            device. Plan 1's AvailabilityResolver provides this.
        is_dismissed: Callable returning True if a category (dedupe_key) is
            currently suppressed.

    Returns:
        Ranked list of SuggestionProposal (highest confidence first), with
        same-category plugins bundled into one proposal.
    """
    recent_text_lower = recent_text.lower()
    by_category: dict[str, list[tuple[str, float, dict[str, str]]]] = defaultdict(list)

    for manifest in plugin_manifests:
        descriptor = manifest.suggestion_descriptor
        if descriptor is None:
            continue
        score = _keyword_match_score(
            descriptor, recent_text_lower=recent_text_lower, locale=locale
        )
        if score <= 0.0:
            continue
        if not is_available(manifest.plugin_id):
            continue
        if is_dismissed(descriptor.category):
            continue
        rationale = {
            "zh": descriptor.rationale.zh,
            "en": descriptor.rationale.en,
        }
        by_category[descriptor.category].append(
            (manifest.plugin_id, score, rationale)
        )

    proposals: list[SuggestionProposal] = []
    for category, entries in by_category.items():
        plugin_ids = [pid for pid, _, _ in entries]
        avg_confidence = sum(score for _, score, _ in entries) / len(entries)
        best_rationale = max(entries, key=lambda e: e[1])[2]
        proposals.append(
            SuggestionProposal(
                dedupe_key=category,
                category=category,
                plugin_ids=plugin_ids,
                confidence=avg_confidence,
                rationale=best_rationale,
            )
        )
    proposals.sort(key=lambda p: p.confidence, reverse=True)
    return proposals
