"""
Tests for the DuckDuckGo web search provider.
"""
from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.web_search.duckduckgo import DuckDuckGoSearchProvider


def test_duckduckgo_provider_is_ready_without_api_key() -> None:
    provider = DuckDuckGoSearchProvider()

    assert provider.is_ready(ProviderConfig()) is True


def test_duckduckgo_normalizes_html_results() -> None:
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

    results = provider._normalize_results(html, num_results=10)

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
