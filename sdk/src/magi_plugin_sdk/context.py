"""Host-provided paths and credential access for one plugin connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .runtime import PluginConnection


class PluginCredentials(Protocol):
    """A connection-scoped credential port; implementations never accept an owner."""

    def get(self, key: str) -> str | None:
        """Read one credential belonging to this connection."""
        ...

    def set(self, key: str, value: str) -> None:
        """Store one credential belonging to this connection."""
        ...

    def delete(self, key: str) -> None:
        """Remove one credential belonging to this connection, if present."""
        ...


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Explicit host binding; no path is inferred from a package or home directory.

    ``state_dir`` holds private account state and source progress. Content and
    regenerable artifacts belong in ``resources_dir`` so a product content clear
    can remove them while retaining account configuration and credentials.
    """

    connection: PluginConnection
    state_dir: Path
    resources_dir: Path
    credentials: PluginCredentials

    def __post_init__(self) -> None:
        if not self.state_dir.is_absolute() or not self.resources_dir.is_absolute():
            raise ValueError("Plugin context paths must be absolute host-owned paths")
        if self.state_dir == self.resources_dir:
            raise ValueError("Plugin state and resource directories must be distinct")


__all__ = ["PluginContext", "PluginCredentials"]
