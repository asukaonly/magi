"""Shared protocol for L2 cognition retrieval mixins."""

from __future__ import annotations

from typing import Any, Dict, Protocol

import aiosqlite


class L2RetrievalQueryHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _assertion_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]: ...
