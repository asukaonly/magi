"""Ports used by reference research without coupling it to web tools."""

from __future__ import annotations

from typing import Any, Protocol


class ReferenceSearchPort(Protocol):
    """Discover public source candidates for one query."""

    async def search(self, query: str, *, limit: int = 6) -> list[dict[str, Any]]:
        """Return normalized search result dictionaries."""


class ReferenceFetchPort(Protocol):
    """Fetch readable content from a public URL."""

    async def fetch(self, url: str, *, max_chars: int = 12000) -> dict[str, Any]:
        """Return normalized page content and metadata."""


__all__ = ["ReferenceFetchPort", "ReferenceSearchPort"]
