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


def partition_for_candidates(
    packages: Iterable[Any],
    registry_entries: Iterable[Any],
) -> tuple[list[Any], list[Any]]:
    """Split inputs into the (installed_manifests, registry_entries) lists to feed
    :func:`build_suggestion_candidates`, applying the "don't suggest what the user
    already has on" rule:

    - Installed plugins that are **enabled** (already in use) are dropped entirely
      — neither suggested to "connect" nor (via registry) to "install".
    - Installed plugins that are **not enabled** are kept as connect candidates.
    - Registry entries are kept only when their plugin isn't installed at all.

    ``packages`` are plugin package states (each has ``.manifest`` + ``.enabled``).
    """
    all_installed_ids = {p.manifest.plugin_id for p in packages}
    inactive_manifests = [p.manifest for p in packages if not getattr(p, "enabled", False)]
    not_installed_registry = [
        e for e in registry_entries if e.plugin_id not in all_installed_ids
    ]
    return inactive_manifests, not_installed_registry
