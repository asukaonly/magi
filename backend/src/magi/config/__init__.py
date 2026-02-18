"""
Configuration Module - Single source of truth for all configuration.

This module centralizes all configuration access. Other modules should
NOT read environment variables directly - use get_config() instead.

Configuration Sources (priority order):
    1. Environment variables (highest priority)
    2. YAML configuration file
    3. Default values (lowest priority)

Usage:
    from magi.config import get_config

    config = get_config()

    # Access configuration values
    api_key = config.agent.llm.api_key
    model = config.agent.llm.model
    provider = config.agent.llm.provider

    # Check feature flags
    if config.features.enable_three_layer_arch:
        ...

Environment Variables:
    LLM_PROVIDER          - Provider: openai, anthropic, glm
    LLM_MODEL             - Model name (e.g., gpt-4o-mini)
    LLM_API_KEY           - API key
    LLM_BASE_URL          - Custom API endpoint
    LLM_TEMPERATURE       - Sampling temperature (0.0-2.0)
    LLM_MAX_TOKENS        - Maximum tokens
    LLM_TIMEOUT           - Request timeout (seconds)

    AGENT_NAME            - Agent name
    NUM_TASK_AGENTS       - Number of task agents
    ENABLE_THREE_LAYER_ARCH - Enable three-layer architecture

    SERVER_HOST           - Server host (default: 0.0.0.0)
    SERVER_PORT           - Server port (default: 8000)

    WEATHER_API_KEY       - Weather tool API key
    WEATHER_DEFAULT_LOCATION - Default location for weather
    SEARCH_API_KEY        - Web search API key
    SEARCH_ENGINE         - Search engine (google, bing, duckduckgo)

    DEBUG                 - Enable debug mode
    LOG_LEVEL             - Log level (DEBUG, INFO, WARNING, ERROR)
"""
from .loader import (
    ConfigLoader,
    get_config,
    reload_config,
    get_loader,
    ENV_MAPPINGS,
)

from .models import (
    # Main configuration
    AppConfig,
    AgentSettings,
    ServerSettings,
    FeatureFlags,

    # LLM configuration
    LLMSettings,
    LLMProvider,

    # Memory configuration
    MemorySettings,
    MemoryBackend,
    EmbeddingSettings,
    EmbeddingBackend,

    # Message bus configuration
    MessageBusSettings,
    MessageBusBackend,
    DropPolicy,

    # Other settings
    PersonalitySettings,
    PluginSettings,

    # Tools settings
    ToolsSettings,
    WeatherToolSettings,
    WebSearchToolSettings,

    # Backward compatibility
    Config,
)

__all__ = [
    # Main API
    "get_config",
    "reload_config",
    "get_loader",

    # Loader class
    "ConfigLoader",

    # Mappings (for documentation/debugging)
    "ENV_MAPPINGS",

    # Configuration models
    "AppConfig",
    "AgentSettings",
    "ServerSettings",
    "FeatureFlags",
    "LLMSettings",
    "LLMProvider",
    "MemorySettings",
    "MemoryBackend",
    "EmbeddingSettings",
    "EmbeddingBackend",
    "MessageBusSettings",
    "MessageBusBackend",
    "DropPolicy",
    "PersonalitySettings",
    "PluginSettings",
    "ToolsSettings",
    "WeatherToolSettings",
    "WebSearchToolSettings",

    # Backward compatibility
    "Config",
]
