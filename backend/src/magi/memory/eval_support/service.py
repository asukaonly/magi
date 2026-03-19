"""Thin orchestration layer for benchmark-facing memory evaluation support."""

from __future__ import annotations

from .contracts import EvalMemoryQuery, EvalMemoryQueryResult, EvalMemoryWriteRecord
from .namespace import EvalNamespaceManager


class EvalMemoryService:
    """Coordinate namespace management, replay writes, and memory reads."""

    def __init__(self, *, namespace_manager: EvalNamespaceManager, writer, reader) -> None:
        self.namespace_manager = namespace_manager
        self.writer = writer
        self.reader = reader

    def create_namespace(self, *, benchmark_name: str, run_id: str, question_id: str) -> str:
        return self.namespace_manager.create_namespace(
            benchmark_name=benchmark_name,
            run_id=run_id,
            question_id=question_id,
        )

    async def reset_namespace(self, namespace: str) -> int:
        return await self.namespace_manager.reset_namespace(namespace)

    async def write_records(
        self,
        *,
        namespace: str,
        records: list[EvalMemoryWriteRecord],
    ):
        self.namespace_manager.register_namespace(namespace)
        return await self.writer.write_records(records)

    async def query_memory(self, query: EvalMemoryQuery) -> EvalMemoryQueryResult:
        self.namespace_manager.register_namespace(query.namespace)
        return await self.reader.query_memory(query)
