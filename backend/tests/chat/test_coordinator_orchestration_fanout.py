"""Regression: a chat turn that finishes via the legacy handler-registry path
(ORCHESTRATION_UPDATE — i.e. a worker-delegated result) must fan out its final
response to the originating external channel, not just publish to the message
bus. Before the fix, fanout_deliver was trapped inside the `route_decision is
not None` branch, so WeChat/Telegram-originated tasks that got offloaded to a
worker subagent silently never reached the channel.
"""
from types import SimpleNamespace

import pytest

from magi_plugin_sdk.delivery import DeliveryContent, DeliveryReceipt
from magi.agent.task_agents.common.contracts import ExecutionMode, ExecutionResult
from magi.channels.chat_delivery_dispatcher import ChatDeliveryDispatcher
from magi.chat.task_agent.coordinator import ChatExecutionCoordinator


class _FakeChannel:
    def __init__(self, channel_type: str) -> None:
        self._ct = channel_type
        self.delivered: list = []

    @property
    def channel_type(self) -> str:
        return self._ct

    async def deliver(self, target, content):
        self.delivered.append((target, content))
        return DeliveryReceipt(
            channel_id=self._ct, external_message_id=f"id_{self._ct}", delivered_at_ms=1
        )


class _FakeChannelRegistry:
    def __init__(self, channels: dict) -> None:
        self._channels = channels

    def get(self, channel_type: str):
        return self._channels.get(channel_type)


class _FakeHandler:
    def __init__(self, result: ExecutionResult) -> None:
        self._result = result

    async def execute(self, request):
        return self._result


class _FakeHandlerRegistry:
    def __init__(self, handler: _FakeHandler) -> None:
        self._handlers: dict = {}
        self._handler = handler

    def get(self, mode):
        return self._handler


def _coordinator(result: ExecutionResult, registry: _FakeChannelRegistry) -> ChatExecutionCoordinator:
    return ChatExecutionCoordinator(
        context_decider=SimpleNamespace(tool_registry=None),
        fact_classifier=SimpleNamespace(),
        handler_registry=_FakeHandlerRegistry(_FakeHandler(result)),
        delivery_dispatcher=ChatDeliveryDispatcher.from_registry(
            channel_registry=registry,
        ),
    )


def _request(*, origin_channel: str = "weixin"):
    return SimpleNamespace(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        context=SimpleNamespace(
            session_id="chsess_x",
            session_run_id="run_x",
            user_id="local_user",
            active_run=SimpleNamespace(trigger=SimpleNamespace(source_channel=origin_channel)),
            user_prefs=None,
            revision=0,
        ),
        intent=SimpleNamespace(route_decision=None),
        tool_selection=None,
    )


@pytest.mark.asyncio
async def test_orchestration_update_fans_out_after_postprocess_persistence():
    weixin = _FakeChannel("weixin")
    chat_sse = _FakeChannel("chat_sse")
    registry = _FakeChannelRegistry({"weixin": weixin, "chat_sse": chat_sse})
    result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        response_text="12 tickets done — 4 bugs, 3 feature requests.",
        skip_emit=False,
    )
    coord = _coordinator(result, registry)

    request = _request(origin_channel="weixin")
    out = await coord.execute(request)

    assert out is result  # still returns the handler's result unchanged
    assert not weixin.delivered
    await coord.deliver_final_chat_response(
        request.context,
        content=DeliveryContent(text=result.response_text),
    )
    assert weixin.delivered, "worker_update result was NOT fanned out to the origin weixin channel"
    assert weixin.delivered[0][1].text == "12 tickets done — 4 bugs, 3 feature requests."


@pytest.mark.asyncio
async def test_orchestration_update_skip_emit_does_not_fanout():
    weixin = _FakeChannel("weixin")
    registry = _FakeChannelRegistry({"weixin": weixin, "chat_sse": _FakeChannel("chat_sse")})
    # Interim worker progress: skip_emit=True must NOT spam the channel.
    result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE, response_text="still working…", skip_emit=True
    )
    coord = _coordinator(result, registry)

    await coord.execute(_request())

    assert not weixin.delivered


@pytest.mark.asyncio
async def test_orchestration_update_empty_text_does_not_fanout():
    weixin = _FakeChannel("weixin")
    registry = _FakeChannelRegistry({"weixin": weixin, "chat_sse": _FakeChannel("chat_sse")})
    result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE, response_text="", skip_emit=False
    )
    coord = _coordinator(result, registry)

    await coord.execute(_request())

    assert not weixin.delivered


@pytest.mark.asyncio
async def test_fanout_strips_sentinel_before_external_channel_delivery():
    weixin = _FakeChannel("weixin")
    registry = _FakeChannelRegistry({"weixin": weixin, "chat_sse": _FakeChannel("chat_sse")})
    result = ExecutionResult(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        response_text="part one‖part two",
        skip_emit=False,
    )
    coord = _coordinator(result, registry)

    request = _request(origin_channel="weixin")
    await coord.execute(request)

    assert not weixin.delivered
    await coord.deliver_final_chat_response(
        request.context,
        content=DeliveryContent(text=result.response_text),
    )

    assert weixin.delivered, "no delivery reached the weixin channel"
    assert weixin.delivered[0][1].text == "part one part two"
    assert "‖" not in weixin.delivered[0][1].text
