"""
Web Search Tool - Search web using multiple providers
"""
from typing import Dict, Any, List

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
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
                "Search the web for information.\n\n"
                "Actions:\n"
                "- query (default): Search the web\n"
                "- config: Manage tool configuration (set/get API keys)\n\n"
                "Supported providers: brave, perplexity, tavily\n\n"
                "To configure API key:\n"
                "  {\"action\": \"config\", \"config_action\": \"set\", \"provider\": \"brave\", \"api_key\": \"your-key\"}"
            ),
            category="web",
            version="1.1.0",
            author="Magi Team",
            parameters=[
                ToolParameter(
                    name="action",
                    type=ParameterType.STRING,
                    description="Action: 'query' (search) or 'config' (manage settings)",
                    required=False,
                    default="query",
                    enum=["query", "config"],
                ),
                # Query parameters
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The search query (for 'query' action)",
                    required=False,
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
                    "input": {"query": "latest AI news"},
                    "output": "Returns search results",
                },
                {
                    "input": {"action": "config", "config_action": "set", "provider": "brave", "api_key": "xxx"},
                    "output": "Sets the Brave Search API key",
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

    def _get_config_path(self, provider_name: str) -> str:
        """Get the config path for a provider's API key."""
        return f"tools.web_search.providers.{provider_name}.api_key"

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute web search or config action"""
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

        if config_action == "get":
            # Return config status for all providers
            available = self.get_available_providers()
            all_providers = self.get_all_provider_names()

            providers_status = []
            for p in all_providers:
                info = PROVIDER_INFO.get(p, {"name": p, "env_var": ""})
                providers_status.append({
                    "provider": p,
                    "name": info["name"],
                    "configured": p in available,
                    "env_var": info["env_var"],
                })

            return ToolResult(
                success=True,
                data={
                    "providers": providers_status,
                    "default_provider": self._get_default_provider(),
                    "message": f"Configured providers: {', '.join(available) if available else 'none'}. "
                               f"Use config_action 'set' with provider and api_key to configure.",
                },
            )

        if config_action == "set":
            provider_name = parameters.get("provider") or self._get_default_provider()
            api_key = parameters.get("api_key")

            if not api_key:
                return ToolResult(
                    success=False,
                    error="Missing 'api_key'. Provide the API key to set.",
                    error_code="MISSING_API_KEY",
                )

            # Validate provider
            if provider_name not in self.get_all_provider_names():
                return ToolResult(
                    success=False,
                    error=f"Unknown provider: {provider_name}. Supported: {', '.join(self.get_all_provider_names())}",
                    error_code="INVALID_PROVIDER",
                )

            # Save the API key
            config_path = self._get_config_path(provider_name)
            if save_config({config_path: api_key}):
                info = PROVIDER_INFO.get(provider_name, {"name": provider_name})
                return ToolResult(
                    success=True,
                    data={
                        "provider": provider_name,
                        "name": info["name"],
                        "configured": True,
                        "message": f"API key for '{info['name']}' has been saved successfully.",
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
        """Handle web search query."""
        query = parameters.get("query")

        if not query:
            return ToolResult(
                success=False,
                error="Missing 'query' parameter. Provide a search query.",
                error_code="MISSING_QUERY",
            )

        # Use specified provider or default from config
        provider_name = parameters.get("provider") or self._get_default_provider()

        # Check if any provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error="No search providers are configured. Use action 'config' to set an API key.",
                error_code="NO_PROVIDERS_CONFIGURED",
                data={
                    "hint": 'Use: {"action": "config", "config_action": "set", "provider": "brave", "api_key": "your-key"}',
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
