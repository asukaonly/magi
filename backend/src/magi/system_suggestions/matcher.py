"""Signal matcher — given recent text + suggestion candidates, surface suggestions.

The matcher is split into two reusable pure functions:

* :func:`candidate_categories` — a cheap keyword *gate* that groups
  available + undismissed suggestion candidates (whose locale keywords appear in
  the recent text) by category. Candidates may be installed plugins *or*
  registry-discovered (not-yet-installed) plugins; each carries its installation
  state. This is cheap enough to run on every
  message.
* :func:`build_proposals` — a proposal builder that ranks candidate categories
  into :class:`SuggestionProposal` objects, using LLM confidences when available
  and degrading to keyword-hit scoring when not.

An LLM classifier + throttle are wired around these two functions via
``engine.py`` (:func:`magi.system_suggestions.engine.run_suggestion_check`),
which the ``/system-suggestions/check`` route calls directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from magi.system_suggestions.contracts import SuggestionPlugin, SuggestionProposal


@dataclass
class CategoryCandidate:
    """A category that passed the keyword gate, with its matched plugins.

    Sibling plugins (e.g. chrome-history / edge-history both under
    ``browser_history``) collapse into a single candidate so the suggestion UI
    can bundle them.

    Each plugin carries its installation state so the UI can offer an
    install-first flow without another catalogue lookup.
    """

    category: str
    plugins: list[SuggestionPlugin] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    rationale: dict[str, str] = field(default_factory=dict)
    keyword_hits: int = 0


def candidate_categories(
    *,
    recent_text: str,
    locale: str,
    candidates: Iterable,
    is_available: Callable[[str], bool],
    is_dismissed: Callable[[str], bool],
) -> dict[str, CategoryCandidate]:
    """Cheap keyword gate.

    Group available + undismissed suggestion candidates whose locale keywords
    appear in ``recent_text``, keyed by category.

    Args:
        recent_text: User message + agent response concatenated.
        locale: 'zh' or 'en' — picks which keyword list to match against.
        candidates: Iterable of suggestion candidates, each exposing
            ``.plugin_id``, ``.descriptor`` (a ``SuggestionDescriptor``), and
            ``.installed`` (bool).
        is_available: Returns True if the plugin can run on this device.
        is_dismissed: Returns True if a category (dedupe_key) is currently
            suppressed.

    Returns:
        Mapping of category -> :class:`CategoryCandidate` for every category
        with at least one matching, available, undismissed candidate. Candidates
        with ``installed is False`` retain that state in their plugin metadata.
    """
    text_lower = recent_text.lower()
    out: dict[str, CategoryCandidate] = {}
    for c in candidates:
        descriptor = c.descriptor
        if descriptor is None:
            continue
        keywords = descriptor.triggers.keywords.get(locale, [])
        hits = [kw for kw in keywords if kw.lower() in text_lower]
        if not hits:
            continue
        category = descriptor.category
        if is_dismissed(category):
            continue
        if not is_available(c.plugin_id):
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
        cand.plugins.append(
            SuggestionPlugin(
                plugin_id=c.plugin_id,
                name=c.name,
                name_i18n=c.name_i18n,
                icon=c.icon,
                installed=c.installed,
            )
        )
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
                plugins=cand.plugins,
                confidence=min(1.0, max(0.0, float(conf))),
                rationale=cand.rationale,
            )
        )
    proposals.sort(key=lambda p: p.confidence, reverse=True)
    return proposals
