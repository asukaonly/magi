"""Ownership and retirement behavior for live plugin registrations."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from magi.events.plugin_ingress import PluginIngressHandlerRegistration, PluginIngressRegistry


def entry(handler):
    return PluginIngressHandlerRegistration("photos", "observed", handler, replay_safe=True)


@pytest.mark.asyncio
async def test_same_plugin_accounts_are_isolated_and_reload_uses_new_worker():
    registry = PluginIngressRegistry()
    left, right, replacement = AsyncMock(), AsyncMock(), AsyncMock()
    dispose = registry.register("left", "epoch", [entry(left)])
    registry.register("right", "epoch", [entry(right)])
    for cid, expected in (("left", left), ("right", right)):
        with registry.lease(cid, "epoch", "photos", "observed") as lease:
            assert lease.handler is expected
    with registry.lease("left", "epoch", "photos", "observed") as lease:
        dispose()
        drained = asyncio.create_task(registry.drain("left"))
        await asyncio.sleep(0)
        assert not drained.done()
        with registry.lease("left", "epoch", "photos", "observed") as stopped:
            assert stopped is None
        with pytest.raises(ValueError):
            registry.register("left", "epoch", [entry(replacement)])
    await drained
    registry.register("left", "new-epoch", [entry(replacement)])
    dispose()  # An obsolete disposer cannot detach a replacement.
    with registry.lease("left", "epoch", "photos", "observed") as stale:
        assert stale is None
    with registry.lease("left", "new-epoch", "photos", "observed") as current:
        assert current.handler is replacement


def test_duplicate_keys_within_one_connection_are_rejected_atomically():
    registry = PluginIngressRegistry()
    with pytest.raises(ValueError):
        registry.register("left", "epoch", [entry(AsyncMock()), entry(AsyncMock())])
    assert not registry.connection_active("left")
