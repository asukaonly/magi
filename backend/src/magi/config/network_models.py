"""Network application configuration models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ProxyType(str, Enum):
    """Supported network proxy types."""
    HTTP = "http"
    SOCKS5 = "socks5"


class NetworkProxySettings(BaseModel):
    """Network proxy configuration.

    When ``enabled`` is False (the default), the application ignores system
    proxy settings and connects directly.  When enabled, all outbound LLM
    requests are routed through the configured proxy.
    """

    enabled: bool = Field(default=False)
    proxy_type: ProxyType = Field(default=ProxyType.HTTP)
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=7890, ge=1, le=65535)

    def proxy_url(self) -> str | None:
        """Build proxy URL string, or ``None`` when disabled."""
        if not self.enabled:
            return None
        scheme = "socks5" if self.proxy_type == ProxyType.SOCKS5 else "http"
        return f"{scheme}://{self.host}:{self.port}"


__all__ = ["NetworkProxySettings", "ProxyType"]