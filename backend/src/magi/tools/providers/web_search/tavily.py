"""
Tavily Search Provider

Search the web using Tavily API.
"""
import aiohttp
from typing import Dict, Any, List

from ..base import Provider, ProviderConfig


class TavilySearchProvider(Provider):
    """Tavily API provider."""

    @property
    def name(self) -> str:
        return "tavily"

    @property
    def display_name(self) -> str:
        return "Tavily"

    def is_ready(self, config: ProviderConfig) -> bool:
        """Check if Tavily API key is configured."""
        return bool(config.api_key)

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig
    ) -> Dict[str, Any]:
        """
        Execute Tavily API call.

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
            raise ValueError("Tavily API key not configured")

        url = "https://api.tavily.com/search"
        headers = {
            "Content-type": "application/json",
        }
        payload = {
            "api_key": config.api_key,
            "query": query,
            "max_results": num_results,
            "include_answer": True,
            "include_raw_content": False,
        }

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.post(url, headers=headers, json=payload, proxy=proxy_url) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Tavily API error: {response.status} - {error_text}")

                data = await response.json()

        results = self._normalize_results(data, num_results)

        return {
            "results": results,
            "provider": self.name,
            "total": len(results),
        }

    def _normalize_results(self, data: Dict[str, Any], num_results: int) -> List[Dict[str, Any]]:
        """Normalize Tavily API response to common format."""
        results = []
        tavily_results = data.get("results", [])

        for item in tavily_results[:num_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("content", ""),
                "source": item.get("source", ""),
                "score": item.get("score"),
            })

        # Include answer if available
        if data.get("answer"):
            results.insert(0, {
                "title": "AI Answer",
                "url": "",
                "description": data["answer"],
                "source": "tavily-ai",
            })

        return results
