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
async def test_cold_start_when_no_snippets(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail(
        cold_lines=["七号还在认识你"],
    )
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=["e"]))
    deps["snippet_fetcher"].return_value = []
    deps["renderer"].render = AsyncMock(return_value=[])

    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"),
                              random_seed=42)
    payload = await service.get_portrait(user_id="u1", session_id="s1")

    assert payload.is_cold_start is True
    assert payload.cold_start_line == "七号还在认识你"
    assert payload.observations == []
    assert payload.persona_id == "p1"


@pytest.mark.asyncio
async def test_full_flow_returns_observations(deps):
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
    payload = await service.get_portrait(user_id="u1", session_id="s1")

    assert payload.is_cold_start is False
    assert len(payload.observations) == 1
    assert payload.observations[0].text == "你又在想老罗"
    assert payload.topic == "罗永浩"


@pytest.mark.asyncio
async def test_cache_hit_skips_llm(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=[]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o1", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])
    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"))
    await service.get_portrait(user_id="u1", session_id="s1")
    # second call should hit cache
    deps["topic_extractor"].extract.reset_mock()
    deps["renderer"].render.reset_mock()
    payload = await service.get_portrait(user_id="u1", session_id="s1")
    assert payload.observations[0].text == "o1"
    deps["topic_extractor"].extract.assert_not_called()
    deps["renderer"].render.assert_not_called()


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(deps):
    deps["message_loader"].return_value = [{"role": "user", "content": "hi"}]
    deps["persona_loader"].return_value = _persona_detail()
    deps["topic_extractor"].extract = AsyncMock(return_value=TopicResult(topic="t", entities=[]))
    deps["snippet_fetcher"].return_value = [
        RawMemorySnippet(id="m1", kind="reflection", layer="L3", statement="x"),
    ]
    deps["renderer"].render = AsyncMock(return_value=[
        PortraitObservation(kind="reflection", text="o1", basis_count=1,
                            basis_summary="1", basis_refs=["m1"]),
    ])
    service = PortraitService(**deps, active_persona_resolver=_async_returning("p1"))
    await service.get_portrait(user_id="u1", session_id="s1")
    deps["topic_extractor"].extract.reset_mock()
    await service.get_portrait(user_id="u1", session_id="s1", force=True)
    deps["topic_extractor"].extract.assert_called_once()


@pytest.mark.asyncio
async def test_no_active_persona_returns_empty_cold_start(deps):
    service = PortraitService(**deps, active_persona_resolver=_async_returning(None))
    payload = await service.get_portrait(user_id="u1", session_id="s1")
    assert payload.is_cold_start is True
    assert payload.persona_id == ""
