from magi.tools.providers.base import ProviderConfig
from magi.tools.providers.web_search.searxng import SearXNGSearchProvider


def test_searxng_provider_requires_base_url() -> None:
    provider = SearXNGSearchProvider()

    assert provider.is_ready(ProviderConfig()) is False
    assert provider.is_ready(ProviderConfig(base_url="https://search.example.com")) is True


def test_searxng_normalizes_json_results() -> None:
    provider = SearXNGSearchProvider()

    results = provider._normalize_results(
        {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Snippet",
                    "engine": "duckduckgo",
                },
                {"title": "", "url": "https://skip.example.com"},
            ]
        },
        num_results=5,
    )

    assert results == [
        {
            "title": "Example",
            "url": "https://example.com",
            "description": "Snippet",
            "source": "duckduckgo",
        }
    ]
