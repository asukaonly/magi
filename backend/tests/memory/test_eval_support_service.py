"""Tests for eval-support service orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryQueryResult, EvalMemoryWriteRecord
from magi.memory.eval_support.namespace import EvalNamespaceManager
from magi.memory.eval_support.service import EvalMemoryService


@pytest.mark.asyncio
async def test_service_creates_namespace_replays_records_and_queries_memory() -> None:
    writer = AsyncMock()
    writer.write_records = AsyncMock(return_value=[{"event_id": "evt-1"}])
    reader = AsyncMock()
    reader.query_memory = AsyncMock(return_value=EvalMemoryQueryResult())
    manager = EvalNamespaceManager(cleaner=AsyncMock(return_value=0))
    service = EvalMemoryService(namespace_manager=manager, writer=writer, reader=reader)

    namespace = service.create_namespace(
        benchmark_name="longmemeval",
        run_id="run-1",
        question_id="q-1",
    )
    records = [
        EvalMemoryWriteRecord(
            namespace=namespace,
            session_id="session-1",
            turn_id="turn-1",
            timestamp=1.0,
            role="user",
            content="hello",
        )
    ]

    await service.write_records(namespace=namespace, records=records)
    await service.query_memory(
        EvalMemoryQuery(
            namespace=namespace,
            query="What did I say?",
            query_timestamp=2.0,
        )
    )

    writer.write_records.assert_awaited_once_with(records)
    reader.query_memory.assert_awaited_once()
    assert manager.is_registered(namespace) is True


@pytest.mark.asyncio
async def test_service_reset_namespace_only_clears_requested_scope() -> None:
    cleaned: list[str] = []

    async def _clean(namespace: str) -> int:
        cleaned.append(namespace)
        return 2

    service = EvalMemoryService(
        namespace_manager=EvalNamespaceManager(cleaner=_clean),
        writer=AsyncMock(),
        reader=AsyncMock(),
    )

    namespace_one = service.create_namespace(
        benchmark_name="longmemeval",
        run_id="run-1",
        question_id="q-1",
    )
    namespace_two = service.create_namespace(
        benchmark_name="longmemeval",
        run_id="run-1",
        question_id="q-2",
    )

    removed = await service.reset_namespace(namespace_one)

    assert removed == 2
    assert cleaned == [namespace_one]
    assert service.namespace_manager.is_registered(namespace_one) is False
    assert service.namespace_manager.is_registered(namespace_two) is True
