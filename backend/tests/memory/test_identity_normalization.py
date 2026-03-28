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
