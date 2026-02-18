"""
Perplexity Search Provider

Search the web using Perplexity AI API.
"""
import aiohttp
from typing import Dict, Any, List

from ..base import Provider, ProviderConfig


class PerplexitySearchProvider(Provider):
    """Perplexity AI API provider."""

    @property
    def name(self) -> str:
        return "perplexity"

    @property
    def display_name(self) -> str:
        return "Perplexity AI"

    def is_ready(self, config: ProviderConfig) -> bool:
        """Check if Perplexity API key is configured."""
        return bool(config.api_key)

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig
    ) -> Dict[str, Any]:
        """
        Execute Perplexity API call.

        Args:
            params: Must contain 'query', optional 'num_results'
            config: Must contain 'api_key'

        Returns:
            Dict with 'results' list containing search results
        """
        query = params["query"]
        num_results = params.get("num_results", 10)

        if not config.api_key:
            raise ValueError("Perplexity API key not configured")

        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-type": "application/json",
        }
        payload = {
            "model": "llama-3.1-sonar-small-128k-online",
            "messages": [
                {
                    "role": "system",
                    "content": f"Return the top {num_results} search results. Format each result as: Title, url, Description. Be concise."
                },
                {
                    "role": "user",
                    "content": query,
                }
            ],
            "max_tokens": 2000,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Perplexity API error: {response.status} - {error_text}")

                data = await response.json()

        results = self._normalize_results(data, num_results)

        return {
            "results": results,
            "provider": self.name,
            "total": len(results),
        }

    def _normalize_results(self, data: Dict[str, Any], num_results: int) -> List[Dict[str, Any]]:
        """Normalize Perplexity API response to common format."""
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Try to parse citations if available
        results = []
        citations = data.get("citations", [])

        if citations:
            for i, citation in enumerate(citations[:num_results]):
                results.append({
                    "title": f"Result {i + 1}",
                    "url": citation,
                    "description": "See citation for details",
                    "source": "perplexity",
                })
        else:
            # Return the content as a single result
            results.append({
                "title": "Search Results",
                "url": "",
                "description": content,
                "source": "perplexity",
            })

        return results
