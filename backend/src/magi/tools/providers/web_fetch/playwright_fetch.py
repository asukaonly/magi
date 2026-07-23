"""
Playwright Fetch Provider

Fetch web page content using a real browser rendering engine.
"""
from typing import Any, Dict

from ..base import Provider, ProviderConfig
from ...utils.network_safety import blocked_url_target_reason


class PlaywrightFetchProvider(Provider):
    """Browser rendering fetch provider powered by Playwright."""

    @property
    def name(self) -> str:
        return "browser"

    @property
    def display_name(self) -> str:
        return "Playwright Browser Fetch"

    def is_ready(self, config: ProviderConfig) -> bool:
        """
        Browser provider is considered available.

        Runtime dependency checks are performed in execute() so auto mode can
        gracefully fall back when Playwright runtime is not installed.
        """
        return True

    async def execute(self, params: Dict[str, Any], config: ProviderConfig) -> Dict[str, Any]:
        """Execute browser-based web fetch."""
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            raise RuntimeError(
                "Playwright is not available. Install dependency 'playwright' and run "
                "'playwright install' to enable browser mode."
            ) from exc

        url = str(params["url"]).strip()
        timeout_ms = int(params.get("timeout_ms", 15000))
        proxy_url = str(params.get("proxy_url") or "").strip() or None
        allow_rfc2544_benchmark_range = bool(
            params.get("allow_rfc2544_benchmark_range", False)
        )
        allow_private_network = bool(params.get("allow_private_network", False))
        private_network_allowlist = list(params.get("private_network_allowlist") or [])
        wait_until = str(params.get("wait_until", "networkidle")).strip().lower()
        if wait_until not in {"domcontentloaded", "load", "networkidle"}:
            wait_until = "networkidle"

        user_agent = str(
            params.get(
                "user_agent",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
        )

        async with async_playwright() as playwright:
            launch_options: Dict[str, Any] = {"headless": True}
            if proxy_url:
                launch_options["proxy"] = {"server": proxy_url}
            browser = await playwright.chromium.launch(**launch_options)
            try:
                page = await browser.new_page(user_agent=user_agent)

                async def guard_route(route, request):
                    reason = await blocked_url_target_reason(
                        request.url,
                        allow_private_network=allow_private_network,
                        private_network_allowlist=private_network_allowlist,
                        allow_rfc2544_benchmark_range=allow_rfc2544_benchmark_range,
                    )
                    if reason:
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", guard_route)
                response = await page.goto(url, wait_until=wait_until, timeout=max(1, timeout_ms))
                html = await page.content()
                title = await page.title()
                final_url = page.url
                status_code = response.status if response else None
                content_type = ""
                if response:
                    headers = await response.all_headers()
                    content_type = headers.get("content-type", "")
            finally:
                await browser.close()

        return {
            "provider": self.name,
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "content_type": content_type,
            "title": title or "",
            "html": html,
            "rendered": True,
        }
