"""
HTTP Fetch Provider

Fetch web page content via direct HTTP request.
"""
from typing import Any, Dict
from urllib.parse import urljoin

import aiohttp

from ..base import Provider, ProviderConfig
from ...utils.network_safety import blocked_url_target_reason


class HttpFetchProvider(Provider):
    """Direct HTTP fetching provider."""

    MAX_REDIRECTS = 5

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
        proxy_url = str(params.get("proxy_url") or "").strip() or None
        allow_rfc2544_benchmark_range = bool(
            params.get("allow_rfc2544_benchmark_range", False)
        )
        allow_private_network = bool(params.get("allow_private_network", False))
        private_network_allowlist = list(params.get("private_network_allowlist") or [])
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

        current_url = url
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            for _ in range(self.MAX_REDIRECTS + 1):
                block_reason = await blocked_url_target_reason(
                    current_url,
                    allow_private_network=allow_private_network,
                    private_network_allowlist=private_network_allowlist,
                    allow_rfc2544_benchmark_range=allow_rfc2544_benchmark_range,
                )
                if block_reason:
                    raise RuntimeError(f"Blocked web-fetch redirect target: {block_reason}")

                async with session.get(
                    current_url,
                    headers=headers,
                    allow_redirects=False,
                    proxy=proxy_url,
                ) as response:
                    if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                        current_url = urljoin(str(response.url), str(response.headers["Location"]))
                        continue

                    html = await response.text(errors="ignore")
                    content_type = response.headers.get("Content-Type", "")
                    final_url = str(response.url)
                    status_code = response.status
                    break
            else:
                raise RuntimeError(f"Too many redirects while fetching {url}")

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
