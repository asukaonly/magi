"""Plugin manifest discovery and package-state projection."""

from __future__ import annotations

from collections.abc import Callable
import logging
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
from . import package_files
from .package_integrity import package_identity_error

logger = logging.getLogger(__name__)
MAX_PLUGIN_MANIFEST_BYTES = 256 * 1024


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
    for root in _ordered_plugin_search_paths(search_paths):
        if not root.exists():
            continue
        source = "builtin" if is_builtin_root(root) else "external"
        for manifest_path in _manifest_paths_for_root(root):
            relative_manifest = manifest_path.relative_to(root)
            if any(part.startswith(".") for part in relative_manifest.parts[:-1]):
                continue
            declared_id = _read_declared_plugin_id(manifest_path)
            existing = discovered.get(declared_id) if declared_id is not None else None
            if existing is not None:
                _log_duplicate_manifest(
                    plugin_id=declared_id,
                    kept=existing,
                    ignored_path=manifest_path,
                    ignored_source=source,
                )
                continue

            manifest = load_plugin_manifest(manifest_path, source=source)
            existing = discovered.get(manifest.plugin_id)
            if existing is not None:
                _log_duplicate_manifest(
                    plugin_id=manifest.plugin_id,
                    kept=existing,
                    ignored_path=manifest_path,
                    ignored_source=source,
                )
                continue
            discovered[manifest.plugin_id] = manifest
    return discovered


def _ordered_plugin_search_paths(search_paths: Iterable[Path]) -> list[Path]:
    """Order builtins, the managed install root, then development scan roots."""

    unique_roots = list(dict.fromkeys(Path(root) for root in search_paths))
    return sorted(
        unique_roots,
        key=lambda root: (
            0 if is_builtin_root(root) else 1 if package_files.is_user_plugins_root(root) else 2
        ),
    )


def _manifest_paths_for_root(root: Path) -> list[Path]:
    """Return safe manifest candidates for one discovery root."""

    if not package_files.is_user_plugins_root(root):
        return sorted(root.rglob("plugin.toml"), key=lambda path: path.as_posix())

    manifests: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda path: path.as_posix()):
        if child.is_symlink() or not child.is_dir():
            continue
        manifest_path = child / "plugin.toml"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            continue
        declared_id = _read_declared_plugin_id(manifest_path)
        if declared_id is None or not package_files.is_managed_plugin_manifest_path(
            declared_id,
            manifest_path,
        ):
            logger.warning(
                "Ignoring plugin manifest with an invalid managed path",
                extra={"manifest_path": str(manifest_path), "plugin_id": declared_id},
            )
            continue
        manifests.append(manifest_path)
    return manifests


def _read_declared_plugin_id(manifest_path: Path) -> str | None:
    """Read only the declared id so known duplicates need no further processing."""

    raw = _load_manifest_document(manifest_path)
    plugin_block = raw.get("plugin", raw)
    if not isinstance(plugin_block, Mapping):
        return None
    plugin_id = plugin_block.get("id")
    return plugin_id if isinstance(plugin_id, str) else None


def _log_duplicate_manifest(
    *,
    plugin_id: str,
    kept: PluginManifest,
    ignored_path: Path,
    ignored_source: str,
) -> None:
    logger.warning(
        "Plugin manifest id conflict; keeping the first discovered package",
        extra={
            "plugin_id": plugin_id,
            "kept_manifest_path": kept.manifest_path,
            "kept_source": kept.source,
            "ignored_manifest_path": str(ignored_path),
            "ignored_source": ignored_source,
        },
    )


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
        identity_error = package_identity_error(manifest, package_cfg)
        if identity_error is not None:
            enabled = False
            trusted = False
            current_settings = {}
        next_states[plugin_id] = PluginPackageState(
            manifest=manifest,
            enabled=enabled,
            trusted=trusted,
            loaded=(
                bool(previous_state.loaded)
                if previous_state is not None and identity_error is None
                else False
            ),
            healthy=(
                bool(previous_state.healthy)
                if previous_state is not None and identity_error is None
                else identity_error is None
            ),
            last_error=(
                previous_state.last_error
                if previous_state is not None and identity_error is None
                else identity_error
            ),
            contributions=(
                list(previous_state.contributions)
                if previous_state is not None
                else placeholder_contributions(manifest)
            ),
            current_settings=current_settings,
        )
    return next_states


def load_plugin_manifest(manifest_path: Path, *, source: str) -> PluginManifest:
    raw = _load_manifest_document(manifest_path)
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


def _load_manifest_document(manifest_path: Path) -> dict[str, Any]:
    try:
        with manifest_path.open("rb") as handle:
            payload = handle.read(MAX_PLUGIN_MANIFEST_BYTES + 1)
    except OSError as exc:
        raise ValueError(f"Cannot read plugin manifest: {manifest_path}") from exc
    if len(payload) > MAX_PLUGIN_MANIFEST_BYTES:
        raise ValueError(f"Plugin manifest exceeds the {MAX_PLUGIN_MANIFEST_BYTES}-byte limit")
    try:
        return tomllib.loads(payload.decode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("Plugin manifest must be UTF-8 text") from exc


def placeholder_contributions(manifest: PluginManifest) -> list[PluginContribution]:
    surface_map = {
        ContributionType.TOOL: "tools",
        ContributionType.SENSOR: "timeline",
        ContributionType.CHANNEL: "extensions",
        ContributionType.HISTORY_IMPORTER: "extensions",
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
