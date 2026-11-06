"""A lost process reply cannot be reported as a successful storage mutation."""

import asyncio
from unittest.mock import AsyncMock
import pytest
from magi.core.persistence_errors import PersistenceUnavailableError
from magi.plugins.process_runtime import PluginProcessTimeout
from magi.plugins.storage_proxy import StorageProviderProxy
from magi_plugin_sdk.storage import StorageCall


async def test_lost_write_confirmation_is_unavailable_without_retry():
    process = AsyncMock()
    process.invoke.side_effect = PluginProcessTimeout("deadline")
    provider = StorageProviderProxy(process, "storage:0")
    with pytest.raises(PersistenceUnavailableError):
        await provider.invoke(StorageCall(session_id="s", repository="events", operation="append"))
    process.invoke.assert_awaited_once()


async def test_cancellation_remains_cancellation():
    process = AsyncMock()
    process.invoke.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await StorageProviderProxy(process, "storage:0").invoke(
            StorageCall(session_id="s", repository="events", operation="get"))
