"""Permission prompts must use the originating conversation address."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from magi.channels.lifecycle import _permission_fanout_callback
from magi.control.permission.contracts import PermissionRequest, RiskLevel, ToolOrigin


@pytest.mark.asyncio
@pytest.mark.parametrize("bound", [True, False])
async def test_permission_only_targets_bound_connection_and_thread(bound: bool) -> None:
    mapping = SimpleNamespace(
        channel_type="account-2:telegram", external_chat_id="group-1",
        external_thread_id="topic-3", magi_user_id="u1",
    ) if bound else None
    registry = Mock()
    registry.get.return_value = SimpleNamespace(supports_control_requests=True)
    router = SimpleNamespace(fanout_control_request=AsyncMock())
    mapper = SimpleNamespace(lookup_by_session=AsyncMock(return_value=mapping))
    callback = _permission_fanout_callback(
        registry=registry, delivery_router=router, session_mapper=mapper,
    )
    await callback(PermissionRequest(
        request_id="request-1", tool_name="switch_light", arguments={},
        risk_level=RiskLevel.LOW, origin=ToolOrigin.CHAT, agent_id="a1",
        session_id="s1", turn_id="t1", workspace=None,
    ))
    registry.all_channels.assert_not_called()
    if not bound:
        router.fanout_control_request.assert_not_awaited()
        return
    target, = router.fanout_control_request.await_args.kwargs["targets"]
    assert (target.channel_type, target.external_chat_id, target.external_thread_id) == (
        "account-2:telegram", "group-1", "topic-3",
    )
