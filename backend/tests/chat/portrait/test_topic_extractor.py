from unittest.mock import AsyncMock

import pytest

from magi.chat.portrait.contracts import TopicResult
from magi.chat.portrait.topic_extractor import TopicExtractor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entities", "expected"),
    [(["罗永浩", "锤子手机"], ["罗永浩", "锤子手机"]), ({"invalid": "shape"}, [])],
)
async def test_extract_returns_topic_and_entities(entities, expected):
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(
        return_value={
            "topic": "罗永浩",
            "entities": entities,
        }
    )
    extractor = TopicExtractor(bridge_factory=lambda: mock_bridge)
    result = await extractor.extract(
        [
            {"role": "user", "content": "你怎么看罗永浩"},
            {"role": "assistant", "content": "老罗是个把失败做成IP的人"},
        ]
    )
    assert isinstance(result, TopicResult)
    assert result.topic == "罗永浩"
    assert result.entities == expected
    mock_bridge.complete_json.assert_awaited_once()
    call = mock_bridge.complete_json.await_args.kwargs
    assert call["user_prompt"] == "[user] 你怎么看罗永浩\n[assistant] 老罗是个把失败做成IP的人"
    assert "Output strict JSON" in call["system_prompt"]


@pytest.mark.asyncio
async def test_extract_empty_messages_returns_empty_result():
    extractor = TopicExtractor(bridge_factory=lambda: AsyncMock())
    result = await extractor.extract([])
    assert result.is_empty()


@pytest.mark.asyncio
async def test_extract_llm_failure_returns_empty():
    mock_bridge = AsyncMock()
    mock_bridge.complete_json = AsyncMock(side_effect=RuntimeError("llm down"))
    extractor = TopicExtractor(bridge_factory=lambda: mock_bridge)
    result = await extractor.extract([{"role": "user", "content": "hi"}])
    assert result.is_empty()


@pytest.mark.asyncio
async def test_extract_no_bridge_returns_empty():
    extractor = TopicExtractor(bridge_factory=lambda: None)
    result = await extractor.extract([{"role": "user", "content": "hi"}])
    assert result.is_empty()
