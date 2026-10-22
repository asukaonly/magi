"""Explicit SQLite composition for timeline integration tests."""

from magi.memory.assets.sqlite_references import SqliteAssetReferenceRepository
from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
from magi.timeline.persistence.sqlite_cover import SqliteTimelineCoverRepository
from magi.timeline.service import TimelineService

from .db_schema import apply_chain_schema


def build_timeline_service(memory, **kwargs):
    path = getattr(memory, "memory_db_path", None)
    if path:
        apply_chain_schema("memory_shared", path)
        kwargs.setdefault("cover_repository", SqliteTimelineCoverRepository(db_path=str(path)))
        if not hasattr(memory, "asset_references"):
            memory.asset_references = SqliteAssetReferenceRepository(str(path))
        if not hasattr(memory, "daily_mood"):
            memory.daily_mood = DailyMoodAggregateStore(str(path))
    return TimelineService(memory, **kwargs)
