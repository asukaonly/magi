"""
HTTP Fetch Provider

Fetch web page content via direct HTTP request.
"""
from typing import Any, Dict

import aiohttp

from ..base import Provider, ProviderConfig


class HttpFetchProvider(Provider):
    """Direct HTTP fetching provider."""

    @property
    def name(self) -> str:
        return "http"

    @property
    def display_name(self) -> str:
        return "HTTP Fetch"

    def is_ready(self, config: ProviderConfig) -> bool:
        """HTTP provider is always ready."""
        return True

    async def execute(self, params: Dict[str, Any], config: ProviderConfig) -> Dict[str, Any]:
        """Execute direct HTTP fetch."""
        url = str(params["url"]).strip()
        timeout_ms = int(params.get("timeout_ms", 15000))
        user_agent = str(
            params.get(
                "user_agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
        )

        timeout_sec = max(1, timeout_ms) / 1000
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                html = await response.text(errors="ignore")
                content_type = response.headers.get("Content-Type", "")
                final_url = str(response.url)
                status_code = response.status

        return {
            "provider": self.name,
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "title": "",
            "html": html,
            "rendered": False,
        }
