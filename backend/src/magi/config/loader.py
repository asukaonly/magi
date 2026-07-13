"""
Configuration Loader - Runtime configuration management.

Configuration Sources (priority order):
    1. Runtime config files:
       - ~/.magi/config/agent.yaml
       - ~/.magi/config/llm.yaml
    - ~/.magi/config/lifecycle.yaml
       - ~/.magi/config/plugins/index.yaml
       - ~/.magi/config/plugins/<plugin_id>.yaml
    2. Pydantic model defaults (lowest priority)

Directory Structure:
    ~/.magi/
    ├── config/
    │   ├── agent.yaml           # Host/runtime configuration (without llm block)
    │   ├── llm.yaml             # LLM override-only configuration
    │   ├── lifecycle.yaml       # Data lifecycle and cleanup policy
    │   └── plugins/
    │       ├── index.yaml       # Plugin package state
    │       └── <plugin>.yaml    # Per-plugin settings
    ├── data/
    │   ├── app/                 # Durable app-owned stores
    │   ├── chat/                # Chat-domain source of truth
    │   ├── memory/              # Memory-layer databases
    │   └── resources/           # Durable managed assets
    ├── runtime/                 # Runtime coordination and observability stores
    ├── cache/                   # Rebuildable plugin/runtime cache state
    └── personalities/           # Personality files

First Run:
    If ~/.magi/config/agent.yaml doesn't exist,
    it will be copied from backend/configs/config.example.yaml.
    Plugin package metadata and settings are then materialized into split files.
"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from .models import AppConfig
from .loader_file_ops import ConfigLoaderFileOpsMixin
from .loader_persistence import ConfigLoaderPersistenceMixin
from .plugin_layout import ConfigPluginLayoutMixin
from ..utils.packaged_paths import get_backend_root

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


def get_lifecycle_config_file() -> Path:
    """Get runtime lifecycle policy config file path."""
    return get_config_dir() / "lifecycle.yaml"


def get_lifecycle_example_config_file() -> Path:
    """Get packaged lifecycle policy defaults file path."""
    return get_backend_root() / "configs" / "lifecycle.example.yaml"


def get_llm_provider_registry_file() -> Path:
    """Get packaged llm provider registry file path."""
    return get_backend_root() / "configs" / "llm_providers.yaml"


def get_example_config_file() -> Path:
    """Get example config file path (in package)"""
    return get_backend_root() / "configs" / "config.example.yaml"


def get_data_dir() -> Path:
    """Get data directory"""
    return get_magi_home() / "data"


# =============================================================================
# Config Loader
# =============================================================================

class ConfigLoader(ConfigLoaderPersistenceMixin, ConfigLoaderFileOpsMixin, ConfigPluginLayoutMixin):
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
        self._lifecycle_config_file: Path = get_lifecycle_config_file()
        self._lifecycle_example_config_file: Path = get_lifecycle_example_config_file()
        self._llm_provider_registry_file: Path = get_llm_provider_registry_file()
        self._plugins_index_file: Path = get_plugins_index_file()

    def load(self) -> AppConfig:
        """
        Load configuration from runtime location.

        Returns:
            AppConfig: Merged configuration
        """
        if self._config is not None:
            current_signature = self._snapshot_config_signature()
            if self._config_signature == current_signature:
                return self._config

        # Ensure config directory exists and has default config when bootstrapping
        # or after external file changes invalidate the cached signature.
        self._ensure_config_exists()

        # Load YAML file
        self._yaml_data = self._load_yaml()

        # Build typed config from YAML
        self._config = self._build_config()
        self._config_signature = self._snapshot_config_signature()

        logger.info(f"Configuration loaded from {self._config_file}")
        return self._config

    def reload(self) -> AppConfig:
        """Reload configuration from file."""
        self._config = None
        self._yaml_data = {}
        self._config_signature = None
        return self.load()

    def get_config_path(self) -> Path:
        """Get the runtime config file path."""
        return self._config_file

    def get_raw_value(self, *keys: str, default: Any = None) -> Any:
        """Read a value from the cached raw YAML data by dotted key path."""
        self.load()  # ensure data is loaded and fresh
        node: Any = self._yaml_data
        for key in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(key)
            if node is None:
                return default
        return node


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


def get_user_preference(key: str, default: Any = None) -> Any:
    """Read a single user preference from the runtime config."""
    global _loader

    if _loader is None:
        _loader = ConfigLoader()
    return _loader.get_raw_value("preferences", key, default=default)


def get_config_file_path() -> Path:
    """Get the runtime config file path."""
    return get_config_file()
