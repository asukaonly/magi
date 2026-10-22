"""Projection readers never create schema or reset the clear fence."""

import sqlite3

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.clear_generation import advance_memory_clear_generation
from magi.user_profile.projection_repository import UserProfileProjectionRepository
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository


@pytest.mark.parametrize("repository", [UserProfileProjectionRepository, UserPortraitProjectionRepository])
async def test_unmigrated_projection_read_does_not_create_tables(tmp_path, repository):
    path = tmp_path / "unmigrated.db"
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        await repository(str(path)).get("local_user")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


async def test_missing_clear_fence_is_not_recreated(tmp_path, ensure_db_schema):
    path = tmp_path / "memory.db"
    ensure_db_schema("memory_shared", path)
    async with sqlite_connection_async(path) as db:
        await db.execute("DELETE FROM memory_clear_state")
        await db.commit()
        with pytest.raises(RuntimeError, match="not initialized"):
            await advance_memory_clear_generation(db)
        rows = await db.execute_fetchall("SELECT * FROM memory_clear_state")
        assert rows == []
