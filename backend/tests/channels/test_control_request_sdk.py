"""SDK contract tests for ``ControlRequest`` + default
``Channel.deliver_control_request``.

These pin the Phase H+2 control-plane fanout shape so the cross-repo
plugin work in magi-plugins can lock against a stable contract:

* ``ControlRequest`` rejects blank required fields (request_id,
  short_id, kind, tool_name) at construction time — silent ingress
  of empty IDs would route nowhere and never resolve.
* The default ``Channel.deliver_control_request`` raises a helpful
  ``NotImplementedError`` mentioning the subclass name and the
  ``supports_control_requests`` capability flag — same pattern as
  Phase G's ``deliver_chunk`` default.
* ``Channel.supports_control_requests`` defaults to ``False`` so the
  host's fanout router can skip non-opted-in channels without
  catching exceptions per call.
"""
from __future__ import annotations

import pytest

from magi_plugin_sdk import ControlRequest
from magi_plugin_sdk.channels import Channel, ChannelTarget, OutboundContent


# === ControlRequest dataclass shape =======================================


def test_control_request_minimal_construction() -> None:
    """Required fields land, optional fields default to sensible values."""
    req = ControlRequest(
        request_id="01HFTGSM7Z8X9YQK4PVAN3RBCD",
        short_id="an3rbc",
        kind="permission",
        tool_name="image_gen",
        preview='Generate image: "a cat with a hat"',
    )
    assert req.request_id == "01HFTGSM7Z8X9YQK4PVAN3RBCD"
    assert req.short_id == "an3rbc"
    assert req.kind == "permission"
    assert req.tool_name == "image_gen"
    assert req.preview.startswith("Generate image:")
    assert req.risk_level == "medium"  # default
    assert req.expires_at_ms is None  # default
    assert req.payload == {}  # default


def test_control_request_rejects_blank_request_id() -> None:
    """Blank request_id has no resolution semantics — broker.resolve
    would route nowhere."""
    with pytest.raises(ValueError, match="request_id must be non-empty"):
        ControlRequest(
            request_id="",
            short_id="abc123",
            kind="permission",
            tool_name="t",
            preview="p",
        )


@pytest.mark.parametrize(
    "expected_error,short_id_value,kind_value,tool_name_value",
    [
        pytest.param(
            "short_id must be non-empty",
            "",
            "permission",
            "t",
            id="control_request_rejects_blank_short_id",
        ),
        pytest.param(
            "kind must be non-empty", "abc123", "", "t", id="control_request_rejects_blank_kind"
        ),
        pytest.param(
            "tool_name must be non-empty",
            "abc123",
            "permission",
            "",
            id="control_request_rejects_blank_tool_name",
        ),
    ],
)
def test_control_request_rejects_blank_required_fields(
    expected_error, short_id_value, kind_value, tool_name_value
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        ControlRequest(
            request_id="01HFTGSM7Z8X9YQK4PVAN3RBCD",
            short_id=short_id_value,
            kind=kind_value,
            tool_name=tool_name_value,
            preview="p",
        )


def test_control_request_blank_preview_is_allowed() -> None:
    """Some tools have no humanly-summarizable preview (a no-arg
    side-effect-free probe), so empty preview must work."""
    req = ControlRequest(
        request_id="01HFTGSM7Z8X9YQK4PVAN3RBCD",
        short_id="abc123",
        kind="permission",
        tool_name="probe",
        preview="",
    )
    assert req.preview == ""


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


def test_channel_supports_control_requests_defaults_false() -> None:
    """Capability flag default ``False`` so the host's fanout router
    can quickly skip non-opted-in channels."""
    assert _Bare.supports_control_requests is False
    instance = _Bare()
    assert instance.supports_control_requests is False


@pytest.mark.asyncio
async def test_default_deliver_control_request_raises_with_capability_hint() -> None:
    """Default ``deliver_control_request`` raises NotImplementedError
    mentioning the subclass name and the ``supports_control_requests``
    capability flag, matching the ``deliver_chunk`` pattern."""
    instance = _Bare()
    target = ChannelTarget(channel_type="bare", external_chat_id="c1")
    req = ControlRequest(
        request_id="01HFTGSM7Z8X9YQK4PVAN3RBCD",
        short_id="abc123",
        kind="permission",
        tool_name="image_gen",
        preview="preview",
    )

    with pytest.raises(NotImplementedError, match=r"_Bare.*supports_control_requests"):
        await instance.deliver_control_request(target, req)
