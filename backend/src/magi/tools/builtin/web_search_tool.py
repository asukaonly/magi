"""
Web Search Tool - Search web using multiple providers
"""
from datetime import date
from typing import Dict, Any, List

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolConfigSpec, ToolErrorCode
from ..providers.base import ProviderConfig
from ..providers.web_search import DuckDuckGoSearchProvider, BraveSearchProvider, PerplexitySearchProvider, TavilySearchProvider
from ...config import get_config, save_config


# Provider display info for messages
PROVIDER_INFO = {
    "duckduckgo": {"name": "DuckDuckGo"},
    "brave": {"name": "Brave Search", "env_var": "BRAVE_API_KEY"},
    "perplexity": {"name": "Perplexity AI", "env_var": "PERPLEXITY_API_KEY"},
    "tavily": {"name": "Tavily", "env_var": "TAVILY_API_KEY"},
}


class WebSearchTool(MultiProviderTool):
    """
    Web Search Tool

    Search the web using configured providers.
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="web-search",
            description=(
                "Search the web for information using configured providers.\n\n"
                "Supported providers: duckduckgo, brave, perplexity, tavily.\n"
                "Configure provider settings via system-settings tool "
                "(for example: tool.web-search.providers.brave.api_key)."
            ),
            category="web",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The search query",
                    required=True,
                ),
                ToolParameter(
                    name="provider",
                    type=ParameterType.STRING,
                    description="Search provider: 'duckduckgo', 'brave', 'perplexity', or 'tavily'",
                    required=False,
                    default="duckduckgo",
                    enum=["duckduckgo", "brave", "perplexity", "tavily"],
                ),
                ToolParameter(
                    name="num_results",
                    type=ParameterType.INTEGER,
                    description="Number of results to return",
                    required=False,
                    default=10,
                    min_value=1,
                    max_value=50,
                ),
                ToolParameter(
                    name="start_date",
                    type=ParameterType.STRING,
                    description="Optional inclusive start date in YYYY-MM-DD format for time-bounded search",
                    required=False,
                ),
                ToolParameter(
                    name="end_date",
                    type=ParameterType.STRING,
                    description="Optional inclusive end date in YYYY-MM-DD format for time-bounded search",
                    required=False,
                ),
            ],
            examples=[
                {
                    "input": {"query": "latest AI news"},
                    "output": "Returns search results",
                },
                {
                    "input": {"query": "OpenAI release notes", "provider": "duckduckgo", "num_results": 5},
                    "output": "Returns search results from DuckDuckGo",
                },
            ],
            timeout=30,
            retry_on_failure=True,
            max_retries=2,
            dangerous=False,
            tags=["web", "search", "information"],
        )

    def _register_providers(self) -> None:
        """Register all available web search providers."""
        self.register_provider(DuckDuckGoSearchProvider())
        self.register_provider(BraveSearchProvider())
        self.register_provider(PerplexitySearchProvider())
        self.register_provider(TavilySearchProvider())

    def _get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get configuration for a specific provider."""
        config = get_config()
        return config.tools.web_search.get_provider_config(provider_name)

    def _get_default_provider(self) -> str:
        """Get the default provider name from config."""
        config = get_config()
        return config.tools.web_search.default_provider

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute web search query."""
        return await self._handle_query(parameters)

    def list_config_specs(self) -> List[ToolConfigSpec]:
        """Describe tool-scoped config entries managed by this tool."""
        specs: List[ToolConfigSpec] = [
            ToolConfigSpec(
                path="default_provider",
                type="string",
                description="Default web search provider",
                required=True,
                enum=self.get_all_provider_names(),
            ),
            ToolConfigSpec(
                path="providers.{provider}.api_key",
                type="string",
                description="Provider API key",
                sensitive=True,
                required=True,
                providers=["brave", "perplexity", "tavily"],
            ),
            ToolConfigSpec(
                path="providers.{provider}.base_url",
                type="string",
                description="DuckDuckGo HTML endpoint override (optional)",
                providers=["duckduckgo"],
            ),
        ]
        return specs

    async def get_config_value(self, path: str, context: ToolExecutionContext) -> ToolResult:
        """Read non-sensitive tool-scoped config values."""
        config = get_config().tools.web_search
        if path == "default_provider":
            return ToolResult(success=True, data=config.default_provider)

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            return ToolResult(success=True, data=config.get_provider_config(provider_name).base_url)

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-search: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def update_config(self, path: str, value: Any, context: ToolExecutionContext) -> ToolResult:
        """Update tool-scoped config values via tool-owned validation logic."""
        if path == "default_provider":
            provider_name = str(value)
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({"tools.web_search.default_provider": provider_name}):
                return ToolResult(success=True, data={"path": path, "value": provider_name})
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        if path.startswith("providers.") and path.endswith(".api_key"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({f"tools.web_search.providers.{provider_name}.api_key": str(value)}):
                info = PROVIDER_INFO.get(provider_name, {"name": provider_name})
                return ToolResult(
                    success=True,
                    data={
                        "provider": provider_name,
                        "name": info["name"],
                        "configured": True,
                    },
                )
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        if path.startswith("providers.") and path.endswith(".base_url"):
            provider_name = path.split(".")[1]
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code=ToolErrorCode.INVALID_PROVIDER.value,
                )
            if save_config({f"tools.web_search.providers.{provider_name}.base_url": str(value)}):
                return ToolResult(success=True, data={"provider": provider_name, "base_url": str(value)})
            return ToolResult(success=False, error="Failed to save configuration", error_code=ToolErrorCode.SAVE_FAILED.value)

        return ToolResult(
            success=False,
            error=f"Unsupported config path for web-search: {path}",
            error_code=ToolErrorCode.UNSUPPORTED_PATH.value,
        )

    async def _handle_query(self, parameters: Dict[str, Any]) -> ToolResult:
        """Handle web search query."""
        query = parameters.get("query")

        if not query:
            return ToolResult(
                success=False,
                error="Missing 'query' parameter. Provide a search query.",
                error_code=ToolErrorCode.MISSING_QUERY.value,
            )

        # Use specified provider or default from config
        requested_provider = str(parameters.get("provider") or self._get_default_provider()).strip()
        provider_name = requested_provider
        date_range_applied = self._normalize_date_range(
            parameters.get("start_date"),
            parameters.get("end_date"),
        )
        if isinstance(date_range_applied, ToolResult):
            return date_range_applied
        executed_query = self._apply_date_range_to_query(query, date_range_applied)

        # Check if any provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error=(
                    "No search providers are configured. "
                    "Ask the user to configure a provider API key via system-settings, then retry."
                ),
                error_code=ToolErrorCode.NO_PROVIDERS_CONFIGURED.value,
                data={
                    "next_action": "ask_user_to_configure_api_key",
                    "llm_guidance": (
                        "Do not retry web search until at least one search provider is available. "
                        "Ask the user to confirm tool configuration or restore a supported provider."
                    ),
                    "user_message_template": (
                        "要继续联网搜索，请先确认网页搜索工具配置可用。"
                        "恢复后我会继续当前搜索。"
                    ),
                    "config_tool": "system-settings",
                    "config_example": {
                        "action": "set",
                        "path": "tool.web-search.default_provider",
                        "value": "duckduckgo",
                    },
                    "supported_providers": list(PROVIDER_INFO.keys()),
                },
            )

        # Fall back to first available if requested provider not available
        fallback_reason = None
        if provider_name not in available_providers:
            fallback_reason = (
                f"Requested provider '{requested_provider}' is unavailable; "
                f"used '{available_providers[0]}' instead."
            )
            provider_name = available_providers[0]

        result = await self.execute_with_provider(
            provider_name,
            {
                "query": executed_query,
                "num_results": parameters.get("num_results", 10),
            }
        )

        if not result.success and self._is_duckduckgo_challenge_error(provider_name, result):
            return self._build_duckduckgo_challenge_guidance(
                query=query,
                requested_provider=requested_provider,
                actual_provider=provider_name,
                date_range_applied=date_range_applied,
            )

        if result.success:
            result.data["query"] = query
            result.data["executed_query"] = executed_query
            result.data["requested_provider"] = requested_provider
            result.data["actual_provider"] = provider_name
            if fallback_reason:
                result.data["fallback_reason"] = fallback_reason
            if date_range_applied is not None:
                result.data["date_range_applied"] = date_range_applied

        return result

    def _is_duckduckgo_challenge_error(self, provider_name: str, result: ToolResult) -> bool:
        if provider_name != "duckduckgo":
            return False
        if result.error_code not in {ToolErrorCode.PROVIDER_ERROR.value, ToolErrorCode.PROVIDER_CHALLENGE.value}:
            return False
        error_text = str(result.error or "").lower()
        return any(
            marker in error_text
            for marker in [
                "duckduckgo search challenge triggered",
                "anti-bot verification",
                "bots use duckduckgo too",
                "challenge",
                "captcha",
            ]
        )

    def _build_duckduckgo_challenge_guidance(
        self,
        *,
        query: str,
        requested_provider: str,
        actual_provider: str,
        date_range_applied: Dict[str, str] | None,
    ) -> ToolResult:
        alternative_providers = [name for name in self.get_all_provider_names() if name != "duckduckgo"]
        guidance_data: Dict[str, Any] = {
            "next_action": "ask_user_to_configure_search_provider",
            "llm_guidance": (
                "DuckDuckGo is currently blocked by an anti-bot challenge for this search. "
                "Ask the user to configure Brave, Perplexity, or Tavily via system-settings before retrying. "
                "Do not keep retrying DuckDuckGo for the same request."
            ),
            "user_message_template": (
                "默认的 DuckDuckGo 搜索这次触发了反爬验证，暂时拿不到稳定结果。"
                "请先配置 Brave、Perplexity 或 Tavily 其中一个搜索服务，我再继续帮你查。"
            ),
            "config_tool": "system-settings",
            "requested_provider": requested_provider,
            "actual_provider": actual_provider,
            "fallback_reason": (
                "DuckDuckGo returned an anti-bot verification challenge instead of usable search results."
            ),
            "query": query,
            "supported_providers": alternative_providers,
            "config_examples": [
                {
                    "action": "set",
                    "path": f"tool.web-search.providers.{provider}.api_key",
                    "value": f"YOUR_{provider.upper()}_API_KEY",
                }
                for provider in alternative_providers
            ],
        }
        if date_range_applied is not None:
            guidance_data["date_range_applied"] = date_range_applied
        return ToolResult(
            success=False,
            error="DuckDuckGo search challenge triggered. Configure another web-search provider and retry.",
            error_code=ToolErrorCode.PROVIDER_CHALLENGE.value,
            data=guidance_data,
        )

    def _normalize_date_range(self, start_date: Any, end_date: Any) -> Dict[str, str] | ToolResult | None:
        start = str(start_date or "").strip()
        end = str(end_date or "").strip()
        if not start and not end:
            return None
        if not start or not end:
            return ToolResult(
                success=False,
                error="Both 'start_date' and 'end_date' must be provided together in YYYY-MM-DD format.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        try:
            normalized_start = date.fromisoformat(start)
            normalized_end = date.fromisoformat(end)
        except ValueError:
            return ToolResult(
                success=False,
                error="Invalid date range. Use YYYY-MM-DD for both 'start_date' and 'end_date'.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        if normalized_start > normalized_end:
            return ToolResult(
                success=False,
                error="'start_date' must be on or before 'end_date'.",
                error_code=ToolErrorCode.INVALID_PARAMETERS.value,
            )
        return {
            "start_date": normalized_start.isoformat(),
            "end_date": normalized_end.isoformat(),
        }

    def _apply_date_range_to_query(self, query: str, date_range: Dict[str, str] | None) -> str:
        if not date_range:
            return query
        return (
            f"{query} after:{date_range['start_date']} before:{date_range['end_date']}"
        )
