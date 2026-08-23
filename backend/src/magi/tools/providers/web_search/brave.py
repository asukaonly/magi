"""
Brave Search Provider

Search the web using Brave Search API.
"""
import aiohttp
from typing import Dict, Any, List

from ..base import Provider, ProviderConfig
from ..http_errors import ProviderRateLimitError, parse_retry_after_seconds


class BraveSearchProvider(Provider):
    """Brave Search API provider."""

    @property
    def name(self) -> str:
        return "brave"

    @property
    def display_name(self) -> str:
        return "Brave Search"

    def is_ready(self, config: ProviderConfig) -> bool:
        """Check if Brave API key is configured."""
        return bool(config.api_key)

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig
    ) -> Dict[str, Any]:
        """
        Execute Brave Search API call.

        Args:
            params: Must contain 'query', optional 'num_results'
            config: Must contain 'api_key'

        Returns:
            Dict with 'results' list containing search results
        """
        query = params["query"]
        num_results = params.get("num_results", 10)
        proxy_url = str(params.get("proxy_url") or "").strip() or None

        if not config.api_key:
            raise ValueError("Brave API key not configured")

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": config.api_key,
        }
        request_params = {
            "q": query,
            "count": num_results,
        }

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(url, headers=headers, params=request_params, proxy=proxy_url) as response:
                if response.status == 429:
                    raise ProviderRateLimitError(
                        "Brave Search rate limit exceeded",
                        retry_after_seconds=parse_retry_after_seconds(
                            response.headers.get("Retry-After")
                        ),
                    )
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Brave API error: {response.status} - {error_text}")

                data = await response.json()

        results = self._normalize_results(data, num_results)

        return {
            "results": results,
            "provider": self.name,
            "total": len(results),
        }

    def _normalize_results(self, data: Dict[str, Any], num_results: int) -> List[Dict[str, Any]]:
        """Normalize Brave API response to common format."""
        results = []
        web_results = data.get("web", {}).get("results", [])

        for item in web_results[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "source": item.get("source", ""),
            })

        return results
