"""L1 pinned-payload satellite store (RFC #56 P3).

A sparse auxiliary table of fact_events: a row exists only when a source pinned
the capture-time full text for an event (obsidian note body, git commit text).
L1.content stays a lean summary; L2 reads the full body from here at extraction.
"""
from __future__ import annotations

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi.memory.l1.event_payload_store import L1EventPayloadStore
from magi.memory.l1.event_store import L1EventStore


def _event(event_id: str, *, content: str, pinned: str | None = None):
    me = normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": "user-1",
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            source="obsidian_vault",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            event_id=event_id,
        )
    )
    me.pinned_payload = pinned
    return me


async def _db_with_schema(tmp_path) -> str:
    """Materialize the canonical L1 schema (alembic-owned) for an isolated db."""
    db = str(tmp_path / "l1.db")
    store = L1EventStore(db_path=db, vector_enabled=False)
    await store.initialize()
    return db


async def test_put_then_get_returns_pinned_content(tmp_path) -> None:
    db = await _db_with_schema(tmp_path)
    payloads = L1EventPayloadStore(db_path=db)
    await payloads.put("evt-1", "the full note body")
    assert await payloads.get("evt-1") == "the full note body"


async def test_get_missing_event_returns_none(tmp_path) -> None:
    db = await _db_with_schema(tmp_path)
    payloads = L1EventPayloadStore(db_path=db)
    assert await payloads.get("no-such-event") is None


async def test_put_overwrites_existing_payload(tmp_path) -> None:
    db = await _db_with_schema(tmp_path)
    payloads = L1EventPayloadStore(db_path=db)
    await payloads.put("evt-1", "v1")
    await payloads.put("evt-1", "v2")
    assert await payloads.get("evt-1") == "v2"


async def test_store_persists_pinned_payload_to_satellite_keeping_row_lean(tmp_path) -> None:
    db = str(tmp_path / "l1.db")
    store = L1EventStore(db_path=db, vector_enabled=False)
    await store.initialize()
    full = "the full frozen note body, much longer than the lean summary"
    await store.store(_event("evt-pinned-1", content="lean one-line summary", pinned=full))

    # full body landed in the satellite...
    assert await L1EventPayloadStore(db_path=db).get("evt-pinned-1") == full
    # ...while the persisted row stays lean (content = summary, no leak into JSON)
    stored = await store.get_event("evt-pinned-1")
    assert stored is not None
    assert stored["content"] == "lean one-line summary"
    assert "frozen note body" not in str(stored.get("metadata_json") or "")


async def test_store_without_pinned_payload_writes_no_satellite_row(tmp_path) -> None:
    db = str(tmp_path / "l1.db")
    store = L1EventStore(db_path=db, vector_enabled=False)
    await store.initialize()
    await store.store(_event("evt-plain-1", content="just a summary", pinned=None))
    # sparse: no extra info -> no satellite row
    assert await L1EventPayloadStore(db_path=db).get("evt-plain-1") is None


async def test_get_pinned_payloads_batch_returns_only_pinned_events(tmp_path) -> None:
    db = str(tmp_path / "l1.db")
    store = L1EventStore(db_path=db, vector_enabled=False)
    await store.initialize()
    await store.store(_event("evt-a", content="summary A", pinned="FULL A"))
    await store.store(_event("evt-b", content="summary B", pinned=None))
    result = await store.get_pinned_payloads(["evt-a", "evt-b", "evt-missing"])
    assert result == {"evt-a": "FULL A"}  # sparse: only events with a pinned body


async def test_prune_stale_drops_old_keeps_recent(tmp_path) -> None:
    db = await _db_with_schema(tmp_path)
    payloads = L1EventPayloadStore(db_path=db)
    await payloads.put("old", "old body", now=1_000.0)
    await payloads.put("new", "new body", now=10_000.0)
    deleted = await payloads.prune_stale(retention_seconds=5_000, now=10_000.0)
    assert deleted == 1
    assert await payloads.get("old") is None
    assert await payloads.get("new") == "new body"


async def test_store_prune_pinned_payloads_delegates_with_retention(tmp_path) -> None:
    db = str(tmp_path / "l1.db")
    store = L1EventStore(db_path=db, vector_enabled=False)
    await store.initialize()
    payloads = L1EventPayloadStore(db_path=db)
    await payloads.put("old", "old body", now=1_000.0)
    await payloads.put("new", "new body", now=10_000.0)
    deleted = await store.prune_pinned_payloads(retention_seconds=5_000, now=10_000.0)
    assert deleted == 1
    assert await payloads.get("old") is None
    assert await payloads.get("new") == "new body"
