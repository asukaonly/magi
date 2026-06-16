"""
DuckDuckGo Search Provider

Search the web using DuckDuckGo's HTML endpoint.
"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp

from ..base import Provider, ProviderConfig


class _DuckDuckGoResultsParser(HTMLParser):
    """Parse DuckDuckGo HTML search results into a normalized structure."""

    def __init__(self) -> None:
        super().__init__()
        self.results: List[Dict[str, str]] = []
        self._current: Optional[Dict[str, str]] = None
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: List[str] = []
        self._snippet_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attr_map = dict(attrs)
        class_name = attr_map.get("class", "") or ""
        href = attr_map.get("href", "") or ""

        if tag == "a" and ("result__a" in class_name or "result-link" in class_name):
            self._flush_current()
            self._current = {
                "title": "",
                "url": self._normalize_url(href),
                "description": "",
                "source": "duckduckgo",
            }
            self._capture_title = True
            self._title_parts = []
            return

        if self._current and tag in {"a", "div", "td", "span"}:
            if "result__snippet" in class_name or "result-snippet" in class_name:
                self._capture_snippet = True
                self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title and self._current:
            self._current["title"] = self._join_parts(self._title_parts)
            self._capture_title = False
            self._title_parts = []
            return

        if tag in {"a", "div", "td", "span"} and self._capture_snippet and self._current:
            self._current["description"] = self._join_parts(self._snippet_parts)
            self._capture_snippet = False
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        elif self._capture_snippet:
            self._snippet_parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush_current()

    def _flush_current(self) -> None:
        if not self._current:
            return

        title = self._current.get("title", "").strip()
        url = self._current.get("url", "").strip()
        if title and url:
            self.results.append(self._current)
        self._current = None
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts = []
        self._snippet_parts = []

    @staticmethod
    def _join_parts(parts: List[str]) -> str:
        return " ".join(part.strip() for part in parts if part.strip())

    @staticmethod
    def _normalize_url(url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            url = f"https:{url}"
        parsed = urlparse(url)
        if "duckduckgo.com" not in parsed.netloc:
            return url

        uddg = parse_qs(parsed.query).get("uddg")
        if not uddg:
            return url
        return unquote(uddg[0])


class DuckDuckGoSearchProvider(Provider):
    """DuckDuckGo HTML search provider."""

    @property
    def name(self) -> str:
        return "duckduckgo"

    @property
    def display_name(self) -> str:
        return "DuckDuckGo"

    def is_ready(self, config: ProviderConfig) -> bool:
        """DuckDuckGo search does not require credentials."""
        _ = config
        return True

    async def execute(
        self,
        params: Dict[str, Any],
        config: ProviderConfig,
    ) -> Dict[str, Any]:
        """Execute DuckDuckGo HTML search."""
        query = params["query"]
        num_results = params.get("num_results", 10)
        proxy_url = str(params.get("proxy_url") or "").strip() or None
        url = config.base_url or "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Magi/1.0 (+https://github.com/asukaonly/magi)",
            "Accept": "text/html,application/xhtml+xml",
        }

        async with aiohttp.ClientSession(trust_env=False) as session:
            async with session.post(url, data={"q": query}, headers=headers, proxy=proxy_url) as response:
                html = await response.text()
                if response.status != 200:
                    if self._is_challenge_response(response.status, html):
                        raise Exception(
                            "DuckDuckGo search challenge triggered. The provider returned an anti-bot verification page instead of search results."
                        )
                    raise Exception(f"DuckDuckGo API error: {response.status} - {html}")

        results = self._normalize_results(html, num_results)
        return {
            "results": results,
            "provider": self.name,
            "total": len(results),
        }

    def get_config_schema(self) -> Dict[str, Any]:
        """DuckDuckGo only supports an optional endpoint override."""
        return {
            "base_url": {
                "type": "string",
                "description": "DuckDuckGo HTML endpoint override (optional)",
                "required": False,
            }
        }

    def _normalize_results(self, html: str, num_results: int) -> List[Dict[str, str]]:
        parser = _DuckDuckGoResultsParser()
        parser.feed(html)
        parser.close()
        return parser.results[:num_results]

    def _is_challenge_response(self, status_code: int, html: str) -> bool:
        if status_code not in {202, 403, 429}:
            return False
        lowered = html.lower()
        return any(
            marker in lowered
            for marker in [
                "anomaly.js",
                "bots use duckduckgo too",
                "confirm this search was made by a human",
                "challenge-form",
                "select all squares containing a duck",
            ]
        )
