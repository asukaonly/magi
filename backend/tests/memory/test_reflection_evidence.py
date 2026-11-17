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
