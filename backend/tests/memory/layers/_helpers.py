from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from magi.memory.event_contracts import (
    IngestTarget,
    MemoryDomain,
    MemoryEvent,
    RetentionClass,
    TomDepth,
)


def make_event(
    *,
    event_id: str = "evt_1",
    event_type: str = "USER_MESSAGE",
    ingest_target: IngestTarget = IngestTarget.L0_AND_L1,
    cognition_eligible: bool = True,
    metadata: dict[str, Any] | None = None,
    source: str = "chat",
    idempotency_key: str | None = "idem-1",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        correlation_id="cor_1",
        timestamp=1.0,
        created_at=1.0,
        event_type=event_type,
        source=source,
        source_item_id=None,
        memory_domain=MemoryDomain.INTERACTION,
        ingest_target=ingest_target,
        cognition_eligible=cognition_eligible,
        tom_depth=TomDepth.NONE,
        retention_class=RetentionClass.DISPOSABLE,
        session_id="sess",
        turn_id=None,
        user_id="user",
        task_id=None,
        content="hi",
        author_type="user",
        content_type="text",
        importance_score=0.5,
        level=20,
        idempotency_key=idempotency_key,
        metadata_json=metadata,
    )


def make_async_mock(**kwargs: Any) -> Any:
    mock = AsyncMock()
    for key, value in kwargs.items():
        getattr(mock, key).return_value = value
    return mock
