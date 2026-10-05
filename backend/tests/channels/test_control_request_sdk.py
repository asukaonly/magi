"""Control request validation and optional SDK channel capabilities."""
from __future__ import annotations

import pytest

from magi_plugin_sdk import ControlRequest
from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent


# === ControlRequest dataclass shape =======================================


@pytest.mark.parametrize("field", ["request_id", "short_id", "kind", "tool_name"])
def test_control_request_rejects_empty_routing_fields(field):
    values = {
        "request_id": "request-1",
        "short_id": "abc123",
        "kind": "permission",
        "tool_name": "probe",
        "preview": "",
    }
    values[field] = ""
    with pytest.raises(ValueError, match=f"{field} must be non-empty"):
        ControlRequest(**values)


# === Default Channel.deliver_control_request behavior ====================


class _Bare(Channel):
    """Minimal concrete Channel that does NOT override
    ``deliver_control_request`` — used to test the default."""

    @property
    def channel_type(self) -> str:
        return "bare"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(
        self, target: ChannelTarget, content: OutboundContent
    ) -> None:
        pass

    async def send_typing_indicator(self, target: ChannelTarget) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chunk", "control_request"])
async def test_default_channel_capabilities_prevent_router_invocation(monkeypatch, kind):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from magi.channels.delivery_router import DeliveryRouter
    from magi_plugin_sdk.delivery import DeliveryChunk

    instance = _Bare()
    method = AsyncMock()
    monkeypatch.setattr(instance, f"deliver_{kind}", method)
    target = ChannelTarget(channel_type="bare", external_chat_id="c1")
    router = DeliveryRouter(channel_registry=SimpleNamespace(get=lambda channel: instance))
    payload = (
        {"chunk": DeliveryChunk(text="hi", is_final=False, seq=0)}
        if kind == "chunk"
        else {
            "request": ControlRequest(
                request_id="request-1",
                short_id="abc123",
                kind="permission",
                tool_name="probe",
                preview="",
            )
        }
    )
    await getattr(router, f"fanout_{kind}")(targets=[target], **payload)
    method.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,capability",
    [("chunk", "supports_streaming"), ("control_request", "supports_control_requests")],
)
async def test_unimplemented_optional_channel_method_reports_its_capability(kind, capability):
    from magi_plugin_sdk.delivery import DeliveryChunk

    instance = _Bare()
    target = ChannelTarget(channel_type="bare", external_chat_id="c1")
    payload = (
        DeliveryChunk(text="hi", is_final=False, seq=0)
        if kind == "chunk"
        else ControlRequest(
            request_id="request-1",
            short_id="abc123",
            kind="permission",
            tool_name="probe",
            preview="",
        )
    )
    with pytest.raises(NotImplementedError, match=rf"_Bare.*{capability}"):
        await getattr(instance, f"deliver_{kind}")(target, payload)
