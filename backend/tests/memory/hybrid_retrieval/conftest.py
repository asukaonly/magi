"""Shared fixtures for hybrid_retrieval memory tests."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.evidence import EvidenceClass
from magi.memory.l2.store import L2CognitionStore


@pytest_asyncio.fixture
async def seeded_l2_store(tmp_path: Path) -> L2CognitionStore:
    """L2 store seeded with the production-bug scenario:
    many EXTERNAL_OBSERVATION INTERESTED_IN edges (Chrome history) plus
    one USER_SELF_REPORT LIKES edge (user's declared name preference).
    """
    db_path = tmp_path / "l2.sqlite"
    await apply_memory_shared_schema(str(db_path))
    store = L2CognitionStore(db_path=str(db_path))
    await store.initialize()
    now = time.time()

    # Many EXTERNAL_OBSERVATION INTERESTED_IN edges (Chrome history)
    for org_id in ("74f953b57f75", "cbff460f1cac", "abc123def456"):
        await store.upsert_knowledge_edge(
            subject_id="user:local_user",
            subject_type="person",
            predicate="INTERESTED_IN",
            object_id=f"organization:{org_id}",
            object_type="organization",
            evidence_event_ids=[f"evt_{uuid.uuid4().hex[:12]}"],
            confidence=0.99,
            observed_at=now - 3 * 86400,
            source_type="chrome_history",
            evidence_class=EvidenceClass.EXTERNAL_OBSERVATION.label,
        )

    # One USER_SELF_REPORT LIKES edge ("叫我子涵或者哈基米" projected as preference)
    await store.upsert_knowledge_edge(
        subject_id="user:local_user",
        subject_type="person",
        predicate="LIKES",
        object_id="preference:address_form:子涵",
        object_type="preference_value",
        evidence_event_ids=[f"evt_{uuid.uuid4().hex[:12]}"],
        confidence=1.0,
        observed_at=now - 4 * 86400,
        source_type="conversation",
        evidence_class=EvidenceClass.USER_SELF_REPORT.label,
    )
    return store


@pytest_asyncio.fixture
async def historical_memory(tmp_path):
    from types import SimpleNamespace
    from magi.events.events import Event, EventTypes
    from magi.memory.event_contracts import normalize_runtime_event
    from magi.memory.l1.event_store import L1EventStore

    l1 = L1EventStore(db_path=str(tmp_path / "l1.db"), vector_enabled=False)
    l2 = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await l2.initialize()
    for event_id, content, source, event_type, timestamp in [
        ("old-name", "Please call me codename.", "chat", EventTypes.USER_MESSAGE, 1600000000.0),
        (
            "new-weather",
            "Today the weather is sunny.",
            "chat",
            EventTypes.USER_MESSAGE,
            1700000100.0,
        ),
        (
            "external-name",
            "Please call me codename.",
            "chrome_history",
            "SourceActivity",
            1600000000.0,
        ),
    ]:
        await l1.store(
            normalize_runtime_event(
                Event(
                    type=event_type,
                    event_id=event_id,
                    source=source,
                    timestamp=timestamp,
                    data={
                        "content": content,
                        "author_type": "user" if source == "chat" else "external",
                        "content_type": "text",
                        "user_id": "u1",
                        "session_id": "history",
                    },
                )
            )
        )
    assert {row[0] for row in await l1.bm25_search("codename", limit=10)} == {
        "old-name",
        "external-name",
    }
    try:
        yield SimpleNamespace(l0=None, l1=l1, l2=l2, l2_entity_catalog=None, l3=None, l4=None)
    finally:
        await l1.shutdown()
