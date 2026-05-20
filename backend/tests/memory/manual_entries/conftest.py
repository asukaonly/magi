"""Shared fixtures for manual_entries tests."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def manual_entry_db(tmp_path) -> str:
    """tmp_path-backed DB with all memory_shared migrations applied."""
    db_path = str(tmp_path / "manual.db")
    await apply_memory_shared_schema(db_path)
    return db_path
