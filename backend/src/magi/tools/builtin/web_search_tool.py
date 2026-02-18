"""
Web Search Tool - Search web using multiple providers
"""
from typing import Dict, Any

from ..schema import MultiProviderTool, ToolSchema, ToolExecutionContext, ToolResult, ToolParameter, ParameterType
from ..providers.base import ProviderConfig
from ..providers.web_search import BraveSearchProvider, PerplexitySearchProvider, TavilySearchProvider


class WebSearchTool(MultiProviderTool):
    """
    Web Search Tool

    Search the web using multiple providers (Brave, Perplexity, Tavily).
    """

    def _init_schema(self) -> None:
        """Initialize Schema"""
        self.schema = ToolSchema(
            name="web-search",
            description="Search the web for information. Supports multiple search providers.",
            category="web",
            version="1.0.0",
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
                    "input": {"query": "latest AI news", "provider": "brave"},
                    "output": "Returns search results from Brave",
                },
                {
                    "input": {"query": "Python async programming", "provider": "perplexity", "num_results": 5},
                    "output": "Returns 5 search results from Perplexity",
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
        from ...config import get_config
        config = get_config()
        provider_config = config.tools.web_search.providers.get(provider_name, {})
        return ProviderConfig(
            api_key=provider_config.api_key if hasattr(provider_config, 'api_key') else provider_config.get("api_key"),
            base_url=provider_config.base_url if hasattr(provider_config, 'base_url') else provider_config.get("base_url"),
        )

    def _get_default_provider(self) -> str:
        """Get the default provider name from config."""
        from ...config import get_config
        config = get_config()
        return config.tools.web_search.default_provider

    def _update_schema_with_available_providers(self) -> None:
        """Update schema enum with only available providers."""
        available = self.get_available_providers()
        if available:
            # Update the provider parameter enum to only show available providers
            for param in self.schema.parameters:
                if param.name == "provider":
                    param.enum = available
                    if param.default not in available and available:
                        param.default = available[0]
                    break

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute web search"""
        query = parameters["query"]

        # Use specified provider or default from config
        provider_name = parameters.get("provider")
        if not provider_name:
            provider_name = self._get_default_provider()

        # Check if provider is available
        available_providers = self.get_available_providers()
        if not available_providers:
            return ToolResult(
                success=False,
                error="No search providers are configured. Please set an API key for at least one provider (BRAVE_API_KEY, PERPLEXITY_API_KEY, or TAVILY_API_KEY).",
                error_code="NO_PROVIDERS_CONFIGURED",
            )

        # Fall back to first available if requested provider not available
        if provider_name not in available_providers:
            original_provider = provider_name
            provider_name = available_providers[0]
            # Could log a warning here about fallback

        result = await self.execute_with_provider(
            provider_name,
            {
                "query": query,
                "num_results": parameters.get("num_results", 10),
            }
        )

        if result.success:
            # Add query to result data
            result.data["query"] = query

        return result
