"""
Weather Tool - Query weather using multiple providers
"""
from typing import Dict, Any, Optional

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolConfigSpec
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
                "Configure provider settings via system-settings tool "
                "(for example: tool.weather.providers.qweather.api_key)."
            ),
            category="information",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="location",
                    type=ParameterType.STRING,
                    description="Location to query. Can be city name or coordinates.",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ParameterType.STRING,
                    description="Language: 'zh' (Chinese) or 'en' (English)",
                    required=False,
                    default="zh",
                    enum=["zh", "en"],
                ),
            ],
            examples=[
                {
                    "input": {"location": "Beijing"},
                    "output": "Returns current weather in Beijing",
                },
                {
                    "input": {"location": "Shanghai", "lang": "en"},
                    "output": "Returns weather in Shanghai (English)",
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

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute weather query."""
        return await self._handle_query(parameters)

    def list_config_specs(self) -> list[ToolConfigSpec]:
        """Describe tool-scoped config entries managed by this tool."""
        return [
            ToolConfigSpec(
                path="default_provider",
                type="string",
                description="Default weather provider",
            ),
            ToolConfigSpec(
                path="providers.{provider}.api_key",
                type="string",
                description="Provider API key",
                sensitive=True,
            ),
            ToolConfigSpec(
                path="providers.{provider}.base_url",
                type="string",
                description="Provider base URL (optional)",
            ),
        ]

    async def get_config_value(self, path: str, context: ToolExecutionContext) -> ToolResult:
        """Read non-sensitive tool-scoped config values."""
        config = get_config().tools.weather
        if path == "default_provider":
            return ToolResult(success=True, data=config.default_provider)

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            return ToolResult(success=True, data=config.get_provider_config(provider_name).base_url)

        return ToolResult(
            success=False,
            error=f"Unsupported config path for weather: {path}",
            error_code="UNSUPPORTED_PATH",
        )

    async def update_config(self, path: str, value: Any, context: ToolExecutionContext) -> ToolResult:
        """Update tool-scoped config values via tool-owned validation logic."""
        if path == "default_provider":
            provider_name = str(value)
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code="INVALID_PROVIDER",
                )
            if save_config({"tools.weather.default_provider": provider_name}):
                return ToolResult(success=True, data={"path": path, "value": provider_name})
            return ToolResult(success=False, error="Failed to save configuration", error_code="SAVE_FAILED")

        if path.startswith("providers.") and path.endswith(".api_key"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code="INVALID_PROVIDER",
                )
            if save_config({f"tools.weather.providers.{provider_name}.api_key": str(value)}):
                return ToolResult(success=True, data={"provider": provider_name, "configured": True})
            return ToolResult(success=False, error="Failed to save configuration", error_code="SAVE_FAILED")

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code="INVALID_PROVIDER",
                )
            if save_config({f"tools.weather.providers.{provider_name}.base_url": str(value)}):
                return ToolResult(success=True, data={"provider": provider_name, "base_url": str(value)})
            return ToolResult(success=False, error="Failed to save configuration", error_code="SAVE_FAILED")

        return ToolResult(
            success=False,
            error=f"Unsupported config path for weather: {path}",
            error_code="UNSUPPORTED_PATH",
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
