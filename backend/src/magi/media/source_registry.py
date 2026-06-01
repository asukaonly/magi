"""Registry of media sources (plugins/domains that contribute reusable assets)."""

from __future__ import annotations

from typing import Iterable, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MediaSource(Protocol):
    """A contributor of time-anchored media assets.

    Implementations describe what kind of source they are (`source_id`,
    e.g. "photo-library", "chat-attachments") and how to enumerate assets
    within a time window. Each asset is a dict that MUST carry at least
    ``ref`` (a stable asset_ref string) and ``timestamp`` (unix seconds).
    Additional metadata (mime_type, dimensions, location, people, etc.) is
    optional and consumed by the selector.
    """

    source_id: str

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        ...


class MediaSourceRegistry:
    """In-memory registry of media sources, populated at bootstrap.

    The registry is intentionally tiny in Plan 1: registration and
    fan-out enumeration. Selection logic lives in MediaSelector.
    """

    def __init__(self) -> None:
        self._sources: dict[str, MediaSource] = {}

    def register(self, source: MediaSource) -> None:
        source_id = getattr(source, "source_id", "") or ""
        if not source_id:
            raise ValueError("MediaSource.source_id must be a non-empty string")
        if source_id in self._sources:
            raise ValueError(f"MediaSource already registered: {source_id}")
        self._sources[source_id] = source

    def get(self, source_id: str) -> Optional[MediaSource]:
        return self._sources.get(source_id)

    def iter_sources(self) -> Iterable[MediaSource]:
        return list(self._sources.values())

    async def collect_assets(self, *, start: float, end: float) -> List[dict]:
        """Fan out to every registered source and concatenate their assets."""
        out: list[dict] = []
        for src in self._sources.values():
            try:
                items = await src.list_assets(start=start, end=end)
            except Exception:
                # Plan 2 will add structured error reporting; for now skip the source.
                continue
            out.extend(items or [])
        return out
