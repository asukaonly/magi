"""
Configuration Loader - Runtime configuration management.

Configuration Sources (priority order):
    1. Runtime config files:
       - ~/.magi/config/agent.yaml
       - ~/.magi/config/llm.yaml
       - ~/.magi/config/plugins/index.yaml
       - ~/.magi/config/plugins/<plugin_id>.yaml
    2. Pydantic model defaults (lowest priority)

Directory Structure:
    ~/.magi/
    ├── config/
    │   ├── agent.yaml           # Host/runtime configuration (without llm block)
    │   ├── llm.yaml             # LLM override-only configuration
    │   └── plugins/
    │       ├── index.yaml       # Plugin package state
    │       └── <plugin>.yaml    # Per-plugin settings
    ├── data/
    │   ├── memories/            # Memory storage (L1/L2/L3/L4/L5)
    │   └── message_queue.db     # Message bus queue database
    └── personalities/           # Personality files

First Run:
    If ~/.magi/config/agent.yaml doesn't exist,
    it will be copied from backend/configs/config.example.yaml.
    Plugin package metadata and settings are then materialized into split files.
"""
import shutil
import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from .models import AppConfig
from .diff_utils import deep_merge_dict, extract_dict_overrides
from .llm_registry import (
    LLMProviderRegistryModel,
    build_runtime_llm_defaults,
    load_llm_provider_registry,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Paths
# =============================================================================

def get_magi_home() -> Path:
    """Get Magi home directory (~/.magi)"""
    return Path.home() / ".magi"


def get_config_dir() -> Path:
    """Get runtime config directory"""
    return get_magi_home() / "config"


def get_config_file() -> Path:
    """Get runtime config file path"""
    return get_config_dir() / "agent.yaml"


def get_plugins_config_dir() -> Path:
    """Get plugin config directory path."""
    return get_config_dir() / "plugins"


def get_plugins_index_file() -> Path:
    """Get plugin index config file path."""
    return get_plugins_config_dir() / "index.yaml"


def get_plugin_settings_file(plugin_id: str) -> Path:
    """Get per-plugin settings file path."""
    return get_plugins_config_dir() / f"{plugin_id}.yaml"


def get_llm_config_file() -> Path:
    """Get runtime llm override config file path."""
    return get_config_dir() / "llm.yaml"


def get_llm_provider_registry_file() -> Path:
    """Get packaged llm provider registry file path."""
    return Path(__file__).parent.parent.parent.parent / "configs" / "llm_providers.yaml"


def get_example_config_file() -> Path:
    """Get example config file path (in package)"""
    # Path relative to this file: backend/configs/config.example.yaml
    return Path(__file__).parent.parent.parent.parent / "configs" / "config.example.yaml"


def get_data_dir() -> Path:
    """Get data directory"""
    return get_magi_home() / "data"


# =============================================================================
# Config Loader
# =============================================================================

class ConfigLoader:
    """
    Runtime configuration loader.

    - Loads from ~/.magi/config/agent.yaml
    - Creates default config on first run
    - Can save changes back to config file
    """

    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._yaml_data: Dict[str, Any] = {}
        self._config_signature: Optional[Tuple[Tuple[str, int, int], ...]] = None
        self._config_file: Path = get_config_file()
        self._llm_config_file: Path = get_llm_config_file()
        self._llm_provider_registry_file: Path = get_llm_provider_registry_file()
        self._plugins_index_file: Path = get_plugins_index_file()

    def load(self) -> AppConfig:
        """
        Load configuration from runtime location.

        Returns:
            AppConfig: Merged configuration
        """
        # Ensure config directory exists and has default config
        self._ensure_config_exists()

        if self._config is not None:
            current_signature = self._snapshot_config_signature()
            if self._config_signature == current_signature:
                return self._config

        # Load YAML file
        self._yaml_data = self._load_yaml()

        # Build typed config from YAML
        self._config = self._build_config()
        self._config_signature = self._snapshot_config_signature()

        logger.info(f"Configuration loaded from {self._config_file}")
        return self._config

    def _snapshot_config_signature(self) -> Tuple[Tuple[str, int, int], ...]:
        """Capture a lightweight signature of split config files for cache invalidation."""
        tracked_paths = [
            self._config_file,
            self._llm_config_file,
            self._plugins_index_file,
            *sorted(get_plugins_config_dir().glob("*.yaml")),
        ]
        signature: list[tuple[str, int, int]] = []
        seen_paths: set[str] = set()

        for path in tracked_paths:
            key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            if path.exists():
                stat = path.stat()
                signature.append((key, stat.st_mtime_ns, stat.st_size))
            else:
                signature.append((key, -1, -1))

        return tuple(signature)

    def _ensure_config_exists(self):
        """Create config directory and copy example config if needed."""
        config_dir = get_config_dir()
        config_file = get_config_file()
        plugins_dir = get_plugins_config_dir()
        example_file = get_example_config_file()

        # Create directory if needed
        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {config_dir}")

        if not plugins_dir.exists():
            plugins_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created plugin config directory: {plugins_dir}")

        if not self._llm_provider_registry_file.exists():
            raise FileNotFoundError(f"Missing packaged LLM provider registry file: {self._llm_provider_registry_file}")

        # Copy example config if runtime config doesn't exist
        if not config_file.exists():
            if example_file.exists():
                shutil.copy(example_file, config_file)
                logger.info(f"Copied example config to {config_file}")
            else:
                # Create minimal config
                self._create_default_config_file(config_file)
                logger.info(f"Created default config at {config_file}")

        if not self._llm_config_file.exists():
            self._write_yaml_file(self._llm_config_file, {})
            logger.info(f"Created llm config file: {self._llm_config_file}")

        # Ensure data directories exist
        data_dir = get_data_dir()
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created data directory: {data_dir}")

        self._ensure_split_plugin_config_layout()

    def _create_default_config_file(self, config_file: Path):
        """Create a minimal default config file."""
        default_config = {
            "agent": {
                "name": "magi-agent",
                "num_task_agents": 2,
            },
            "features": {
                "enable_three_layer_arch": False,
                "enable_skills": True,
            },
            "tools": {
                "weather": {"enabled": True, "api_key": ""},
                "web_search": {"enabled": True, "api_key": ""},
            },
            "plugins": {
                "scan_paths": ["plugins", "~/.magi/plugins"],
            },
            "debug": False,
            "log_level": "INFO",
        }

        self._write_yaml_file(config_file, default_config)

    def _default_plugin_index_data(self) -> Dict[str, Any]:
        """Return default plugin package metadata."""
        return {
            "packages": {
                "core-tools": {"enabled": True, "trusted": True, "source": "builtin"},
                "photo-library": {"enabled": True, "trusted": True, "source": "builtin"},
                "core-actions": {"enabled": True, "trusted": True, "source": "builtin"},
                "chrome-history": {"enabled": True, "trusted": True, "source": "builtin"},
                "calendar": {"enabled": True, "trusted": True, "source": "builtin"},
                "git-activity": {"enabled": True, "trusted": True, "source": "builtin"},
                "screen-time": {"enabled": True, "trusted": True, "source": "builtin"},
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

    def _default_plugin_settings_map(self) -> Dict[str, Dict[str, Any]]:
        """Return default per-plugin settings."""
        return {
            "core-tools": {},
            "photo-library": {
                "sensors": {
                    "photo_library": {
                        "enabled": True,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 60,
                        "default_retention_mode": "retain_raw",
                        "storage_mode": "external_reference",
                        "source_path": "",
                        "edge_whitelist": ["CAPTURED", "RELATED_TO", "INTERACTED_WITH", "CREATED"],
                    },
                }
            },
            "core-actions": {
                "email": {"default_sender": "", "provider_mode": "simulated"},
            },
            "chrome-history": {
                "sensors": {
                    "chrome_history": {
                        "enabled": False,
                        "sync_mode": "manual",
                        "sync_interval_minutes": 30,
                        "default_retention_mode": "analyze_only",
                        "storage_mode": "managed",
                        "profile": "Default",
                        "lookback_hours": 24,
                        "max_items_per_sync": 200,
                        "fetch_page_content": False,
                        "edge_whitelist": ["VISITED", "VIEWED"],
                    }
                }
            },
            "calendar": {
                "sensors": {
                    "calendar": {
                        "enabled": False,
                        "sync_mode": "interval",
                        "sync_interval_minutes": 30,
                        "lookback_days": 30,
                        "recurring_expansion_days": 30,
                        "default_retention_mode": "full",
                    }
                }
            },
            "git-activity": {
                "sensors": {
                    "git_activity": {
                        "enabled": False,
                        "repos": [],
                        "sync_interval_minutes": 30,
                        "initial_sync_policy": "lookback_days",
                        "initial_sync_lookback_days": 30,
                        "sensitive_mode": "redact",
                        "sensitive_keywords": [],
                        "default_retention_mode": "analyze_only",
                    }
                }
            },
            "screen-time": {
                "sensors": {
                    "screen_time": {
                        "enabled": False,
                        "sync_interval_minutes": 5,
                    }
                }
            },
            "terminal-history": {
                "sensors": {
                    "terminal_history": {
                        "enabled": False,
                        "sync_interval_minutes": 15,
                        "initial_sync_policy": "lookback_days",
                        "initial_sync_lookback_days": 7,
                        "initial_sync_configured": False,
                        "sensitive_mode": "redact",
                        "sensitive_keywords": [],
                        "dedup_window_seconds": 60,
                        "default_retention_mode": "analyze_only",
                    }
                }
            },
        }

    def _migrate_chrome_history_plugin_defaults(self, index_data: Dict[str, Any]) -> bool:
        """Promote legacy chrome-history package state to the new builtin defaults."""

        packages = index_data.setdefault("packages", {})
        package_data = packages.setdefault(
            "chrome-history",
            {"enabled": True, "trusted": True, "source": "builtin"},
        )
        changed = False
        settings_file = get_plugin_settings_file("chrome-history")
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
            self._write_yaml_file(
                settings_file,
                self._default_plugin_settings_map()["chrome-history"],
            )
            changed = True

        return changed

    def _ensure_split_plugin_config_layout(self) -> None:
        """Ensure plugin metadata and settings use split config files."""
        agent_data = self._load_yaml_file(self._config_file)
        agent_changed = False
        plugins_root = get_plugins_config_dir()
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
                    get_plugin_settings_file(plugin_id),
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

        for plugin_id, defaults in self._default_plugin_settings_map().items():
            plugin_file = get_plugin_settings_file(plugin_id)
            if not plugin_file.exists():
                self._write_yaml_file(plugin_file, defaults)

    def _merge_split_plugin_config(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Merge split plugin config files into a single config tree."""
        merged = dict(agent_data)
        plugins_node = merged.setdefault("plugins", {})
        if not isinstance(plugins_node, dict):
            plugins_node = {}
            merged["plugins"] = plugins_node

        index_data = self._merge_plugin_index_defaults(self._load_yaml_file(self._plugins_index_file))
        packages = dict(index_data.get("packages", {})) if isinstance(index_data, dict) else {}
        for plugin_file in sorted(get_plugins_config_dir().glob("*.yaml")):
            if plugin_file.name == "index.yaml":
                continue
            plugin_id = plugin_file.stem
            package_entry = dict(packages.get(plugin_id, {}))
            package_entry["settings"] = self._load_yaml_file(plugin_file)
            packages[plugin_id] = package_entry
        if packages:
            plugins_node["packages"] = packages
        return merged

    def _load_yaml_file(self, path: Path) -> Dict[str, Any]:
        """Load and parse a YAML file, returning an empty dict on failure."""
        if not path.exists():
            return {}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load config file {path}: {e}")
            return {}

    def _write_yaml_file(self, path: Path, data: Dict[str, Any]) -> None:
        """Write a YAML file with a normalized dict payload."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    def _load_yaml(self) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        data = self._load_yaml_file(self._config_file)
        data = self._merge_split_plugin_config(data)
        data["llm"] = self._load_effective_llm_config()
        return data

    def _load_effective_llm_config(self) -> Dict[str, Any]:
        """Load effective LLM config by merging registry defaults and runtime overrides."""
        defaults = self._build_llm_defaults()
        overrides = self._load_yaml_file(self._llm_config_file)
        return deep_merge_dict(defaults, overrides)

    def _load_llm_provider_registry(self) -> LLMProviderRegistryModel:
        """Load packaged provider registry for LLM default generation."""
        return load_llm_provider_registry(
            self._llm_provider_registry_file,
            fallback=LLMProviderRegistryModel(),
        )

    def _build_llm_defaults(self) -> Dict[str, Any]:
        """Build default LLM config from provider registry."""
        return build_runtime_llm_defaults(self._load_llm_provider_registry())

    def _build_config(self) -> AppConfig:
        """Build final config by merging YAML + model defaults."""
        return AppConfig.model_validate(self._yaml_data)

    def save(self, updates: Dict[str, Any]) -> bool:
        """
        Save configuration updates to the runtime config file.

        Args:
            updates: Dict of path -> value to update

        Returns:
            True if saved successfully
        """
        try:
            update_keys = sorted(updates.keys())
            logger.info("Configuration save requested | update_paths=%s", update_keys)

            agent_yaml = self._load_yaml_file(self._config_file)
            if "llm" in agent_yaml:
                del agent_yaml["llm"]
            agent_yaml.setdefault("plugins", {})
            if isinstance(agent_yaml.get("plugins"), dict) and "packages" in agent_yaml["plugins"]:
                del agent_yaml["plugins"]["packages"]
            self._prune_deprecated_memory_settings(agent_yaml)
            plugins_index = self._merge_plugin_index_defaults(self._load_yaml_file(self._plugins_index_file))
            llm_defaults = self._build_llm_defaults()
            llm_overrides = self._load_yaml_file(self._llm_config_file)
            llm_effective = deep_merge_dict(llm_defaults, llm_overrides)
            plugin_settings_updates: Dict[str, Dict[str, Any]] = {}

            for path, value in updates.items():
                if path.startswith("llm."):
                    self._set_nested_yaml(llm_effective, path[4:], value)
                    continue
                if path.startswith("plugins.packages."):
                    parts = path.split(".")
                    if len(parts) < 4:
                        self._set_nested_yaml(agent_yaml, path, value)
                        continue
                    plugin_id = parts[2]
                    if parts[3] == "settings":
                        relative_path = ".".join(parts[4:])
                        plugin_settings_updates.setdefault(plugin_id, {})
                        plugin_settings_updates[plugin_id][relative_path] = value
                    else:
                        relative_path = ".".join(parts[2:])
                        self._set_nested_yaml(plugins_index, f"packages.{relative_path}", value)
                    continue
                self._set_nested_yaml(agent_yaml, path, value)

            next_llm_overrides = extract_dict_overrides(llm_defaults, llm_effective)

            self._write_yaml_file(self._config_file, agent_yaml)
            self._write_yaml_file(self._llm_config_file, next_llm_overrides)
            self._write_yaml_file(self._plugins_index_file, plugins_index)

            for plugin_id, plugin_updates in plugin_settings_updates.items():
                plugin_yaml = self._load_yaml_file(get_plugin_settings_file(plugin_id))
                for relative_path, value in plugin_updates.items():
                    if relative_path:
                        self._set_nested_yaml(plugin_yaml, relative_path, value)
                    elif isinstance(value, dict):
                        plugin_yaml = dict(value)
                    else:
                        raise ValueError(f"Plugin settings root must be a dict for {plugin_id}")
                self._write_yaml_file(get_plugin_settings_file(plugin_id), plugin_yaml)

            # Reload config
            self._config = None
            self.load()

            logger.info(
                "Configuration saved | config_file=%s | update_paths=%s",
                str(self._config_file),
                update_keys,
            )
            return True

        except Exception as e:
            logger.error(
                "Failed to save config | update_paths=%s | error=%s",
                sorted(updates.keys()),
                str(e),
            )
            return False

    def _set_nested_yaml(self, data: Dict, path: str, value: Any):
        """Set nested value in YAML data structure."""
        parts = path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _prune_deprecated_memory_settings(self, data: Dict[str, Any]) -> None:
        """Remove no-longer-supported memory vector config overrides from runtime YAML."""
        agent = data.get("agent")
        if not isinstance(agent, dict):
            return
        memory = agent.get("memory")
        if not isinstance(memory, dict):
            return

        memory.pop("async_embeddings", None)
        embedding = memory.get("embedding")
        if isinstance(embedding, dict):
            embedding.pop("backend", None)
            if not embedding:
                memory.pop("embedding", None)

    def reload(self) -> AppConfig:
        """Reload configuration from file."""
        self._config = None
        self._yaml_data = {}
        self._config_signature = None
        return self.load()

    def get_config_path(self) -> Path:
        """Get the runtime config file path."""
        return self._config_file


# =============================================================================
# Global Instance & Public API
# =============================================================================

_loader: Optional[ConfigLoader] = None


def get_config() -> AppConfig:
    """
    Get application configuration.

    Loads from runtime config files under ~/.magi/config/.

    Returns:
        AppConfig: Application configuration
    """
    global _loader

    if _loader is None:
        _loader = ConfigLoader()

    return _loader.load()


def reload_config() -> AppConfig:
    """Reload configuration from file."""
    global _loader

    if _loader is not None:
        return _loader.reload()

    return get_config()


def save_config(updates: Dict[str, Any]) -> bool:
    """
    Save configuration updates to runtime config file.

    Args:
        updates: Dict of path -> value (e.g., {"tools.weather.api_key": "xxx"})

    Returns:
        True if saved successfully
    """
    global _loader

    if _loader is None:
        _loader = ConfigLoader()
        _loader.load()

    return _loader.save(updates)


def get_loader() -> Optional[ConfigLoader]:
    """Get the global config loader instance."""
    return _loader


def get_config_file_path() -> Path:
    """Get the runtime config file path."""
    return get_config_file()
