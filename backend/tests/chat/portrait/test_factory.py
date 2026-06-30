from types import SimpleNamespace

import pytest

from magi.chat.portrait.factory import _BridgeJsonAdapter


class _FakeBridge:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []
        self.llm = SimpleNamespace(
            model_name="test-model",
            base_url="http://llm.test",
        )

    async def chat(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_bridge_json_adapter_returns_json_and_passes_chat_options() -> None:
    bridge = _FakeBridge('{"ok": true}')
    adapter = _BridgeJsonAdapter(
        bridge,
        label="topic",
        thinking_depth="none",
        timeout_seconds=25.0,
    )

    result = await adapter.complete_json(
        system_prompt="system",
        user_prompt="hello",
    )

    assert result == {"ok": True}
    assert bridge.calls == [
        {
            "system_prompt": "system",
            "messages": [{"role": "user", "content": "hello"}],
            "json_mode": True,
            "temperature": 0.2,
            "thinking_depth": "none",
            "timeout_seconds": 25.0,
        }
    ]


@pytest.mark.asyncio
async def test_bridge_json_adapter_returns_empty_dict_for_bad_json() -> None:
    bridge = _FakeBridge("not json")
    adapter = _BridgeJsonAdapter(bridge, label="topic")

    assert await adapter.complete_json(system_prompt="system", user_prompt="hello") == {}


@pytest.mark.asyncio
async def test_bridge_json_adapter_returns_empty_dict_on_bridge_failure() -> None:
    bridge = _FakeBridge(error=RuntimeError("llm down"))
    adapter = _BridgeJsonAdapter(bridge, label="topic")

    assert await adapter.complete_json(system_prompt="system", user_prompt="hello") == {}
