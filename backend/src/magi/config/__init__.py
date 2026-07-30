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
    1. Runtime config files under ~/.magi/config/
    2. Model defaults (lowest priority)

Usage:
    from magi.config import get_config, save_config

    # Read configuration
    config = get_config()
    api_key = config.tools.weather.api_key

    # Save configuration (persists to split runtime config files)
    save_config({"tools.weather.api_key": "your-key"})

"""
from .loader import (
    ConfigLoader,
    get_config,
    reload_config,
    save_config,
    delete_plugin_package,
    get_loader,
    get_user_preference,
    get_config_file_path,
    get_magi_home,
    get_config_dir,
    get_plugins_config_dir,
    get_plugins_index_file,
    get_plugin_settings_file,
    get_lifecycle_config_file,
    get_data_dir,
)

from .models import (
    # Main configuration
    AppConfig,
    AgentSettings,
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

    # Tool settings
    WeatherToolSettings,
    WebSearchToolSettings,

    # Other settings
    PersonalitySettings,
    PluginSettings,
    PluginsSettings,
    LLMCacheObservabilitySettings,
    LifecycleSettings,
)
from .llm_registry import (
    LLMAudioGenerationModelMetaModel,
    LLMChatCapabilitiesModel,
    LLMEmbeddingModelMetaModel,
    LLMImageGenerationModelMetaModel,
    LLMModelMetaModel,
    LLMProviderFieldModel,
    LLMProviderMetaModel,
    LLMProviderPlanEndpointModel,
    LLMCustomProviderMetaModel,
    LLMProviderRegistryModel,
    LLMResolvedImageGenerationModelMetaModel,
    ResolvedLLMProfile,
    find_chat_model_meta,
    find_embedding_model_meta,
    find_provider_meta,
    load_llm_provider_registry,
    resolve_embedding_dimension,
    resolve_llm_profile,
)
from .introspection import ConfigPathSpec, list_app_config_specs

__all__ = [
    # Main API
    "get_config",
    "reload_config",
    "save_config",
    "delete_plugin_package",
    "get_loader",
    "get_user_preference",
    "get_config_file_path",
    "get_magi_home",
    "get_config_dir",
    "get_plugins_config_dir",
    "get_plugins_index_file",
    "get_plugin_settings_file",
    "get_lifecycle_config_file",
    "get_data_dir",

    # Loader class
    "ConfigLoader",

    # Introspection
    "ConfigPathSpec",
    "list_app_config_specs",

    # Configuration models
    "AppConfig",
    "AgentSettings",
    "FeatureFlags",
    "ToolsSettings",
    "LLMSettings",
    "LLMProvider",
    "LLMCapabilitiesSettings",
    "LLMLimitsSettings",
    "LLMChatCapabilitiesModel",
    "LLMEmbeddingModelMetaModel",
    "LLMImageGenerationModelMetaModel",
    "LLMAudioGenerationModelMetaModel",
    "LLMModelMetaModel",
    "LLMProviderFieldModel",
    "LLMProviderMetaModel",
    "LLMProviderPlanEndpointModel",
    "LLMCustomProviderMetaModel",
    "LLMProviderRegistryModel",
    "LLMResolvedImageGenerationModelMetaModel",
    "ResolvedLLMProfile",
    "find_chat_model_meta",
    "find_embedding_model_meta",
    "find_provider_meta",
    "load_llm_provider_registry",
    "resolve_embedding_dimension",
    "resolve_llm_profile",
    "MemorySettings",
    "MemoryBackend",
    "EmbeddingSettings",
    "EmbeddingBackend",
    "MessageBusSettings",
    "WeatherToolSettings",
    "WebSearchToolSettings",
    "PersonalitySettings",
    "PluginSettings",
    "PluginsSettings",
    "LLMCacheObservabilitySettings",
    "LifecycleSettings",
]
