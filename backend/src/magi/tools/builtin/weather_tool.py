"""
Weather Tool - Query weather using multiple providers
"""
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolConfigSpec, ToolErrorCode
from ..providers.base import ProviderConfig
from ..providers.weather import QWeatherProvider
from ...config import get_config, save_config
from ...core.logger import get_logger


logger = get_logger(__name__, category="TOOLS")


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
                "Supports current weather and forecast queries.\n\n"
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
                ToolParameter(
                    name="mode",
                    type=ParameterType.STRING,
                    description="Query mode: 'current' for real-time weather, 'forecast' for multi-day forecast",
                    required=False,
                    default="current",
                    enum=["current", "forecast"],
                ),
                ToolParameter(
                    name="days",
                    type=ParameterType.INTEGER,
                    description="Forecast days when mode='forecast' (1-7)",
                    required=False,
                    default=3,
                    min_value=1,
                    max_value=7,
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
                {
                    "input": {"location": "Hangzhou", "mode": "forecast", "days": 3},
                    "output": "Returns 3-day weather forecast in Hangzhou",
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

    def _normalize_api_host(self, raw_value: Any) -> str:
        """Normalize user-provided endpoint to host-only format."""
        text = str(raw_value).strip()
        if not text:
            return ""

        # Accept full URL and extract host part.
        if "://" in text:
            parsed = urlparse(text)
            text = parsed.netloc or parsed.path

        text = text.strip().strip("/")
        if "/" in text:
            text = text.split("/", 1)[0]
        return text

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
                required=True,
                enum=self.get_all_provider_names(),
            ),
            ToolConfigSpec(
                path="providers.{provider}.api_key",
                type="string",
                description="Provider API key",
                sensitive=True,
                required=True,
                providers=["qweather"],
            ),
            ToolConfigSpec(
                path="providers.{provider}.base_url",
                type="string",
                description="Provider base URL",
                required=True,
                providers=["qweather"],
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
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def update_config(self, path: str, value: Any, context: ToolExecutionContext) -> ToolResult:
        """Update tool-scoped config values via tool-owned validation logic."""
        logger.info(
            "weather config update requested",
            path=path,
            value_provided=value is not None,
            value_length=len(str(value)) if value is not None else 0,
        )

        if path == "default_provider":
            provider_name = str(value)
            if provider_name not in self.get_all_provider_names():
                logger.warning(
                    "weather config update rejected (invalid provider)",
                    path=path,
                    provider=provider_name,
                )
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({"tools.weather.default_provider": provider_name}):
                logger.info("weather config saved", path=path, provider=provider_name)
                return ToolResult(success=True, data={"path": path, "value": provider_name})
            logger.error("weather config save failed", path=path, provider=provider_name)
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        if path.startswith("providers.") and path.endswith(".api_key"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                logger.warning(
                    "weather config update rejected (invalid provider)",
                    path=path,
                    provider=provider_name,
                )
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({f"tools.weather.providers.{provider_name}.api_key": str(value)}):
                logger.info(
                    "weather config saved",
                    path=path,
                    provider=provider_name,
                    configured=bool(str(value).strip()),
                )
                return ToolResult(success=True, data={"provider": provider_name, "configured": True})
            logger.error("weather config save failed", path=path, provider=provider_name)
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                logger.warning(
                    "weather config update rejected (invalid provider)",
                    path=path,
                    provider=provider_name,
                )
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            normalized_host = self._normalize_api_host(value)
            if save_config({f"tools.weather.providers.{provider_name}.base_url": normalized_host}):
                stored_host = (
                    get_config().tools.weather.get_provider_config(provider_name).base_url
                )
                logger.info(
                    "weather config saved",
                    path=path,
                    provider=provider_name,
                    normalized_host=normalized_host or None,
                    stored_host=stored_host,
                )
                return ToolResult(
                    success=True,
                    data={
                        "provider": provider_name,
                        "base_url": normalized_host or None,
                        "normalized": str(value).strip() != normalized_host,
                    },
                )
            logger.error(
                "weather config save failed",
                path=path,
                provider=provider_name,
                normalized_host=normalized_host or None,
            )
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        logger.warning("weather config update rejected (unsupported path)", path=path)
        return ToolResult(
            success=False,
            error=f"Unsupported config path for weather: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def _handle_query(self, parameters: Dict[str, Any]) -> ToolResult:
        """Handle weather query."""
        location = parameters.get("location")

        if not location:
            return ToolResult(
                success=False,
                error="Missing 'location' parameter. Provide a city name or coordinates.",
                error_code=ToolErrorCode.MISSING_LOCATION.value,
            )

        lang = parameters.get("lang", "zh")
        mode = parameters.get("mode", "current")
        days = parameters.get("days", 3)
        provider_name = self._get_default_provider()

        if mode not in {"current", "forecast"}:
            return ToolResult(
                success=False,
                error="Invalid 'mode'. Use 'current' or 'forecast'.",
                error_code=ToolErrorCode.INVALID_MODE.value,
            )

        if mode == "forecast":
            try:
                days = int(days)
            except (TypeError, ValueError):
                return ToolResult(
                    success=False,
                    error="Invalid 'days'. Must be an integer between 1 and 7.",
                    error_code=ToolErrorCode.INVALID_DAYS.value,
                )
            if days < 1 or days > 7:
                return ToolResult(
                    success=False,
                    error="Invalid 'days'. Must be between 1 and 7.",
                    error_code=ToolErrorCode.INVALID_DAYS.value,
                )

        # Check if any provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error=(
                    "Weather API key is not configured. "
                    "Ask the user to configure key path "
                    "'tool.weather.providers.qweather.api_key' via system-settings, then retry."
                ),
                error_code=ToolErrorCode.NO_PROVIDERS_CONFIGURED.value,
                data={
                    "next_action": "ask_user_to_configure_api_key",
                    "llm_guidance": (
                        "Do not retry weather query until API key is configured. "
                        "Ask user to provide/confirm API key, then call system-settings with action=set."
                    ),
                    "user_message_template": (
                        "要继续查询天气，请先配置和风天气 API Key。"
                        "配置后我会立即重试当前天气查询。"
                    ),
                    "config_tool": "system-settings",
                    "config_path": "tool.weather.providers.qweather.api_key",
                    "config_example": {
                        "action": "set",
                        "path": "tool.weather.providers.qweather.api_key",
                        "value": "<your-qweather-api-key>",
                    },
                    "retry_example": {
                        "location": location,
                        "lang": lang,
                    },
                },
            )

        result = await self.execute_with_provider(
            provider_name,
            {
                "location": location,
                "lang": lang,
                "mode": mode,
                "days": days,
            }
        )

        if not result.success and provider_name == "qweather":
            lower_error = (result.error or "").lower()
            base_url_error_markers = (
                "invalid-host",
                "invalid_host",
                "invaild-host",
                "unauthorized api host",
                "invalid or unauthorized api host",
                "requires a configured base url",
            )
            if any(marker in lower_error for marker in base_url_error_markers):
                return ToolResult(
                    success=False,
                    error=(
                        "QWeather base URL is not configured correctly. "
                        "Use system-settings to set "
                        "'tool.weather.providers.qweather.base_url', then retry."
                    ),
                    error_code=ToolErrorCode.QWEATHER_BASE_URL_REQUIRED.value,
                    data={
                        "next_action": "configure_qweather_base_url",
                        "llm_guidance": (
                            "Call system-settings with action=set to configure "
                            "'tool.weather.providers.qweather.base_url', then retry weather query."
                        ),
                        "config_tool": "system-settings",
                        "config_path": "tool.weather.providers.qweather.base_url",
                        "config_example": {
                            "action": "set",
                            "path": "tool.weather.providers.qweather.base_url",
                            "value": "<base-url-from-qweather-console>",
                        },
                        "reference_url": "https://console.qweather.com/setting",
                        "retry_example": {
                            "location": location,
                            "lang": lang,
                            "mode": mode,
                            "days": days,
                        },
                    },
                )

        return result
