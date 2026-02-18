"""
Weather Tool - Query weather using QWeather (和风天气) API
"""
from typing import Dict, Any

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ..providers.base import ProviderConfig
from ..providers.weather import QWeatherProvider


class WeatherTool(MultiProviderTool):
    """
    Weather Tool

    Query weather information using QWeather (和风天气) API.
    Supports querying by city name or coordinates.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="weather",
            description="Query weather information for a specific location. Returns current weather including temperature, humidity, wind, and more.",
            category="information",
            version="1.0.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="location",
                    type=ParameterType.STRING,
                    description="Location to query. Can be a city name (e.g., 'Beijing', '上海') or coordinates as 'longitude,latitude' (e.g., '116.41,39.92')",
                    required=True,
                ),
                ToolParameter(
                    name="lang",
                    type=ParameterType.STRING,
                    description="Language for weather descriptions: 'zh' (Chinese, default), 'en' (English)",
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
                    "input": {"location": "上海", "lang": "zh"},
                    "output": "Returns current weather in Shanghai with Chinese descriptions",
                },
            ],
            timeout=15,
            retry_on_failure=True,
            max_retries=2,
            dangerous=False,
            tags=["weather", "information", "qweather"],
        )

    def _register_providers(self) -> None:
        """Register all available weather providers."""
        self.register_provider(QWeatherProvider())

    def _get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get configuration for a specific provider with backward compatibility."""
        from ...config import get_config
        config = get_config()
        return config.tools.weather.get_provider_config(provider_name)

    def _get_default_provider(self) -> str:
        """Get the default provider name from config."""
        from ...config import get_config
        config = get_config()
        return config.tools.weather.default_provider

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute weather query"""
        location = parameters["location"]
        lang = parameters.get("lang", "zh")

        # Weather tool only has one provider, but we use the same pattern
        provider_name = self._get_default_provider()

        # Check if any provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error="Weather API key not configured. Set QWEATHER_API_KEY environment variable or configure in agent.yaml. Get your key from https://dev.qweather.com/",
                error_code="NO_PROVIDERS_CONFIGURED",
            )

        result = await self.execute_with_provider(
            provider_name,
            {
                "location": location,
                "lang": lang,
            }
        )

        return result
