"""Smoke test for the knowledge_graph evidence_class backfill script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import aiosqlite
import pytest

# The backfill script lives in backend/scripts/ which is not a Python package
# (no __init__.py, not in setuptools.packages.find). Load it directly from
# the file system so this test is hermetic and doesn't depend on packaging.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "backfill_kg_evidence_class.py"
)
_SPEC = importlib.util.spec_from_file_location("backfill_kg_evidence_class", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules["backfill_kg_evidence_class"] = _MODULE
_SPEC.loader.exec_module(_MODULE)
backfill = _MODULE.backfill


@pytest.mark.asyncio
async def test_backfill_picks_highest_authority(tmp_path: Path):
    mem_db = tmp_path / "mem.sqlite"
    l1_db = tmp_path / "l1.sqlite"

    async with aiosqlite.connect(mem_db) as db:
        await db.execute(
            "CREATE TABLE knowledge_graph ("
            "triple_id TEXT PRIMARY KEY, "
            "evidence_event_ids TEXT, "
            "evidence_class TEXT)"
        )
        await db.execute(
            "INSERT INTO knowledge_graph VALUES ('t1', '[\"e1\",\"e2\"]', NULL)"
        )
        await db.commit()

    async with aiosqlite.connect(l1_db) as db:
        await db.execute(
            "CREATE TABLE fact_events (event_id TEXT PRIMARY KEY, evidence_class INTEGER)"
        )
        # e1 = external_observation (8), e2 = user_self_report (2)
        # user_self_report wins on authority despite lower enum int.
        await db.executemany(
            "INSERT INTO fact_events VALUES (?, ?)", [("e1", 8), ("e2", 2)]
        )
        await db.commit()

    await backfill(mem_db, l1_db)

    async with aiosqlite.connect(mem_db) as db:
        async with db.execute(
            "SELECT evidence_class FROM knowledge_graph WHERE triple_id='t1'"
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == "user_self_report"
