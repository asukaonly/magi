from __future__ import annotations

import time
from pathlib import Path

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _make_memory_event(*, event_id: str, content: str = "visited page"):
    timestamp = time.time()
    return normalize_runtime_event(
        Event(
            type=EventTypes.USER_MESSAGE,
            data={
                "user_id": None,
                "session_id": None,
                "content": content,
                "author_type": "user",
                "content_type": "text",
            },
            source="chrome_history",
            level=EventLevel.INFO,
            correlation_id=f"corr-{event_id}",
            timestamp=timestamp,
        event_id=event_id),
        )


@pytest.mark.asyncio
async def test_projection_rows_prefer_effective_batch_owner_over_metadata_json(tmp_path: Path):
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    from magi.memory.l2.llm_service import L2LLMService
    from magi.memory.l2.pipeline import L2Pipeline
    from magi.memory.l2.store import L2CognitionStore

    memory_db = str(tmp_path / "memory.db")
    l1_db = str(tmp_path / "l1.db")
    cognition_store = L2CognitionStore(db_path=memory_db)
    await cognition_store.initialize()
    entity_catalog = L2EntityCatalog(db_path=memory_db)
    await entity_catalog.initialize()
    l1_store = L1EventStore(db_path=l1_db, vector_enabled=False)
    await l1_store.initialize()

    event = _make_memory_event(event_id="evt-chrome-1")
    event.metadata_json = {
        "l2_batch_owner": "chrome_history:Default:github.com",
        "l2_batch_max_events": 20,
    }
    await l1_store.store(event)

    pipeline = L2Pipeline(
        cognition_store,
        l1_store=l1_store,
        entity_catalog=entity_catalog,
        llm_service=L2LLMService(None),
    )
    jobs, missing_event_ids = await pipeline._build_extract_jobs_from_projection_rows(
        [
            {
                "event_id": "evt-chrome-1",
                "lease_token": "lease-owner-override",
                "attempt_count": 1,
                "batch_owner": "chrome_history:Default:github.com",
                "effective_batch_owner": "chrome_history:Default:catchup:2",
            }
        ]
    )

    assert missing_event_ids == []
    assert len(jobs) == 1
    assert jobs[0].bucket_key == "owner:chrome_history:Default:catchup:2"
    assert jobs[0].event_ids == ["evt-chrome-1"]
