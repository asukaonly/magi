"""``DeliveryRouter.fanout_control_request`` — CF-4 of channel control fanout.

Pins:
* Channels with ``supports_control_requests = False`` are skipped
  silently (fast path — no per-call NotImplementedError catch).
* Channels with the flag ``True`` get ``deliver_control_request``
  called with the same target + request.
* Per-channel exceptions are isolated — one failure doesn't abort
  the rest of the fanout, matching ``fanout_deliver`` semantics.
* Defensive: a flag-True / NotImplementedError-raising channel
  (plugin author bug) logs at info level and continues; doesn't
  crash the fanout.
* Empty target list → no-op (no spurious logs / coroutines).
"""
from __future__ import annotations

import logging

import pytest

from magi.channels.delivery_router import DeliveryRouter
from magi_plugin_sdk import ControlRequest
from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent


class _ChannelStub(Channel):
    """Test double with controllable opt-in and outcome."""

    def __init__(
        self,
        *,
        ctype: str,
        supports_control: bool,
        raise_exc: type[BaseException] | None = None,
    ) -> None:
        # Override class attr per-instance (Channel reads instance via getattr).
        self.supports_control_requests = supports_control  # type: ignore[misc]
        self._ctype = ctype
        self._raise_exc = raise_exc
        self.calls: list[tuple[ChannelTarget, ControlRequest]] = []

    @property
    def channel_type(self) -> str:
        return self._ctype

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, target, content: OutboundContent) -> None:
        pass

    async def send_typing_indicator(self, target) -> None:
        pass

    async def deliver_control_request(self, target, request) -> None:
        self.calls.append((target, request))
        if self._raise_exc is not None:
            raise self._raise_exc("forced")


class _Registry:
    def __init__(self, channels: dict[str, Channel]) -> None:
        self._channels = channels

    def get(self, channel_id: str):
        return self._channels.get(channel_id)


def _make_request() -> ControlRequest:
    return ControlRequest(
        request_id="01HFTGSM7Z8X9YQK4PVAN3RBCD",
        short_id="an3rbc",
        kind="permission",
        tool_name="image_gen",
        preview="gen a cat",
    )


def _target(ctype: str) -> ChannelTarget:
    return ChannelTarget(channel_type=ctype, external_chat_id="")


# === Happy path ==========================================================


@pytest.mark.asyncio
async def test_opted_in_channel_receives_request() -> None:
    """Channel with supports_control_requests=True gets the call."""
    tg = _ChannelStub(ctype="telegram", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"telegram": tg}))
    req = _make_request()
    await router.fanout_control_request(request=req, targets=[_target("telegram")])
    assert len(tg.calls) == 1
    assert tg.calls[0][0].channel_type == "telegram"
    assert tg.calls[0][1] is req


@pytest.mark.asyncio
async def test_two_opted_in_channels_both_receive() -> None:
    """All opted-in targets get the call, in parallel."""
    tg = _ChannelStub(ctype="telegram", supports_control=True)
    sse = _ChannelStub(ctype="chat_sse", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"telegram": tg, "chat_sse": sse}))
    await router.fanout_control_request(
        request=_make_request(),
        targets=[_target("chat_sse"), _target("telegram")],
    )
    assert len(tg.calls) == 1
    assert len(sse.calls) == 1


# === Skip / isolation ====================================================


@pytest.mark.asyncio
async def test_non_opted_in_channel_skipped_silently() -> None:
    """Channel with supports_control_requests=False is NOT called.

    No NotImplementedError catch — the capability flag is the fast
    path so the host doesn't pay for an exception per call."""
    wx = _ChannelStub(ctype="weixin", supports_control=False)
    router = DeliveryRouter(channel_registry=_Registry({"weixin": wx}))
    await router.fanout_control_request(
        request=_make_request(), targets=[_target("weixin")],
    )
    assert wx.calls == []


@pytest.mark.asyncio
async def test_one_opted_in_one_not_only_opted_in_called() -> None:
    """Mixed fanout: opted-in channel gets the call, non-opted skipped."""
    tg = _ChannelStub(ctype="telegram", supports_control=True)
    wx = _ChannelStub(ctype="weixin", supports_control=False)
    router = DeliveryRouter(channel_registry=_Registry(
        {"telegram": tg, "weixin": wx}
    ))
    await router.fanout_control_request(
        request=_make_request(),
        targets=[_target("telegram"), _target("weixin")],
    )
    assert len(tg.calls) == 1
    assert wx.calls == []


@pytest.mark.asyncio
async def test_exception_in_one_channel_does_not_abort_others() -> None:
    """Per-channel failure isolation: a raising channel logs, the
    healthy channel still completes."""
    bad = _ChannelStub(ctype="bad", supports_control=True, raise_exc=RuntimeError)
    good = _ChannelStub(ctype="good", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"bad": bad, "good": good}))
    await router.fanout_control_request(
        request=_make_request(),
        targets=[_target("bad"), _target("good")],
    )
    assert len(good.calls) == 1
    assert len(bad.calls) == 1  # was called, raised, caught


@pytest.mark.asyncio
async def test_registry_lookup_failure_does_not_abort_other_control_targets() -> None:
    good = _ChannelStub(ctype="good", supports_control=True)

    class _FailingRegistry(_Registry):
        def get(self, channel_id: str):
            if channel_id == "broken":
                raise RuntimeError("registry unavailable")
            return super().get(channel_id)

    router = DeliveryRouter(
        channel_registry=_FailingRegistry({"good": good})
    )
    await router.fanout_control_request(
        request=_make_request(),
        targets=[_target("broken"), _target("good")],
    )

    assert len(good.calls) == 1


@pytest.mark.asyncio
async def test_flag_true_but_not_implemented_logged_and_continues() -> None:
    """Defensive: plugin sets flag=True but the override raises
    NotImplementedError (author bug). Logged at info level, no
    crash, other channels continue."""
    buggy = _ChannelStub(ctype="buggy", supports_control=True, raise_exc=NotImplementedError)
    good = _ChannelStub(ctype="good", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"buggy": buggy, "good": good}))
    await router.fanout_control_request(
        request=_make_request(),
        targets=[_target("buggy"), _target("good")],
    )
    assert len(good.calls) == 1


# === Edge cases ==========================================================


@pytest.mark.asyncio
async def test_empty_targets_is_noop() -> None:
    """No targets → no work, no exception, no spurious log noise."""
    router = DeliveryRouter(channel_registry=_Registry({}))
    await router.fanout_control_request(request=_make_request(), targets=[])
    # No exception = pass


@pytest.mark.asyncio
async def test_unknown_channel_type_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Target whose channel_type isn't registered → WARNING log,
    fanout continues to other channels (same as fanout_deliver)."""
    tg = _ChannelStub(ctype="telegram", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"telegram": tg}))
    with caplog.at_level(logging.WARNING):
        await router.fanout_control_request(
            request=_make_request(),
            targets=[_target("ghost"), _target("telegram")],
        )
    assert any("no channel registered" in rec.message for rec in caplog.records)
    assert len(tg.calls) == 1
