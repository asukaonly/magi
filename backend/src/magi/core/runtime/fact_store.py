"""
Fact store for runtime agents.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict

from .contracts import FactRecord


class FactStore:
    """Stores and queues facts per target runtime agent."""

    def __init__(self) -> None:
        self._facts: dict[str, list[FactRecord]] = defaultdict(list)
        self._queues: dict[str, asyncio.Queue[FactRecord]] = {}

    def get_queue(self, agent_id: str) -> asyncio.Queue[FactRecord]:
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
        return self._queues[agent_id]

    async def append_fact(self, record: FactRecord) -> None:
        self._facts[record.agent_id].append(record)
        await self.get_queue(record.agent_id).put(record)

    def get_recent_facts(self, agent_id: str, limit: int = 20) -> list[FactRecord]:
        records = self._facts.get(agent_id, [])
        if limit <= 0:
            return []
        return records[-limit:]

    def get_counts(self) -> dict[str, int]:
        return {agent_id: len(records) for agent_id, records in self._facts.items()}
