"""
Tests for the DuckDuckGo web search provider.
"""
import pytest

from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.web_search.duckduckgo import DuckDuckGoSearchProvider


@pytest.mark.asyncio
async def test_keyless_search_request_returns_normalized_html_results(monkeypatch) -> None:
    provider = DuckDuckGoSearchProvider()
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">
            Example Docs
          </a>
          <a class="result__snippet">
            Canonical reference documentation
          </a>
        </div>
        <div class="result">
          <a class="result__a" href="https://example.org/blog">Example Blog</a>
          <div class="result__snippet">Notes and updates</div>
        </div>
      </body>
    </html>
    """

    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from magi.tools.providers.web_search import duckduckgo

    requests = []

    async def text():
        return html

    @asynccontextmanager
    async def post(url, **kwargs):
        requests.append((url, kwargs))
        yield SimpleNamespace(status=200, text=text)

    @asynccontextmanager
    async def session(*, trust_env):
        assert trust_env is False
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(duckduckgo.aiohttp, "ClientSession", session)
    config = ProviderConfig()
    assert provider.is_ready(config)
    response = await provider.execute({"query": "reference docs", "num_results": 10}, config)
    assert response["provider"] == "duckduckgo" and response["total"] == 2
    assert len(requests) == 1
    url, request = requests[0]
    assert url == "https://html.duckduckgo.com/html/"
    assert request["data"] == {"q": "reference docs"}
    assert request["proxy"] is None
    assert "Authorization" not in request["headers"]
    results = response["results"]

    assert results == [
        {
            "title": "Example Docs",
            "url": "https://example.com/docs",
            "description": "Canonical reference documentation",
            "source": "duckduckgo",
        },
        {
            "title": "Example Blog",
            "url": "https://example.org/blog",
            "description": "Notes and updates",
            "source": "duckduckgo",
        },
    ]


@pytest.mark.parametrize(
    "status,html,expected",
    [
        (202, '<form id="challenge-form"></form>', True),
        (403, "Bots use DuckDuckGo too", True),
        (429, '<script src="/anomaly.js"></script>', True),
        (200, '<form id="challenge-form"></form>', False),
        (202, "ordinary search response", False),
        (200, "ordinary search response", False),
    ],
)
def test_challenge_detection_requires_status_and_body_evidence(status, html, expected):
    assert DuckDuckGoSearchProvider()._is_challenge_response(status, html) is expected
