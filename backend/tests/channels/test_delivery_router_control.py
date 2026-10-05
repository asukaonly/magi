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
@pytest.mark.parametrize(
    "first_enabled,second_enabled,preview",
    [
        (True, True, "generate a cat"),
        (True, False, ""),
        (False, True, "generate a cat"),
        (False, False, ""),
    ],
)
async def test_control_fanout_preserves_request_and_only_calls_opted_in_channels(
    first_enabled, second_enabled, preview
):
    from dataclasses import asdict

    first = _ChannelStub(ctype="first", supports_control=first_enabled)
    second = _ChannelStub(ctype="second", supports_control=second_enabled)
    router = DeliveryRouter(channel_registry=_Registry({"first": first, "second": second}))
    req = ControlRequest(
        request_id="request-1",
        short_id="abc123",
        kind="permission",
        tool_name="probe",
        preview=preview,
    )
    targets = [_target("first"), _target("second")]
    await router.fanout_control_request(request=req, targets=targets)
    assert first.calls == ([(targets[0], req)] if first_enabled else [])
    assert second.calls == ([(targets[1], req)] if second_enabled else [])
    for _, received in [*first.calls, *second.calls]:
        assert received is req
        assert asdict(received) == {
            "request_id": "request-1",
            "short_id": "abc123",
            "kind": "permission",
            "tool_name": "probe",
            "preview": preview,
            "risk_level": "medium",
            "expires_at_ms": None,
            "payload": {},
        }


# === Skip / isolation ====================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,level", [(RuntimeError, logging.WARNING), (NotImplementedError, logging.INFO)]
)
async def test_control_channel_failure_is_observed_logged_and_isolated(caplog, error, level):
    bad = _ChannelStub(ctype="bad", supports_control=True, raise_exc=error)
    good = _ChannelStub(ctype="good", supports_control=True)
    router = DeliveryRouter(channel_registry=_Registry({"bad": bad, "good": good}))
    req = _make_request()
    targets = [_target("bad"), _target("good")]
    with caplog.at_level(logging.INFO):
        await router.fanout_control_request(request=req, targets=targets)
    assert bad.calls == [(targets[0], req)]
    assert good.calls == [(targets[1], req)]
    assert any(
        record.levelno == level and "bad" in record.getMessage() for record in caplog.records
    )


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


# === Edge cases ==========================================================




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
