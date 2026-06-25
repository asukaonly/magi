from __future__ import annotations

import pytest

from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore


@pytest.mark.asyncio
async def test_l4_records_and_returns_task_preferences(tmp_path) -> None:
    store = L4ProceduralMemoryStore(
        db_path=str(tmp_path / "memory.db"),
        vector_enabled=False,
    )
    await store.initialize()

    skill_id = await store.record_task_preference(
        user_id="u1",
        persona_id="seven",
        task_category="coding",
        preference="改代码前先讲完成标准",
        polarity="prefer",
        evidence_text="以后改代码前先讲完成标准。",
        confidence=0.9,
        turn_id="turn-1",
        session_id="session-1",
    )

    preferences = await store.get_task_preferences(
        user_id="u1",
        task_category="coding",
        limit=4,
    )

    assert skill_id
    assert preferences == [
        {
            "skill_id": skill_id,
            "skill_name": "coding:prefer:改代码前先讲完成标准",
            "skill_category": "task_preference",
            "skill_type": "task_preference",
            "summary": "Prefer: 改代码前先讲完成标准",
            "content": "Prefer: 改代码前先讲完成标准\nEvidence: 以后改代码前先讲完成标准。",
            "polarity": "prefer",
            "task_category": "coding",
            "preference": "改代码前先讲完成标准",
            "confidence": 0.9,
            "source_event_ids": ["turn-1"],
        }
    ]
