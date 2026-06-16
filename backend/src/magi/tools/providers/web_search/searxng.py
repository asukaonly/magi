"""SearXNG search provider."""

from __future__ import annotations

from typing import Any, Dict, List

import aiohttp

from ..base import Provider, ProviderConfig


class SearXNGSearchProvider(Provider):
    """Search through a user-configured SearXNG instance."""

    @property
    def name(self) -> str:
        return "searxng"

    @property
    def display_name(self) -> str:
        return "SearXNG"

    def is_ready(self, config: ProviderConfig) -> bool:
        """SearXNG needs an explicit instance URL."""
        return bool((config.base_url or "").strip())

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig,
    ) -> Dict[str, Any]:
        query = params["query"]
        num_results = int(params.get("num_results", 10))
        proxy_url = str(params.get("proxy_url") or "").strip() or None
        base_url = str(config.base_url or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("SearXNG base URL is not configured")

        request_params = {
            "q": query,
            "format": "json",
            "language": "auto",
            "safesearch": "0",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "Magi/1.0 (+https://github.com/asukaonly/magi)",
        }

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.get(
                f"{base_url}/search",
                params=request_params,
                headers=headers,
                proxy=proxy_url,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"SearXNG API error: {response.status} - {error_text}")
                data = await response.json(content_type=None)

        results = self._normalize_results(data, num_results)
        return {
            "results": results,
            "provider": self.name,
            "total": len(results),
        }

    def _normalize_results(self, data: Dict[str, Any], num_results: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for item in list(data.get("results") or [])[:num_results]:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "description": str(item.get("content") or "").strip(),
                    "source": str(item.get("engine") or "searxng").strip(),
                }
            )
        return results
