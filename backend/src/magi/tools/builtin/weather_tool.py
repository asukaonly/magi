"""
Weather Tool - Query weather using multiple providers
"""
from typing import Dict, Any, Optional

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ..providers.base import ProviderConfig
from ..providers.weather import QWeatherProvider
from ...config import get_config, save_config


class WeatherTool(MultiProviderTool):
    """
    Weather Tool

    Query weather information using configured providers.
    Supports querying by city name or coordinates.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="weather",
            description=(
                "Query weather information for a specific location. "
                "Returns current weather including temperature, humidity, wind, and more.\n\n"
                "Actions:\n"
                "- query (default): Get weather for a location\n"
                "- config: Manage tool configuration (set/get API key)\n\n"
                "To configure API key:\n"
                "  {\"action\": \"config\", \"config_action\": \"set\", \"api_key\": \"your-api-key\"}"
            ),
            category="information",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action: 'query' (get weather) or 'config' (manage settings)",
                    required=False,
                    default="query",
                    enum=["query", "config"],
                ),
                # Query parameters
                ToolParameter(
                    name="location",
                    type=ParameterType.STRING,
                    description="Location to query (for 'query' action). Can be city name or coordinates.",
                    required=False,
                ),
                ToolParameter(
                    name="lang",
                    type=ParameterType.STRING,
                    description="Language: 'zh' (Chinese) or 'en' (English)",
                    required=False,
                    default="zh",
                    enum=["zh", "en"],
                ),
                # Config parameters
                ToolParameter(
                    name="config_action",
                    type=ParameterType.STRING,
                    description="Config action (for 'config' action): 'get' or 'set'",
                    required=False,
                    enum=["get", "set"],
                ),
                ToolParameter(
                    name="api_key",
                    type=ParameterType.STRING,
                    description="API key to set (for 'config' action with 'set')",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"location": "Beijing"},
                    "output": "Returns current weather in Beijing",
                },
                {
                    "input": {"action": "config", "config_action": "set", "api_key": "xxx"},
                    "output": "Sets the weather API key",
                },
            ],
            timeout=15,
            retry_on_failure=True,
            max_retries=2,
            dangerous=False,
            tags=["weather", "information"],
        )

    def _register_providers(self) -> None:
        """Register all available weather providers."""
        self.register_provider(QWeatherProvider())

    def _get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get configuration for a specific provider."""
        config = get_config()
        return config.tools.weather.get_provider_config(provider_name)

    def _get_default_provider(self) -> str:
        """Get the default provider name from config."""
        config = get_config()
        return config.tools.weather.default_provider

    def _get_config_path(self, provider_name: str) -> str:
        """Get the config path for a provider's API key."""
        return f"tools.weather.providers.{provider_name}.api_key"

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute weather query or config action"""
        action = parameters.get("action", "query")

        if action == "config":
            return await self._handle_config(parameters)

        return await self._handle_query(parameters)

    async def _handle_config(self, parameters: Dict[str, Any]) -> ToolResult:
        """Handle configuration actions."""
        config_action = parameters.get("config_action")

        if not config_action:
            return ToolResult(
                success=False,
                error="Missing 'config_action'. Use 'get' or 'set'.",
                error_code="MISSING_CONFIG_ACTION",
            )

        provider_name = self._get_default_provider()

        if config_action == "get":
            # Return current config status (not the actual key for security)
            available = self.get_available_providers()
            return ToolResult(
                success=True,
                data={
                    "provider": provider_name,
                    "configured": provider_name in available,
                    "message": f"Provider '{provider_name}' is {'configured' if provider_name in available else 'not configured'}. "
                               f"Use config_action 'set' with api_key to configure.",
                },
            )

        if config_action == "set":
            api_key = parameters.get("api_key")
            if not api_key:
                return ToolResult(
                    success=False,
                    error="Missing 'api_key'. Provide the API key to set.",
                    error_code="MISSING_API_KEY",
                )

            # Save the API key
            config_path = self._get_config_path(provider_name)
            if save_config({config_path: api_key}):
                return ToolResult(
                    success=True,
                    data={
                        "provider": provider_name,
                        "configured": True,
                        "message": f"API key for '{provider_name}' has been saved successfully.",
                    },
                )
            else:
                return ToolResult(
                    success=False,
                    error="Failed to save configuration",
                    error_code="SAVE_FAILED",
                )

        return ToolResult(
            success=False,
            error=f"Unknown config_action: {config_action}. Use 'get' or 'set'.",
            error_code="INVALID_CONFIG_ACTION",
        )

    async def _handle_query(self, parameters: Dict[str, Any]) -> ToolResult:
        """Handle weather query."""
        location = parameters.get("location")

        if not location:
            return ToolResult(
                success=False,
                error="Missing 'location' parameter. Provide a city name or coordinates.",
                error_code="MISSING_LOCATION",
            )

        lang = parameters.get("lang", "zh")
        provider_name = self._get_default_provider()

        # Check if any provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error="Weather API key not configured. Use action 'config' to set the API key.",
                error_code="NO_PROVIDERS_CONFIGURED",
                data={
                    "hint": 'Use: {"action": "config", "config_action": "set", "api_key": "your-key"}',
                },
            )

        result = await self.execute_with_provider(
            provider_name,
            {
                "location": location,
                "lang": lang,
            }
        )

        return result
