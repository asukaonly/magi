"""Plugin manifest discovery and package-state projection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from ..config import get_config, save_config
from ..config.models import PluginSettings
from ..utils.packaged_paths import get_repo_root
from .contracts import (
    ContributionType,
    PluginContribution,
    PluginManifest,
    PluginPackageState,
)
from .icon_assets import encode_plugin_icon_asset


def resolve_plugin_search_paths() -> list[Path]:
    config = get_config()
    repo_root = get_repo_root()
    builtin_root = default_builtin_root()
    resolved: list[Path] = [builtin_root]
    for raw_path in config.plugins.scan_paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (repo_root / raw_path).resolve()
        if path not in resolved:
            resolved.append(path)
    return resolved


def discover_plugin_manifests(search_paths: Iterable[Path]) -> dict[str, PluginManifest]:
    discovered: dict[str, PluginManifest] = {}
    for root in search_paths:
        if not root.exists():
            continue
        source = "builtin" if is_builtin_root(root) else "external"
        for manifest_path in root.rglob("plugin.toml"):
            manifest = load_plugin_manifest(manifest_path, source=source)
            discovered[manifest.plugin_id] = manifest
    return discovered


def persist_new_plugin_packages(
    manifests: Mapping[str, PluginManifest],
    *,
    config: Any | None = None,
    save: Callable[[dict[str, Any]], Any] = save_config,
) -> None:
    config = config or get_config()
    updates: dict[str, Any] = {}
    for plugin_id, manifest in manifests.items():
        if plugin_id in config.plugins.packages:
            continue
        if manifest.kind == "library":
            enabled = True
            trusted = True
        else:
            enabled = bool(manifest.official and manifest.source == "builtin")
            trusted = enabled
        updates[f"plugins.packages.{plugin_id}.enabled"] = enabled
        updates[f"plugins.packages.{plugin_id}.trusted"] = trusted
        updates[f"plugins.packages.{plugin_id}.source"] = manifest.source
        updates[f"plugins.packages.{plugin_id}.manifest_path"] = manifest.manifest_path
        updates[f"plugins.packages.{plugin_id}.official"] = (
            bool(manifest.official) if manifest.source == "builtin" else False
        )
        updates[f"plugins.packages.{plugin_id}.settings"] = {}
    if updates:
        save(updates)


def build_package_states(
    *,
    manifests: Mapping[str, PluginManifest],
    packages: Mapping[str, Any],
    previous_states: Mapping[str, PluginPackageState],
) -> dict[str, PluginPackageState]:
    next_states: dict[str, PluginPackageState] = {}
    for plugin_id, manifest in manifests.items():
        package_cfg = coerce_package_settings(packages.get(plugin_id))
        enabled = bool(package_cfg.enabled) if package_cfg is not None else False
        trusted = bool(package_cfg.trusted) if package_cfg is not None else False
        current_settings = dict(package_cfg.settings) if package_cfg is not None else {}
        previous_state = previous_states.get(plugin_id)
        next_states[plugin_id] = PluginPackageState(
            manifest=manifest,
            enabled=enabled,
            trusted=trusted,
            loaded=bool(previous_state.loaded) if previous_state is not None else False,
            healthy=bool(previous_state.healthy) if previous_state is not None else True,
            last_error=previous_state.last_error if previous_state is not None else None,
            contributions=list(previous_state.contributions)
            if previous_state is not None
            else placeholder_contributions(manifest),
            current_settings=current_settings,
        )
    return next_states


def load_plugin_manifest(manifest_path: Path, *, source: str) -> PluginManifest:
    with manifest_path.open("rb") as fp:
        raw = tomllib.load(fp)
    plugin_block = raw.get("plugin", raw)
    manifest = PluginManifest.model_validate(
        {
            **plugin_block,
            "plugin_dir": str(manifest_path.parent),
            "manifest_path": str(manifest_path),
            "source": source,
        }
    )
    encode_plugin_icon_asset(manifest.icon, manifest_path.parent)
    return manifest


def placeholder_contributions(manifest: PluginManifest) -> list[PluginContribution]:
    surface_map = {
        ContributionType.TOOL: "tools",
        ContributionType.SENSOR: "timeline",
        ContributionType.CHANNEL: "extensions",
    }
    return [
        PluginContribution(
            plugin_id=manifest.plugin_id,
            contribution_id=f"{manifest.plugin_id}:{contribution_type.value}",
            contribution_type=contribution_type,
            display_name=manifest.name,
            description=manifest.description,
            surface=surface_map.get(contribution_type, "extensions"),
        )
        for contribution_type in manifest.contribution_types
    ]


def coerce_package_settings(value: Any) -> PluginSettings | None:
    if value is None:
        return None
    if isinstance(value, PluginSettings):
        return value
    if isinstance(value, dict):
        return PluginSettings.model_validate(value)
    return None


def is_builtin_root(path: Path) -> bool:
    return path == default_builtin_root()


def default_builtin_root() -> Path:
    return get_repo_root() / "plugins"
