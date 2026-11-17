"""Reflection input obeys memory ownership, correction and forgetting rules."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from magi.core.sqlite import sqlite_connection_async
from magi.memory.reflection_evidence import ReflectionEvidenceReader


async def test_evidence_reader_excludes_other_users_and_governed_records(tmp_path, ensure_db_schema):
    path = tmp_path / "memory.db"
    ensure_db_schema("memory_shared", path)
    base = dict(user_id="u1", cognition_eligible=True, content="A source", deleted_at=None,
                memory_domain="user_authored", source="chat", timestamp=1, author_type="user")
    events = [dict(base, event_id="ok"), dict(base, event_id="other", user_id="u2"),
              dict(base, event_id="disabled", cognition_eligible=False),
              dict(base, event_id="deleted", deleted_at=2),
              dict(base, event_id="trace", memory_domain="runtime_telemetry")]
    l1 = SimpleNamespace(query_events=AsyncMock(return_value=events),
                         get_user_visible_event=AsyncMock(side_effect=lambda identity: next((e for e in events if e["event_id"] == identity), None)))
    reader = ReflectionEvidenceReader(SimpleNamespace(l1=l1, memory_db_path=str(path)))
    assert [row["event_id"] for row in await reader.recent("u1")] == ["ok"]
    assert await reader.current("u1", ["other", "disabled", "deleted"]) == []
    revision = await reader.governance_revision()
    async with sqlite_connection_async(path) as db:
        await db.execute("INSERT INTO memory_subject_revisions VALUES ('subject',1,1)")
        await db.commit()
    assert await reader.governance_revision() != revision


async def test_watch_scan_uses_capture_cursor_and_governed_reads(tmp_path, ensure_db_schema):
    memory_path = tmp_path / "memory.db"
    l1_path = tmp_path / "l1.db"
    ensure_db_schema("memory_shared", memory_path)
    async with sqlite_connection_async(l1_path) as db:
        await db.execute("CREATE TABLE fact_events(event_id TEXT,user_id TEXT,source TEXT,created_at REAL,deleted_at REAL,cognition_eligible INTEGER)")
        await db.executemany("INSERT INTO fact_events VALUES (?,'u1','notes',2,NULL,1)", [(f"e{index:02}",) for index in range(26)])
        await db.execute("INSERT INTO fact_events VALUES ('other','u2','private',3,NULL,1)")
        await db.commit()
    events = {f"e{index:02}": dict(event_id=f"e{index:02}", user_id="u1", source="notes", author_type="user", content="Late imported material", timestamp=0,
                                  cognition_eligible=index != 0, memory_domain="user_authored", deleted_at=None) for index in range(26)}
    l1 = SimpleNamespace(get_user_visible_event=AsyncMock(side_effect=lambda key: events.get(key)))
    reader = ReflectionEvidenceReader(SimpleNamespace(l1=l1, l1_db_path=str(l1_path), memory_db_path=str(memory_path)))
    assert await reader.watch_sources("u1") == ["notes"]
    first, cursor, last = await reader.watch_changes("u1", ["notes"], 1, "")
    assert len(first) == 23 and last == "e23"
    second, cursor, last = await reader.watch_changes("u1", ["notes"], cursor, last)
    assert [row["event_id"] for row in second] == ["e24", "e25"]
    assert await reader.watch_changes("u1", ["notes"], cursor, last) == ([], cursor, last)
