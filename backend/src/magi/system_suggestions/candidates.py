"""Union of installed plugin manifests + registry entries into suggestion candidates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class SuggestionCandidate:
    plugin_id: str
    descriptor: Any  # SuggestionDescriptor
    installed: bool


def build_suggestion_candidates(
    installed_manifests: Iterable[Any],
    registry_entries: Iterable[Any],
) -> list[SuggestionCandidate]:
    """Installed manifests (with a descriptor) tagged installed=True, then
    registry entries (with a descriptor) not already installed, installed=False.
    Dedup by plugin_id (installed wins). Manifests/entries without a descriptor
    are skipped."""
    out: list[SuggestionCandidate] = []
    seen: set[str] = set()
    for m in installed_manifests:
        desc = getattr(m, "suggestion_descriptor", None)
        if desc is None:
            continue
        out.append(SuggestionCandidate(plugin_id=m.plugin_id, descriptor=desc, installed=True))
        seen.add(m.plugin_id)
    for e in registry_entries:
        desc = getattr(e, "suggestion_descriptor", None)
        if desc is None or e.plugin_id in seen:
            continue
        out.append(SuggestionCandidate(plugin_id=e.plugin_id, descriptor=desc, installed=False))
        seen.add(e.plugin_id)
    return out
