"""The coordinator uses supplied query owners without selecting local adapters."""

from unittest.mock import AsyncMock, Mock

from magi.memory.unified_store import UnifiedMemoryStore


async def test_memory_coordinator_uses_injected_owners(tmp_path):
    indexes = Mock()
    assets = Mock(is_visible_reference=AsyncMock(return_value=True))
    mood = Mock(list_aggregates=AsyncMock(return_value=[]))
    archives = Mock(search=AsyncMock(return_value={"test": "archive-result"}))
    memory = UnifiedMemoryStore(
        persist_dir=str(tmp_path), enable_l0=False, enable_l1=False, enable_l2=False,
        enable_l3=False, enable_l4=False,
        vector_index_factory=indexes, asset_references=assets,
        daily_mood=mood, archive_repository=archives,
    )
    assert memory.vector_indexes is indexes
    assert memory.asset_references is assets
    assert memory.daily_mood is mood
    result = await memory.archives.search(query="retained", event_ids=("event",))
    assert result == {"test": "archive-result"}
    archives.search.assert_awaited_once_with(
        query="retained", limit=20, offset=0, event_ids=("event",),
    )
    assert not list(tmp_path.rglob("*.db"))
