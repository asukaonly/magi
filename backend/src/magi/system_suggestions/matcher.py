"""Signal matcher — given recent text + plugin manifests, surface suggestions.

The matcher is split into two reusable pure functions:

* :func:`candidate_categories` — a cheap keyword *gate* that groups
  installed + available + undismissed plugins (whose locale keywords appear in
  the recent text) by category. This is cheap enough to run on every message.
* :func:`build_proposals` — a proposal builder that ranks candidate categories
  into :class:`SuggestionProposal` objects, using LLM confidences when available
  and degrading to keyword-hit scoring when not.

A later task wires an LLM classifier + throttle around these via an
``engine.py``.

NOTE: :func:`find_suggestions` is a thin backward-compat wrapper kept only so
the existing ``system_suggestions_routes.py`` (and its tests) stay importable
and green. Task B6 rewrites that route around the two functions above and
should delete this wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from magi.system_suggestions.contracts import SuggestionProposal
from magi_plugin_sdk.contracts import PluginManifest


@dataclass
class CategoryCandidate:
    """A category that passed the keyword gate, with its matched plugins.

    Sibling plugins (e.g. chrome-history / edge-history both under
    ``browser_history``) collapse into a single candidate so the suggestion UI
    can bundle them.
    """

    category: str
    plugin_ids: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    rationale: dict[str, str] = field(default_factory=dict)
    keyword_hits: int = 0


def candidate_categories(
    *,
    recent_text: str,
    locale: str,
    plugin_manifests: Iterable[PluginManifest],
    is_available: Callable[[str], bool],
    is_dismissed: Callable[[str], bool],
) -> dict[str, CategoryCandidate]:
    """Cheap keyword gate.

    Group installed + available + undismissed plugins whose locale keywords
    appear in ``recent_text``, keyed by category.

    Args:
        recent_text: User message + agent response concatenated.
        locale: 'zh' or 'en' — picks which keyword list to match against.
        plugin_manifests: All installed plugin manifests (those without a
            ``suggestion_descriptor`` are skipped).
        is_available: Returns True if the plugin can run on this device.
        is_dismissed: Returns True if a category (dedupe_key) is currently
            suppressed.

    Returns:
        Mapping of category -> :class:`CategoryCandidate` for every category
        with at least one matching, available, undismissed plugin.
    """
    text_lower = recent_text.lower()
    out: dict[str, CategoryCandidate] = {}
    for manifest in plugin_manifests:
        descriptor = manifest.suggestion_descriptor
        if descriptor is None:
            continue
        keywords = descriptor.triggers.keywords.get(locale, [])
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if not hits:
            continue
        category = descriptor.category
        if is_dismissed(category):
            continue
        if not is_available(manifest.plugin_id):
            continue
        cand = out.get(category)
        if cand is None:
            cand = CategoryCandidate(
                category=category,
                rationale={
                    "zh": descriptor.rationale.zh,
                    "en": descriptor.rationale.en,
                },
            )
            out[category] = cand
        cand.plugin_ids.append(manifest.plugin_id)
        for kw in keywords:
            if kw not in cand.keywords:
                cand.keywords.append(kw)
        cand.keyword_hits = max(cand.keyword_hits, len(hits))
    return out


def _keyword_confidence(hits: int) -> float:
    """0-1 confidence from keyword-hit count; saturates at 1.0 after 3+ hits."""
    if hits <= 0:
        return 0.0
    return min(1.0, 0.5 + 0.25 * (hits - 1))


def build_proposals(
    candidates: dict[str, CategoryCandidate],
    confidences: dict[str, float] | None,
) -> list[SuggestionProposal]:
    """Build ranked proposals from candidate categories.

    With ``confidences`` (an LLM classification result), use the per-category
    score and drop categories scored <= 0 or absent. Without it
    (``confidences is None`` = degrade path), use keyword-hit confidence.

    Returns proposals sorted by confidence, highest first.
    """
    proposals: list[SuggestionProposal] = []
    for category, cand in candidates.items():
        if confidences is not None:
            conf = confidences.get(category)
            if conf is None or conf <= 0.0:
                continue
        else:
            conf = _keyword_confidence(cand.keyword_hits)
            if conf <= 0.0:
                continue
        proposals.append(
            SuggestionProposal(
                dedupe_key=category,
                category=category,
                plugin_ids=cand.plugin_ids,
                confidence=min(1.0, max(0.0, float(conf))),
                rationale=cand.rationale,
            )
        )
    proposals.sort(key=lambda p: p.confidence, reverse=True)
    return proposals


def find_suggestions(
    *,
    recent_text: str,
    locale: str,
    plugin_manifests: Iterable[PluginManifest],
    is_available: Callable[[str], bool],
    is_dismissed: Callable[[str], bool],
) -> list[SuggestionProposal]:
    """DEPRECATED keyword-only matcher kept for backward compatibility.

    Thin wrapper over :func:`candidate_categories` + :func:`build_proposals`
    (keyword-degrade path). Retained only so the legacy
    ``system_suggestions_routes.py`` stays importable; Task B6 rewrites the
    route around the two functions above and should delete this wrapper.
    """
    candidates = candidate_categories(
        recent_text=recent_text,
        locale=locale,
        plugin_manifests=plugin_manifests,
        is_available=is_available,
        is_dismissed=is_dismissed,
    )
    return build_proposals(candidates, confidences=None)
