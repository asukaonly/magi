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
    active_plugin_ids: set[str] | None = None,
) -> tuple[list[Any], list[Any]]:
    """Split inputs into the (installed_manifests, registry_entries) lists to feed
    :func:`build_suggestion_candidates`, applying the "don't suggest what the user
    already has on" rule:

    - Plugins whose data source is already **in use** (id in ``active_plugin_ids``)
      are dropped entirely — neither suggested to "connect" nor to "install".
    - Sibling plugins in the same suggestion category are also dropped. Once a
      browser-history source is active, for example, another browser is not a
      useful replacement recommendation.
    - Other installed plugins are kept as connect candidates.
    - Registry entries are kept only when their plugin isn't installed and isn't
      already active.

    ``active_plugin_ids`` is the set of plugin ids that have an enabled **and**
    configured sensor source. This is the source-level signal (``sensors.<source>
    .enabled`` + the activation flow's ``configured_key``), NOT the package-level
    ``PluginPackageState.enabled`` flag — a plugin package can be loaded/enabled
    while its data source has never been activated, in which case we DO still want
    to suggest connecting it.

    ``packages`` are plugin package states (each has ``.manifest``).
    """
    active = active_plugin_ids or set()
    package_list = list(packages)
    registry_list = list(registry_entries)

    def _category(item: Any) -> str | None:
        descriptor = getattr(item, "suggestion_descriptor", None)
        category = getattr(descriptor, "category", None)
        return str(category) if category else None

    all_descriptors = [p.manifest for p in package_list] + registry_list
    active_categories = {
        category
        for item in all_descriptors
        if item.plugin_id in active and (category := _category(item)) is not None
    }

    def _is_active_or_covered(item: Any) -> bool:
        return item.plugin_id in active or _category(item) in active_categories

    all_installed_ids = {p.manifest.plugin_id for p in package_list}
    connect_manifests = [
        p.manifest for p in package_list if not _is_active_or_covered(p.manifest)
    ]
    not_installed_registry = [
        e
        for e in registry_list
        if e.plugin_id not in all_installed_ids and not _is_active_or_covered(e)
    ]
    return connect_manifests, not_installed_registry
