"""
Configuration Module - Runtime configuration management.

Configuration Location:
    ~/.magi/config/agent.yaml
    ~/.magi/config/plugins/index.yaml
    ~/.magi/config/plugins/<plugin_id>.yaml

First Run:
    If config file doesn't exist, it's copied from backend/configs/config.example.yaml
    and plugin configuration is materialized into split files.

Configuration Sources (priority order):
    1. Environment variables (highest priority)
    2. Runtime config files under ~/.magi/config/
    3. Default values (lowest priority)

Usage:
    from magi.config import get_config, save_config

    # Read configuration
    config = get_config()
    api_key = config.tools.weather.api_key

    # Save configuration (persists to split runtime config files)
    save_config({"tools.weather.api_key": "your-key"})

Environment Variables:
    LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_BASE_URL
    QWEATHER_API_KEY, SEARCH_API_KEY
    DEBUG, LOG_LEVEL
"""
from .loader import (
    ConfigLoader,
    get_config,
    reload_config,
    save_config,
    get_loader,
    get_config_file_path,
    get_magi_home,
    get_config_dir,
    get_plugins_config_dir,
    get_plugins_index_file,
    get_plugin_settings_file,
    get_data_dir,
    ENV_MAPPINGS,
)

from .models import (
    # Main configuration
    AppConfig,
    AgentSettings,
    ServerSettings,
    FeatureFlags,
    ToolsSettings,

    # LLM configuration
    LLMSettings,
    LLMProvider,
    LLMCapabilitiesSettings,
    LLMLimitsSettings,

    # Memory configuration
    MemorySettings,
    MemoryBackend,
    EmbeddingSettings,
    EmbeddingBackend,

    # Message bus configuration
    MessageBusSettings,
    MessageBusBackend,

    # Tool settings
    WeatherToolSettings,
    WebSearchToolSettings,

    # Other settings
    PersonalitySettings,
    PluginSettings,
    PluginsSettings,

    # Backward compatibility
    Config,
)
from .llm_registry import (
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMCustomProviderMetaModel,
    LLMProviderRegistryModel,
    ResolvedLLMProfile,
    find_model_meta,
    find_provider_meta,
    load_llm_provider_registry,
    resolve_llm_profile,
)
from .introspection import ConfigPathSpec, list_app_config_specs

__all__ = [
    # Main API
    "get_config",
    "reload_config",
    "save_config",
    "get_loader",
    "get_config_file_path",
    "get_magi_home",
    "get_config_dir",
    "get_plugins_config_dir",
    "get_plugins_index_file",
    "get_plugin_settings_file",
    "get_data_dir",

    # Loader class
    "ConfigLoader",

    # Mappings
    "ENV_MAPPINGS",
    "ConfigPathSpec",
    "list_app_config_specs",

    # Configuration models
    "AppConfig",
    "AgentSettings",
    "ServerSettings",
    "FeatureFlags",
    "ToolsSettings",
    "LLMSettings",
    "LLMProvider",
    "LLMCapabilitiesSettings",
    "LLMLimitsSettings",
    "LLMModelMetaModel",
    "LLMProviderFieldModel",
    "LLMProviderMetaModel",
    "LLMCustomProviderMetaModel",
    "LLMProviderRegistryModel",
    "ResolvedLLMProfile",
    "find_model_meta",
    "find_provider_meta",
    "load_llm_provider_registry",
    "resolve_llm_profile",
    "MemorySettings",
    "MemoryBackend",
    "EmbeddingSettings",
    "EmbeddingBackend",
    "MessageBusSettings",
    "MessageBusBackend",
    "WeatherToolSettings",
    "WebSearchToolSettings",
    "PersonalitySettings",
    "PluginSettings",
    "PluginsSettings",

    # Backward compatibility
    "Config",
]
