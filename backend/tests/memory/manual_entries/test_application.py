"""Application admission works independently of FastAPI and container setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from magi.memory.application_errors import MemoryApplicationError
from magi.memory.manual_entries.application import (
    ManualEntryDependencies,
    create_manual_entry,
    get_manual_entry,
)
from magi.memory.manual_entries.commands import ManualEntryCreateBody


@pytest.mark.asyncio
async def test_clear_admission_rejects_before_any_store_write():
    store = SimpleNamespace(get=AsyncMock())
    memory = SimpleNamespace(
        memory_operation_epoch=lambda: 1, memory_clear_in_progress=lambda: True
    )
    services = ManualEntryDependencies(store, None, None, None, None, memory)
    with pytest.raises(MemoryApplicationError) as error:
        await create_manual_entry(
            ManualEntryCreateBody(entry_id="me-test", body="A note"), services=services
        )
    assert error.value.reason == "conflict"
    assert error.value.detail["code"] == "memory_clear_in_progress"
    store.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_entry_returns_a_domain_failure_without_http():
    services = ManualEntryDependencies(
        SimpleNamespace(get=AsyncMock(return_value=None)), None, None, None, None, None
    )
    with pytest.raises(MemoryApplicationError) as error:
        await get_manual_entry("me-missing", services=services)
    assert error.value.reason == "not_found"
