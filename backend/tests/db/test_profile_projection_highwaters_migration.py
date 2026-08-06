from __future__ import annotations

import sqlite3

import pytest

from _shared.memory_schema import apply_memory_shared_schema


@pytest.mark.asyncio
async def test_fresh_schema_contains_projection_input_highwaters(tmp_path):
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)

    with sqlite3.connect(db_path) as db:
        profile_columns = {
            str(row[1])
            for row in db.execute("PRAGMA table_info(user_profile_projection)")
        }
        portrait_columns = {
            str(row[1])
            for row in db.execute("PRAGMA table_info(user_portrait_projection)")
        }

    assert "input_assertion_highwater" in profile_columns
    assert {
        "input_assertion_highwater",
        "input_claim_highwater",
        "input_review_highwater",
        "input_profile_highwater",
    }.issubset(portrait_columns)
