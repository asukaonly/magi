from __future__ import annotations

from pathlib import Path

import pytest

import magi.memory as memory_module
from magi.events.events import EventLevel
from magi.memory import UnifiedMemoryStore


@pytest.mark.asyncio
async def test_normalize_event_does_not_infer_calendar_from_event_id_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []

    def _capture_warning(message: str, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        warnings.append(str(message))

    monkeypatch.setattr(memory_module.logger, "warning", _capture_warning)

    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1_events.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memories"),
        l2_batch_flush_interval_seconds=0,
    )

    normalized = store._normalize_event(
        {
            "event_id": "calendar:synthetic",
            "type": "UserMessage",
            "timestamp": 1.0,
            "source": "chat",
            "level": EventLevel.INFO.value,
            "data": {
                "user_id": "u1",
                "session_id": "s1",
                "content": "hello",
            },
            "metadata": {},
        }
    )

    assert normalized.source == "chat"
    assert warnings == []


@pytest.mark.asyncio
async def test_normalize_event_dict_generates_distinct_occurrence_ids_instead_of_storage_ids(
    tmp_path,
):
    import re

    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1_events.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memories"),
        l2_batch_flush_interval_seconds=0,
    )
    events = [
        store._normalize_event(
            {
                "id": storage_id,
                "type": "UserMessage",
                "timestamp": float(storage_id),
                "source": "chat",
                "level": EventLevel.INFO.value,
                "data": {"user_id": "u1", "session_id": "s1", "content": f"message-{storage_id}"},
                "metadata": {},
            }
        )
        for storage_id in (101, 102)
    ]
    ids = [event.event_id for event in events]
    assert len(set(ids)) == 2
    for event_id in ids:
        assert isinstance(event_id, str)
        assert re.fullmatch(r"(?:[0-9A-HJKMNP-TV-Z]{26}|[0-9a-f]{32})", event_id)
