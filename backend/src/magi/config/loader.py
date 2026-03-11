"""
Configuration Loader - Runtime configuration management.

Configuration Sources (priority order):
    1. Environment variables (highest priority)
    2. Runtime config file: ~/.magi/config/agent.yaml
    3. Default values (lowest priority)

Directory Structure:
    ~/.magi/
    ├── config/
    │   └── agent.yaml      # Runtime configuration
    ├── data/
    │   ├── memories/       # Memory storage
    │   └── events.db       # Event database
    └── personalities/      # Personality files

First Run:
    If ~/.magi/config/agent.yaml doesn't exist,
    it will be copied from backend/configs/config.example.yaml
"""
import os
import re
import shutil
import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, Callable, Tuple

from .models import (
    AppConfig, AgentSettings, ServerSettings, FeatureFlags, ToolsSettings,
    LLMSettings, LLMProvider, MemorySettings, MessageBusSettings,
    PersonalitySettings, WeatherToolSettings, WebSearchToolSettings,
)
from .constants import DEFAULT_MAX_TOKENS

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


def get_example_config_file() -> Path:
    """Get example config file path (in package)"""
    # Path relative to this file: backend/configs/config.example.yaml
    return Path(__file__).parent.parent.parent.parent / "configs" / "config.example.yaml"


def get_data_dir() -> Path:
    """Get data directory"""
    return get_magi_home() / "data"


# =============================================================================
# Environment Variable Mappings
# =============================================================================

# Maps config path -> (env_var_name, type_converter, default_value)
ENV_MAPPINGS: Dict[str, Tuple[str, Callable, Any]] = {
    # LLM Settings
    "llm.provider": ("LLM_PROVIDER", lambda v: LLMProvider(v.lower()), LLMProvider.OPENAI),
    "llm.model": ("LLM_MODEL", str, "gpt-4o-mini"),
    "llm.api_key": ("LLM_API_KEY", str, None),
    "llm.base_url": ("LLM_BASE_URL", str, None),
    "llm.temperature": ("LLM_TEMPERATURE", float, 0.7),
    "llm.max_tokens": ("LLM_MAX_TOKENS", int, DEFAULT_MAX_TOKENS),
    "llm.timeout": ("LLM_TIMEOUT", int, 60),

    # Agent Settings
    "agent.name": ("AGENT_NAME", str, "magi-agent"),
    "agent.num_task_agents": ("NUM_TASK_AGENTS", int, 2),
    "agent.loop_interval": ("LOOP_INTERVAL", float, 1.0),
    "agent.enable_monitoring": ("ENABLE_MONITORING", lambda v: v.lower() == "true", True),

    # Feature Flags
    "features.enable_three_layer_arch": ("ENABLE_THREE_LAYER_ARCH", lambda v: v.lower() == "true", False),
    "features.enable_skills": ("ENABLE_SKILLS", lambda v: v.lower() == "true", True),
    "features.enable_websocket": ("ENABLE_WEBSOCKET", lambda v: v.lower() == "true", True),

    # Tools - Weather
    "tools.weather.default_provider": ("WEATHER_DEFAULT_PROVIDER", str, "qweather"),
    "tools.weather.providers.qweather.api_key": ("QWEATHER_API_KEY", str, None),
    "tools.weather.providers.qweather.base_url": ("QWEATHER_API_HOST", str, None),

    # Tools - Web Search
    "tools.web_search.default_provider": ("WEB_SEARCH_DEFAULT_PROVIDER", str, "duckduckgo"),
    "tools.web_search.providers.brave.api_key": ("BRAVE_API_KEY", str, None),
    "tools.web_search.providers.perplexity.api_key": ("PERPLEXITY_API_KEY", str, None),
    "tools.web_search.providers.tavily.api_key": ("TAVILY_API_KEY", str, None),

    # Server Settings
    "server.host": ("SERVER_HOST", str, "0.0.0.0"),
    "server.port": ("SERVER_PORT", int, 8000),
    "server.debug": ("SERVER_DEBUG", lambda v: v.lower() == "true", False),

    # Global
    "debug": ("DEBUG", lambda v: v.lower() == "true", False),
    "log_level": ("LOG_LEVEL", str, "INFO"),
}


# =============================================================================
# Config Loader
# =============================================================================

class ConfigLoader:
    """
    Runtime configuration loader.

    - Loads from ~/.magi/config/agent.yaml
    - Creates default config on first run
    - Supports environment variable overrides
    - Can save changes back to config file
    """

    def __init__(self):
        self._config: Optional[AppConfig] = None
        self._yaml_data: Dict[str, Any] = {}
        self._config_file: Path = get_config_file()

    def load(self) -> AppConfig:
        """
        Load configuration from runtime location.

        Returns:
            AppConfig: Merged configuration
        """
        if self._config is not None:
            return self._config

        # Ensure config directory exists and has default config
        self._ensure_config_exists()

        # Load YAML file
        self._yaml_data = self._load_yaml()

        # Build config with env var overrides
        self._config = self._build_config()

        logger.info(f"Configuration loaded from {self._config_file}")
        return self._config

    def _ensure_config_exists(self):
        """Create config directory and copy example config if needed."""
        config_dir = get_config_dir()
        config_file = get_config_file()
        example_file = get_example_config_file()

        # Create directory if needed
        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {config_dir}")

        # Copy example config if runtime config doesn't exist
        if not config_file.exists():
            if example_file.exists():
                shutil.copy(example_file, config_file)
                logger.info(f"Copied example config to {config_file}")
            else:
                # Create minimal config
                self._create_default_config_file(config_file)
                logger.info(f"Created default config at {config_file}")

        # Ensure data directories exist
        data_dir = get_data_dir()
        if not data_dir.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created data directory: {data_dir}")

    def _create_default_config_file(self, config_file: Path):
        """Create a minimal default config file."""
        default_config = {
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "",
                "temperature": 0.7,
                "max_tokens": DEFAULT_MAX_TOKENS,
                "timeout": 60,
                "capability_override_enabled": False,
                "capabilities": {
                    "vision": False,
                    "image_output": False,
                    "tool_calling": True,
                    "reasoning": True,
                    "embedding": False,
                },
                "limits": {
                    "context_window": None,
                    "max_output_tokens": None,
                },
                "provider_options": {},
            },
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
                "packages": {
                    "core-tools": {"enabled": True, "trusted": True, "source": "builtin", "settings": {}},
                    "core-timeline": {
                        "enabled": True,
                        "trusted": True,
                        "source": "builtin",
                        "settings": {
                            "sensors": {
                                "chat": {
                                    "enabled": True,
                                    "sync_mode": "watch",
                                    "sync_interval_minutes": 1,
                                    "default_retention_mode": "analyze_only",
                                    "storage_mode": "managed",
                                    "edge_whitelist": ["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "INTERACTED_WITH"],
                                },
                                "manual_journal": {
                                    "enabled": True,
                                    "sync_mode": "manual",
                                    "sync_interval_minutes": 1,
                                    "default_retention_mode": "retain_raw",
                                    "storage_mode": "managed",
                                    "edge_whitelist": ["MENTIONED", "CARES_ABOUT", "LIKES", "DISLIKES", "CREATED", "RELATED_TO"],
                                },
                                "browser_history": {
                                    "enabled": True,
                                    "sync_mode": "interval",
                                    "sync_interval_minutes": 30,
                                    "default_retention_mode": "analyze_only",
                                    "storage_mode": "managed",
                                    "source_path": "",
                                    "fetch_page_content": False,
                                    "edge_whitelist": ["VIEWED", "VISITED", "CARES_ABOUT", "LIKES"],
                                },
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
                    },
                    "core-actions": {
                        "enabled": True,
                        "trusted": True,
                        "source": "builtin",
                        "settings": {
                            "notifications": {"default_level": "info"},
                            "email": {"default_sender": "", "provider_mode": "simulated"},
                        },
                    },
                },
            },
            "debug": False,
            "log_level": "INFO",
        }

        with open(config_file, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True)

    def _load_yaml(self) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        if not self._config_file.exists():
            return {}

        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # Substitute ${VAR} and ${VAR:default} patterns
            data = self._substitute_env_vars(data)
            return data

        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            return {}

    def _substitute_env_vars(self, data: Any) -> Any:
        """Recursively substitute ${VAR} patterns."""
        if isinstance(data, str):
            if "${" not in data:
                return data

            pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

            def replace(match):
                var_name = match.group(1)
                default = match.group(2) if match.group(2) is not None else ""
                return os.getenv(var_name, default)

            return re.sub(pattern, replace, data)

        elif isinstance(data, dict):
            return {k: self._substitute_env_vars(v) for k, v in data.items()}

        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]

        return data

    def _build_config(self) -> AppConfig:
        """Build final config by merging YAML + env vars + defaults."""
        config_dict: Dict[str, Any] = {}

        # Apply YAML values
        self._apply_yaml_values(config_dict, self._yaml_data, "")

        # Apply environment variable overrides
        for config_path, (env_var, converter, default) in ENV_MAPPINGS.items():
            env_value = os.getenv(env_var)

            if env_value is not None:
                try:
                    value = converter(env_value)
                    self._set_nested(config_dict, config_path, value)
                except Exception as e:
                    logger.warning(f"Failed to convert {env_var}={env_value}: {e}")
            elif not self._has_nested(config_dict, config_path):
                self._set_nested(config_dict, config_path, default)

        return AppConfig(**config_dict)

    def _apply_yaml_values(self, result: Dict, yaml_data: Dict, prefix: str):
        """Flatten YAML data into result dict."""
        if not isinstance(yaml_data, dict):
            return

        for key, value in yaml_data.items():
            full_path = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                self._apply_yaml_values(result, value, full_path)
            else:
                self._set_nested(result, full_path, value)

    def _set_nested(self, data: Dict, path: str, value: Any):
        """Set nested value using dot-notation path."""
        parts = path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _has_nested(self, data: Dict, path: str) -> bool:
        """Check if nested path exists."""
        parts = path.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]

        return True

    def _get_nested(self, data: Dict, path: str) -> Any:
        """Get nested value using dot-notation path."""
        parts = path.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]

        return current

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

            # Reload current YAML data
            self._yaml_data = self._load_yaml()

            # Apply updates
            for path, value in updates.items():
                self._set_nested_yaml(self._yaml_data, path, value)

            # Write back to file
            with open(self._config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self._yaml_data, f, default_flow_style=False, allow_unicode=True)

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

    def reload(self) -> AppConfig:
        """Reload configuration from file."""
        self._config = None
        self._yaml_data = {}
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

    Loads from ~/.magi/config/agent.yaml with env var overrides.

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
