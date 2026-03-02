"""
Web Search Tool - Search web using multiple providers
"""
from typing import Dict, Any, List

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType, ToolConfigSpec, ToolErrorCode
from ..providers.base import ProviderConfig
from ..providers.web_search import BraveSearchProvider, PerplexitySearchProvider, TavilySearchProvider
from ...config import get_config, save_config


# Provider display info for messages
PROVIDER_INFO = {
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
                "Supported providers: brave, perplexity, tavily.\n"
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
                    description="Search provider: 'brave', 'perplexity', or 'tavily'",
                    required=False,
                    default="brave",
                    enum=["brave", "perplexity", "tavily"],
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
            ],
            examples=[
                {
                    "input": {"query": "latest AI news"},
                    "output": "Returns search results",
                },
                {
                    "input": {"query": "OpenAI release notes", "provider": "brave", "num_results": 5},
                    "output": "Returns search results from Brave",
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
        provider_name = parameters.get("provider") or self._get_default_provider()

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
                        "Do not retry web search until one provider key is configured. "
                        "Ask user to provide/confirm a key and set it using system-settings action=set."
                    ),
                    "user_message_template": (
                        "要继续联网搜索，请先配置任一搜索提供商的 API Key（如 brave）。"
                        "配置后我会继续当前搜索。"
                    ),
                    "config_tool": "system-settings",
                    "config_example": {
                        "action": "set",
                        "path": "tool.web-search.providers.brave.api_key",
                        "value": "<your-brave-api-key>",
                    },
                    "supported_providers": list(PROVIDER_INFO.keys()),
                },
            )

        # Fall back to first available if requested provider not available
        if provider_name not in available_providers:
            provider_name = available_providers[0]

        result = await self.execute_with_provider(
            provider_name,
            {
                "query": query,
                "num_results": parameters.get("num_results", 10),
            }
        )

        if result.success:
            result.data["query"] = query

        return result
