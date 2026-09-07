"""Typed source push services bound to one host-issued watch subscription."""

from __future__ import annotations

from typing import Protocol

from .runtime import ResourceRef, SourceChange


class SourceEmitter(Protocol):
    """The host chooses connection and source; authors only supply content."""

    async def emit(self, change: SourceChange) -> None:
        """Submit a versioned change through the normal source ingestion path."""
        ...

    async def create_resource(
        self, content: bytes, *, media_type: str, display_name: str = ""
    ) -> ResourceRef:
        """Store bounded content owned by this connection."""
        ...

    async def read_resource(self, reference: ResourceRef) -> bytes:
        """Read an existing resource belonging to this connection."""
        ...
