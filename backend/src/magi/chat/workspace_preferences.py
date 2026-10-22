"""Workspace preference port owned by chat, independent of its persistence format."""

from typing import Protocol


class RecentWorkspaceRepository(Protocol):
    async def list_paths(self) -> list[str]: ...
    async def remember(self, path: str) -> list[str]: ...
