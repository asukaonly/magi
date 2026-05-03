import asyncio

import pytest

from magi.mcp.resource_cache import MCPResourceCache


@pytest.mark.asyncio
async def test_get_or_fetch_caches_within_ttl():
    cache = MCPResourceCache(ttl_seconds=10)
    calls = 0

    async def fetch(server_id: str, uri: str):
        nonlocal calls
        calls += 1
        return {"data": f"{server_id}:{uri}"}

    a = await cache.get_or_fetch("s", "u", fetch)
    b = await cache.get_or_fetch("s", "u", fetch)
    assert a == b
    assert calls == 1


@pytest.mark.asyncio
async def test_get_or_fetch_dedupes_concurrent_calls():
    cache = MCPResourceCache(ttl_seconds=10)
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(server_id: str, uri: str):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"v": 1}

    t1 = asyncio.create_task(cache.get_or_fetch("s", "u", fetch))
    await started.wait()
    t2 = asyncio.create_task(cache.get_or_fetch("s", "u", fetch))
    # Give t2 a moment to enter the lock-wait state.
    await asyncio.sleep(0)
    release.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert r1 == r2 == {"v": 1}
    assert calls == 1


@pytest.mark.asyncio
async def test_expired_entries_refetched():
    cache = MCPResourceCache(ttl_seconds=0.05)
    calls = 0

    async def fetch(server_id: str, uri: str):
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_fetch("s", "u", fetch) == 1
    await asyncio.sleep(0.06)
    assert await cache.get_or_fetch("s", "u", fetch) == 2


@pytest.mark.asyncio
async def test_invalidate_drops_entry():
    cache = MCPResourceCache(ttl_seconds=10)
    cache.put("s", "u", {"v": 1})
    assert cache.get("s", "u") == {"v": 1}
    cache.invalidate("s", "u")
    assert cache.get("s", "u") is None
