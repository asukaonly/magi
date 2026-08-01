import asyncio

import pytest

from magi.mcp.resource_cache import MCPResourceCache, MCPResourceCacheClearedError


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


@pytest.mark.asyncio
async def test_global_data_clear_waits_for_active_fetch_and_removes_result():
    cache = MCPResourceCache(ttl_seconds=10)
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(_server_id: str, _uri: str):
        started.set()
        await release.wait()
        return {"private": "resource text"}

    fetch_task = asyncio.create_task(cache.get_or_fetch("s", "private://u", fetch))
    await started.wait()
    clear_entered = asyncio.Event()

    async def clear_cache() -> None:
        async with cache.global_data_clear_boundary():
            clear_entered.set()

    clear_task = asyncio.create_task(clear_cache())
    await asyncio.sleep(0)
    assert not clear_entered.is_set()

    release.set()
    assert await fetch_task == {"private": "resource text"}
    await clear_task
    assert cache.get("s", "private://u") is None


@pytest.mark.asyncio
async def test_global_data_clear_rejects_fetch_queued_before_clear():
    cache = MCPResourceCache(ttl_seconds=10)
    blocker_started = asyncio.Event()
    release_blocker = asyncio.Event()

    async def blocking_fetch(_server_id: str, _uri: str):
        blocker_started.set()
        await release_blocker.wait()
        return {"private": "first"}

    active = asyncio.create_task(cache.get_or_fetch("s", "private://active", blocking_fetch))
    await blocker_started.wait()
    clear_entered = asyncio.Event()
    release_clear = asyncio.Event()

    async def clear_cache() -> None:
        async with cache.global_data_clear_boundary():
            clear_entered.set()
            await release_clear.wait()

    clear_task = asyncio.create_task(clear_cache())
    await asyncio.sleep(0)

    async def stale_source(_server_id: str, _uri: str):
        return {"private": "old"}

    stale_fetch = asyncio.create_task(
        cache.get_or_fetch("s", "private://queued", stale_source)
    )

    release_blocker.set()
    await active
    await clear_entered.wait()
    release_clear.set()
    await clear_task

    with pytest.raises(MCPResourceCacheClearedError):
        await stale_fetch
