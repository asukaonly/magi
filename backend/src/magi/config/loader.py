"""
Configuration Loader - Centralized configuration management.

This module is the single source of truth for all configuration.
Other modules should NOT read environment variables directly.

Configuration Sources (priority order):
1. Environment variables (highest priority)
2. YAML configuration file
3. Default values (lowest priority)

Usage:
    from magi.config import get_config

    config = get_config()
    api_key = config.agent.llm.api_key
    model = config.agent.llm.model
"""
import os
import re
import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any, Type, Callable, Tuple

from .models import (
    AppConfig, AgentSettings, ServerSettings, FeatureFlags, ToolsSettings,
    LLMSettings, LLMProvider, MemorySettings, MessageBusSettings,
    PersonalitySettings,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Environment Variable Mappings
# =============================================================================
# Maps config path -> (env_var_name, type_converter, default_value)

ENV_MAPPINGS: Dict[str, Tuple[str, Callable, Any]] = {
    # LLM Settings
    "agent.llm.provider": ("LLM_PROVIDER", lambda v: LLMProvider(v.lower()), LLMProvider.OPENAI),
    "agent.llm.model": ("LLM_MODEL", str, "gpt-4o-mini"),
    "agent.llm.api_key": ("LLM_API_KEY", str, None),
    "agent.llm.base_url": ("LLM_BASE_URL", str, None),
    "agent.llm.temperature": ("LLM_TEMPERATURE", float, 0.7),
    "agent.llm.max_tokens": ("LLM_MAX_TOKENS", int, 1000),
    "agent.llm.timeout": ("LLM_TIMEOUT", int, 60),

    # Agent Settings
    "agent.name": ("AGENT_NAME", str, "magi-agent"),
    "agent.num_task_agents": ("NUM_TASK_AGENTS", int, 2),
    "agent.loop_interval": ("LOOP_INTERVAL", float, 1.0),
    "agent.enable_monitoring": ("ENABLE_MONITORING", lambda v: v.lower() == "true", True),

    # Personality Settings
    "agent.personality.name": ("PERSONALITY_NAME", str, "default"),
    "agent.personality.enable_evolution": ("ENABLE_EVOLUTION", lambda v: v.lower() == "true", True),

    # Server Settings
    "server.host": ("SERVER_HOST", str, "0.0.0.0"),
    "server.port": ("SERVER_PORT", int, 8000),
    "server.debug": ("SERVER_DEBUG", lambda v: v.lower() == "true", False),

    # Feature Flags
    "features.enable_three_layer_arch": ("ENABLE_THREE_LAYER_ARCH", lambda v: v.lower() == "true", False),
    "features.enable_skills": ("ENABLE_SKILLS", lambda v: v.lower() == "true", True),
    "features.enable_websocket": ("ENABLE_WEBSOCKET", lambda v: v.lower() == "true", True),

    # Tools - Weather
    "tools.weather.enabled": ("WEATHER_TOOL_ENABLED", lambda v: v.lower() == "true", True),
    "tools.weather.api_key": ("WEATHER_API_KEY", str, None),
    "tools.weather.base_url": ("WEATHER_BASE_URL", str, None),
    "tools.weather.default_location": ("WEATHER_DEFAULT_LOCATION", str, "Beijing"),

    # Tools - Web Search
    "tools.web_search.enabled": ("WEB_SEARCH_ENABLED", lambda v: v.lower() == "true", True),
    "tools.web_search.api_key": ("SEARCH_API_KEY", str, None),
    "tools.web_search.engine": ("SEARCH_ENGINE", str, "google"),
    "tools.web_search.max_results": ("SEARCH_MAX_RESULTS", int, 5),

    # Global Settings
    "debug": ("DEBUG", lambda v: v.lower() == "true", False),
    "log_level": ("LOG_LEVEL", str, "INFO"),
}

# Default YAML config file search paths
DEFAULT_CONFIG_PATHS = [
    "./configs/agent.yaml",
    "../configs/agent.yaml",
    "./agent.yaml",
    "/etc/magi/agent.yaml",
]


class ConfigLoader:
    """
    Centralized configuration loader.

    Handles all configuration sources and provides a unified interface.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration loader.

        Args:
            config_path: Optional path to YAML config file.
                         If None, searches default paths.
        """
        self.config_path = config_path or self._find_config_file()
        self._config: Optional[AppConfig] = None
        self._yaml_data: Dict[str, Any] = {}

    def _find_config_file(self) -> Optional[str]:
        """Search for configuration file in default locations."""
        for path in DEFAULT_CONFIG_PATHS:
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                logger.info(f"Found config file: {abs_path}")
                return abs_path
        return None

    def load(self) -> AppConfig:
        """
        Load configuration from all sources.

        Priority: Environment variables > YAML file > Defaults

        Returns:
            AppConfig: Merged configuration object
        """
        if self._config is not None:
            return self._config

        # 1. Load YAML file (if exists)
        self._yaml_data = self._load_yaml()

        # 2. Build config with priority: env > yaml > default
        self._config = self._build_config()

        logger.info("Configuration loaded")
        return self._config

    def _load_yaml(self) -> Dict[str, Any]:
        """Load and parse YAML configuration file."""
        if not self.config_path or not os.path.exists(self.config_path):
            return {}

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # Substitute ${VAR} and ${VAR:default} patterns
            data = self._substitute_env_vars(data)
            return data

        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            return {}

    def _substitute_env_vars(self, data: Any) -> Any:
        """Recursively substitute ${VAR} patterns in YAML data."""
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
        """
        Build final configuration by merging all sources.

        Priority: env var > yaml value > default
        """
        # Start with defaults from ENV_MAPPINGS
        config_dict: Dict[str, Any] = {}

        # Apply YAML values first
        self._apply_yaml_values(config_dict, self._yaml_data, "")

        # Then apply environment variable overrides
        for config_path, (env_var, converter, default) in ENV_MAPPINGS.items():
            env_value = os.getenv(env_var)

            if env_value is not None:
                # Environment variable takes precedence
                try:
                    value = converter(env_value)
                    self._set_nested(config_dict, config_path, value)
                except Exception as e:
                    logger.warning(f"Failed to convert {env_var}={env_value}: {e}")
            elif not self._has_nested(config_dict, config_path):
                # Use default if no value set
                self._set_nested(config_dict, config_path, default)

        # Build Pydantic model
        return AppConfig(**config_dict)

    def _apply_yaml_values(self, result: Dict, yaml_data: Dict, prefix: str):
        """Flatten YAML data into result dict with dot-notation keys."""
        if not isinstance(yaml_data, dict):
            return

        for key, value in yaml_data.items():
            full_path = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                self._apply_yaml_values(result, value, full_path)
            else:
                self._set_nested(result, full_path, value)

    def _set_nested(self, data: Dict, path: str, value: Any):
        """Set a nested value using dot-notation path."""
        parts = path.split(".")
        current = data

        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        current[parts[-1]] = value

    def _has_nested(self, data: Dict, path: str) -> bool:
        """Check if a nested path exists."""
        parts = path.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]

        return True

    def _get_nested(self, data: Dict, path: str) -> Any:
        """Get a nested value using dot-notation path."""
        parts = path.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]

        return current

    def reload(self) -> AppConfig:
        """Reload configuration from all sources."""
        self._config = None
        self._yaml_data = {}
        return self.load()

    def get_raw_env(self, env_var: str) -> Optional[str]:
        """Get raw environment variable value (for debugging)."""
        return os.getenv(env_var)

    def list_env_vars(self) -> Dict[str, Optional[str]]:
        """List all recognized environment variables and their values."""
        result = {}
        for config_path, (env_var, _, _) in ENV_MAPPINGS.items():
            result[env_var] = os.getenv(env_var)
        return result


# =============================================================================
# Global Instance & Public API
# =============================================================================

_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[str] = None) -> AppConfig:
    """
    Get application configuration.

    This is the main entry point for all configuration access.
    Other modules should use this function instead of reading env vars directly.

    Args:
        config_path: Optional config file path (only used on first call)

    Returns:
        AppConfig: Application configuration
    """
    global _loader

    if _loader is None:
        _loader = ConfigLoader(config_path)

    return _loader.load()


def reload_config() -> AppConfig:
    """Reload configuration from all sources."""
    global _loader

    if _loader is not None:
        return _loader.reload()

    return get_config()


def get_loader() -> Optional[ConfigLoader]:
    """Get the global config loader instance."""
    return _loader
