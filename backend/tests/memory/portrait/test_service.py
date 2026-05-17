import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.portrait.contracts import (
    PortraitObservation,
    RawMemorySnippet,
    TopicResult,
)
from magi.memory.portrait.service import PortraitService


def _persona_detail(name="七号", cold_lines=None):
    return {
        "persona_id": "p1",
        "name": name,
        "config": {
            "name": name,
            "identity_core": {"identity_statement": "猫一样的搭档"},
            "idiolect": {"sentence_style": "短句"},
            "interim_lines": {
                "portrait_cold_start": cold_lines or [],
            },
        },
    }


@pytest.fixture
def deps():
    return {
        "topic_extractor": MagicMock(),
        "renderer": MagicMock(),
        "snippet_fetcher": AsyncMock(),
        "persona_loader": AsyncMock(),
        "message_loader": AsyncMock(),
    }


def _async_returning(value):
    return AsyncMock(return_value=value)


@pytest.mark.asyncio
async def test_first_call_returns_computing_then_warms_cache(deps):
    """First request kicks off a background task and returns cold-start.
    After the task completes, the cache holds the warm payload."""
    deps["message_loader"].return_value = [{"role": "user", "content": "你怎么看罗永浩"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="罗永浩", entities=["罗永浩"]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="你又在想老罗", basis_count=1,
                            basis_summary="1 条", basis_refs=["m1"]),
    ])

    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"))

    first = await service.get_portrait(user_id="u1", session_id="s1")
    assert first.is_cold_start is True
    assert first.cold_start_reason == "computing"

    await service.wait_for_pending()

    second = await service.get_portrait(user_id="u1", session_id="s1")
    assert second.is_cold_start is False
    assert len(second.observations) == 1
    assert second.observations[0].text == "你又在想老罗"
    assert second.topic == "罗永浩"


@pytest.mark.asyncio
async def test_concurrent_requests_single_flight(deps):
    """Two near-simultaneous requests must spawn at most one background task."""
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=["e"]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])

    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"))

    a, b = await asyncio.gather(
        service.get_portrait(user_id="u1", session_id="s1"),
        service.get_portrait(user_id="u1", session_id="s1"),
    )
    assert a.is_cold_start and b.is_cold_start

    await service.wait_for_pending()

    # The background pipeline should have been called exactly once.
    assert deps["topic_extractor"].extract.call_count == 1
    assert deps["renderer"].render.call_count == 1


@pytest.mark.asyncio
async def test_no_snippets_does_not_warm_cache(deps):
    """A compute that ends in 'no_snippets' must leave the cache empty so
    later polls (after L2/L3 catch up) can succeed."""
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail(
        cold_lines=["七号还在认识你"],
    )
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=["e"]))
    deps["snippet_fetcher"].return_value = []
    deps["renderer"].render = AsyncMock(return_value=[])

    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"),
                              random_seed=42)

    first = await service.get_portrait(user_id="u1", session_id="s1")
    assert first.cold_start_reason == "computing"

    await service.wait_for_pending()

    second = await service.get_portrait(user_id="u1", session_id="s1")
    # Still cold-start: now reports the most recent attempt's outcome via
    # a fresh spawn (reason="computing"), and no warm payload exists yet.
    assert second.is_cold_start is True
    # Renderer was never called because snippets were empty.
    deps["renderer"].render.assert_not_called()


@pytest.mark.asyncio
async def test_force_refresh_spawns_new_task(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=["e"]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o1", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])
    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"))

    await service.get_portrait(user_id="u1", session_id="s1")
    await service.wait_for_pending()

    deps["topic_extractor"].extract.reset_mock()
    await service.get_portrait(user_id="u1", session_id="s1", force=True)
    await service.wait_for_pending()
    deps["topic_extractor"].extract.assert_called_once()


@pytest.mark.asyncio
async def test_no_active_persona_returns_empty_cold_start(deps):
    service = PortraitService(**deps, active_persona_resolver=_async_returning(None))
    payload = await service.get_portrait(user_id="u1", session_id="s1")
    assert payload.is_cold_start is True
    assert payload.cold_start_reason == "no_persona"
    assert payload.persona_id == ""
