"""Storage contract for the daily mood projection."""

from typing import Protocol

from .models import DailyMoodAggregate


class DailyMoodRepository(Protocol):
    async def upsert_aggregate(self, aggregate: DailyMoodAggregate) -> bool: ...
    async def list_aggregates(
        self, *, start_date: str, end_date: str
    ) -> list[DailyMoodAggregate]: ...
