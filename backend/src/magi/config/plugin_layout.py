"""Split plugin config layout helpers for the runtime config loader.

Per-plugin default settings are declared in each plugin's ``plugin.toml``
under the ``[plugin.default_settings]`` table. When the host first creates
``~/.magi/config/plugins/{plugin_id}.yaml`` it reads that dict via
:meth:`_load_manifest_defaults_for_known_plugins` and writes it verbatim.

This is the single rail: adding a new plugin requires zero magi backend
changes — plugins are fully self-describing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


class ConfigPluginLayoutMixin:
    """Maintains split plugin package metadata and per-plugin settings files."""

    _config_file: Path
    _plugins_index_file: Path

    def _load_yaml_file(self, path: Path) -> Dict[str, Any]:
        raise NotImplementedError

    def _write_yaml_file(self, path: Path, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def _plugins_config_dir(self) -> Path:
        raise NotImplementedError

    def _plugin_settings_file(self, plugin_id: str) -> Path:
        raise NotImplementedError

    def _indexed_plugin_settings_file(self, plugin_id: str) -> Path | None:
        """Return a safe settings path for an index entry."""
        plugins_root = self._plugins_config_dir().resolve()
        settings_file = self._plugin_settings_file(plugin_id)
        if (
            settings_file.name == self._plugins_index_file.name
            or settings_file.parent.resolve() != plugins_root
            or settings_file.is_symlink()
        ):
            logger.error(
                "Unsafe indexed plugin settings path ignored | plugin_id=%s | path=%s",
                plugin_id,
                settings_file,
            )
            return None
        return settings_file

    def _default_plugin_index_data(self) -> Dict[str, Any]:
        """Return default plugin package metadata."""
        return {
            "packages": {
                "core-tools": {"enabled": True, "trusted": True, "source": "builtin"},
                "photo_library_core": {"enabled": True, "trusted": True, "source": "builtin"},
                "apple-photos": {"enabled": True, "trusted": True, "source": "builtin"},
                "local-photos": {"enabled": True, "trusted": True, "source": "builtin"},
                "chrome-history": {"enabled": True, "trusted": True, "source": "builtin"},
                "calendar": {"enabled": True, "trusted": True, "source": "builtin"},
                "git-activity": {"enabled": True, "trusted": True, "source": "builtin"},
                "screen-time": {"enabled": True, "trusted": True, "source": "builtin"},
                "system-media": {"enabled": True, "trusted": True, "source": "builtin"},
                "terminal-history": {"enabled": True, "trusted": True, "source": "builtin"},
            }
        }

    def _merge_plugin_index_defaults(self, index_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge missing builtin plugin metadata into the plugin index."""
        merged = self._default_plugin_index_data()
        merged_packages = merged.setdefault("packages", {})
        raw_packages = index_data.get("packages", {}) if isinstance(index_data, dict) else {}
        if isinstance(raw_packages, dict):
            for plugin_id, package_data in raw_packages.items():
                if isinstance(package_data, dict):
                    merged_packages.setdefault(plugin_id, {})
                    merged_packages[plugin_id].update(package_data)
        return merged

    def _load_manifest_defaults_for_known_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Read each known plugin's ``[plugin.default_settings]`` table.

        Iterates entries in ``~/.magi/config/plugins/index.yaml`` (which has
        already been written earlier in :meth:`_ensure_split_plugin_config_layout`)
        and, for every package that carries a ``manifest_path``, attempts to
        load that ``plugin.toml``. The ``[plugin.default_settings]`` sub-table
        is returned per plugin id.

        Any failure (missing manifest file, invalid TOML, no
        ``default_settings`` key) is silently treated as "no defaults
        provided" — the plugin gets no ``{plugin_id}.yaml`` written until it
        ships a manifest with defaults.
        """
        index_data = self._load_yaml_file(self._plugins_index_file)
        if not isinstance(index_data, dict):
            return {}
        packages = index_data.get("packages")
        if not isinstance(packages, dict):
            return {}

        defaults: Dict[str, Dict[str, Any]] = {}
        for plugin_id, package_data in packages.items():
            if not isinstance(package_data, dict):
                continue
            manifest_path = package_data.get("manifest_path")
            if not manifest_path:
                continue
            try:
                manifest_file = Path(manifest_path)
                if not manifest_file.is_file():
                    continue
                with manifest_file.open("rb") as handle:
                    manifest = tomllib.load(handle)
            except (OSError, ValueError, tomllib.TOMLDecodeError):
                continue
            plugin_table = manifest.get("plugin") if isinstance(manifest, dict) else None
            if not isinstance(plugin_table, dict):
                continue
            manifest_defaults = plugin_table.get("default_settings")
            if not isinstance(manifest_defaults, dict):
                continue
            defaults[plugin_id] = manifest_defaults
        return defaults

    def _migrate_chrome_history_plugin_defaults(self, index_data: Dict[str, Any]) -> bool:
        """Promote legacy chrome-history package state to the new builtin defaults.

        Defaults now live in chrome-history's ``plugin.toml`` manifest. This
        helper reads them from there via
        :meth:`_load_manifest_defaults_for_known_plugins`; if the manifest
        lookup turns up empty (e.g. manifest missing or malformed) we skip
        seeding rather than crash.
        """
        packages = index_data.setdefault("packages", {})
        package_data = packages.setdefault(
            "chrome-history",
            {"enabled": True, "trusted": True, "source": "builtin"},
        )
        changed = False
        settings_file = self._plugin_settings_file("chrome-history")
        settings_data = self._load_yaml_file(settings_file)

        if (
            package_data.get("source") == "builtin"
            and package_data.get("enabled") is False
            and package_data.get("trusted") is False
            and not settings_data
        ):
            package_data["enabled"] = True
            package_data["trusted"] = True
            changed = True

        if not settings_data:
            manifest_defaults = self._load_manifest_defaults_for_known_plugins()
            chrome_defaults = manifest_defaults.get("chrome-history")
            if chrome_defaults:
                self._write_yaml_file(settings_file, chrome_defaults)
                changed = True
            else:
                logger.warning(
                    "chrome-history manifest defaults unavailable; skipping "
                    "legacy seed migration. Plugin will pick up defaults on "
                    "next manifest load."
                )

        return changed

    def _ensure_split_plugin_config_layout(self) -> None:
        """Ensure plugin metadata and settings use split config files."""
        agent_data = self._load_yaml_file(self._config_file)
        agent_changed = False
        plugins_root = self._plugins_config_dir()
        plugins_root.mkdir(parents=True, exist_ok=True)
        index_data = self._merge_plugin_index_defaults(self._load_yaml_file(self._plugins_index_file))
        index_changed = self._migrate_chrome_history_plugin_defaults(index_data)
        legacy_packages = (
            agent_data.get("plugins", {}).get("packages", {})
            if isinstance(agent_data.get("plugins"), dict)
            else {}
        )

        if "llm" in agent_data:
            del agent_data["llm"]
            agent_changed = True

        if legacy_packages:
            packages_section = index_data.setdefault("packages", {})
            for plugin_id, package_data in legacy_packages.items():
                if not isinstance(package_data, dict):
                    continue
                package_meta = {
                    key: package_data[key]
                    for key in ("enabled", "trusted", "source", "manifest_path")
                    if key in package_data
                }
                packages_section.setdefault(plugin_id, {})
                packages_section[plugin_id].update(package_meta)
                self._write_yaml_file(
                    self._plugin_settings_file(plugin_id),
                    dict(package_data.get("settings", {})),
                )
            agent_data.setdefault("plugins", {})
            if isinstance(agent_data["plugins"], dict) and "packages" in agent_data["plugins"]:
                del agent_data["plugins"]["packages"]
                agent_changed = True
            self._write_yaml_file(self._plugins_index_file, index_data)

        if agent_changed:
            self._write_yaml_file(self._config_file, agent_data)

        if not self._plugins_index_file.exists():
            self._write_yaml_file(self._plugins_index_file, index_data)
        elif index_changed:
            self._write_yaml_file(self._plugins_index_file, index_data)

        # Plugins declare their seed defaults via [plugin.default_settings] in
        # their plugin.toml. See the module docstring for the rationale
        # (defaults belong with the plugin).
        seed_map = self._load_manifest_defaults_for_known_plugins()
        for plugin_id, defaults in seed_map.items():
            plugin_file = self._plugin_settings_file(plugin_id)
            if not plugin_file.exists():
                self._write_yaml_file(plugin_file, defaults)

    def _merge_split_plugin_config(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge indexed plugin config files into a single config tree.

        The package index is authoritative for package existence. A settings
        file without a matching package entry is ignored so a stale file from
        an interrupted uninstall cannot recreate a removed plugin.
        """
        merged = dict(agent_data)
        plugins_node = merged.setdefault("plugins", {})
        if not isinstance(plugins_node, dict):
            plugins_node = {}
            merged["plugins"] = plugins_node

        index_data = self._merge_plugin_index_defaults(self._load_yaml_file(self._plugins_index_file))
        packages = dict(index_data.get("packages", {})) if isinstance(index_data, dict) else {}
        for plugin_id, raw_package_entry in list(packages.items()):
            if not isinstance(raw_package_entry, dict):
                continue
            plugin_file = self._indexed_plugin_settings_file(plugin_id)
            if plugin_file is None or not plugin_file.is_file():
                continue
            package_entry = dict(packages.get(plugin_id, {}))
            package_entry["settings"] = self._load_yaml_file(plugin_file)
            packages[plugin_id] = package_entry
        if packages:
            plugins_node["packages"] = packages
        return merged


__all__ = ["ConfigPluginLayoutMixin"]
