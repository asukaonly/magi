"""Tests for eval-support service orchestration."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.eval_support.contracts import EvalMemoryQuery, EvalMemoryWriteRecord
from magi.memory.eval_support.namespace import EvalNamespaceManager
from magi.memory.eval_support.service import EvalMemoryService


@pytest.mark.asyncio
async def test_service_replays_and_reads_real_namespace_scoped_memory(tmp_path):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.unified_store import UnifiedMemoryStore, MemoryStoreTuning
    from magi.memory.eval_support.writer import EvalMemoryWriter
    from magi.memory.eval_support.reader import EvalMemoryReader

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        l1_db_path=str(tmp_path / "l1.db"),
        memory_db_path=db_path,
        enable_l0=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
        tuning=MemoryStoreTuning(enable_l1_vectors=False),
    )
    await memory.initialize()
    service = EvalMemoryService(
        namespace_manager=EvalNamespaceManager(),
        writer=EvalMemoryWriter(memory),
        reader=EvalMemoryReader(None, l1_store=memory.l1),
    )
    try:
        namespaces = [
            service.create_namespace(benchmark_name="test", run_id="run-1", question_id=q)
            for q in ["q1", "q2"]
        ]
        for index, namespace in enumerate(namespaces):
            results = await service.write_records(
                namespace=namespace,
                records=[
                    EvalMemoryWriteRecord(
                        namespace=namespace,
                        session_id=f"s{index}",
                        turn_id=f"t{index}",
                        timestamp=float(index + 1),
                        role="user",
                        content=f"unique memory for {namespace}",
                    )
                ],
            )
            rows = await memory.l1.query_events(user_id=namespace)
            assert [row["event_id"] for row in rows] == [results[0]["event_id"]]
        for index, namespace in enumerate(namespaces):
            result = await service.query_memory(
                EvalMemoryQuery(namespace=namespace, query="unique memory", mode="l1_only")
            )
            assert [(hit.session_id, hit.turn_id, hit.content) for hit in result.hits] == [
                (f"s{index}", f"t{index}", f"unique memory for {namespace}")
            ]
            assert service.namespace_manager.is_registered(namespace)
    finally:
        await memory.shutdown()


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
