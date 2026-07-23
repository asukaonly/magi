"""Tool application configuration models."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    """Generic provider configuration."""
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)


class WeatherToolSettings(BaseModel):
    """Weather tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="openmeteo")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "openmeteo": ProviderConfig(),
            "qweather": ProviderConfig(),
        }
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class WebSearchToolSettings(BaseModel):
    """Web search tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="duckduckgo")
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "duckduckgo": ProviderConfig(),
            "brave": ProviderConfig(),
            "perplexity": ProviderConfig(),
            "searxng": ProviderConfig(),
            "tavily": ProviderConfig(),
        }
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class WebFetchToolSettings(BaseModel):
    """Web fetch tool configuration."""
    enabled: bool = Field(default=True)
    default_provider: str = Field(default="http")
    allow_rfc2544_benchmark_range: bool = Field(default=True)
    allow_private_network: bool = Field(default=False)
    private_network_allowlist: List[str] = Field(default_factory=list)
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=lambda: {
            "http": ProviderConfig(),
            "browser": ProviderConfig(),
            "curl": ProviderConfig(),
        }
    )

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """Get provider config, returns empty config if not found."""
        return self.providers.get(provider_name, ProviderConfig())


class ToolsSettings(BaseModel):
    """Tools configuration."""
    weather: WeatherToolSettings = Field(default_factory=WeatherToolSettings)
    web_search: WebSearchToolSettings = Field(default_factory=WebSearchToolSettings)
    web_fetch: WebFetchToolSettings = Field(default_factory=WebFetchToolSettings)
    skills: List[str] = Field(default_factory=list)


__all__ = [
    "ProviderConfig",
    "ToolsSettings",
    "WeatherToolSettings",
    "WebFetchToolSettings",
    "WebSearchToolSettings",
]
