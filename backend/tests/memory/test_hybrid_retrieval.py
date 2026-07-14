from __future__ import annotations

import pytest

from magi.events.events import Event, EventLevel, EventTypes
from magi.i18n import language_context


@pytest.mark.asyncio
async def test_detail_mode_prefers_l0_and_l1(tmp_path):
    from magi.memory import UnifiedMemoryStore
    from magi.memory.hybrid_retrieval.models import RetrievalQuery
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService

    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1_events.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memories"),
    )
    await store.initialize()
    try:
        await store.add_event(
            Event(
                type="WORKER_AGENT_PROGRESS",
                data={"user_id": "u1", "session_id": "s1", "content": "thinking"},
                source="worker",
                level=EventLevel.INFO,
                correlation_id="corr-1",
            )
        )
        await store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I feel stressed about work."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="corr-2",
            )
        )

        service = HybridRetrievalService(store)
        payload = await service.query(
            RetrievalQuery(
                query="stressed work",
                user_id="u1",
                session_id="s1",
                time_range={},
                query_mode="detail",
                source_filters=[],
                domain_filters=[],
                limit=5,
            )
        )

        assert payload.l0_workbench
        assert len(payload.l1_events) == 1
        assert payload.l1_events[0]["memory_domain"] == "user_authored"
    finally:
        await store.shutdown()


@pytest.mark.asyncio
async def test_summary_and_experience_modes_hit_l3_and_l4(tmp_path):
    from magi.memory import UnifiedMemoryStore
    from magi.memory.hybrid_retrieval.models import RetrievalQuery
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService

    store = UnifiedMemoryStore(
        l1_db_path=str(tmp_path / "l1_events.db"),
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memories"),
    )
    await store.initialize()
    try:
        await store.add_event(
            Event(
                type=EventTypes.USER_MESSAGE,
                data={"user_id": "u1", "session_id": "s1", "content": "I want to switch jobs this year."},
                source="chat",
                level=EventLevel.INFO,
                correlation_id="evt-1",
                timestamp=1710000000.0,
            )
        )
        await store.add_event(
            Event(
                type=EventTypes.ACTION_EXECUTED,
                data={
                    "user_id": "u1",
                    "session_id": "s1",
                    "action_type": "browser.open",
                    "params": {"url": "https://example.com"},
                    "success": True,
                    "execution_time": 0.4,
                },
                source="worker",
                level=EventLevel.INFO,
                correlation_id="evt-2",
                timestamp=1710000600.0,
            )
        )
        with language_context("en"):
            await store.generate_summary(
                period_type="day",
                period_start=1709990000.0,
                period_end=1710003600.0,
            )

        service = HybridRetrievalService(store)
        summary_payload = await service.query(
            RetrievalQuery(
                query="switch jobs",
                user_id="u1",
                session_id="s1",
                time_range={},
                query_mode="summary",
                source_filters=[],
                domain_filters=[],
                limit=5,
            )
        )
        experience_payload = await service.query(
            RetrievalQuery(
                query="browser",
                user_id="u1",
                session_id="s1",
                time_range={},
                query_mode="experience",
                source_filters=[],
                domain_filters=[],
                limit=5,
            )
        )

        assert summary_payload.l3_reflections
        assert experience_payload.l4_procedures
    finally:
        await store.shutdown()
