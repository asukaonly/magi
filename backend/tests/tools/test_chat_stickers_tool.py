"""Sticker management uses the active session and user, never model-supplied identity."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.bootstrap.tool_capabilities import _HostChatPort
from magi.core.tool_capabilities import ToolCapabilities
from magi.tools.builtin.chat_stickers_tool import ChatStickersTool
from magi.tools.schema import ToolExecutionContext


@pytest.mark.asyncio
async def test_save_uses_context_identity_and_reports_the_library_result():
    manage = AsyncMock(return_value={"sticker": {"sticker_id": "st_0123456789abcdef01234567", "name": "开心"}})
    context = ToolExecutionContext(
        agent_id="chat", env_vars={"user_id": "u1", "session_id": "s1"},
        capabilities=ToolCapabilities(chat=SimpleNamespace(manage_stickers=manage)),
    )
    result = await ChatStickersTool().execute(
        {"action": "save", "attachment_id": "a1", "name": "开心", "user_id": "u2", "session_id": "s2"}, context,
    )
    assert result.success
    manage.assert_awaited_once_with(user_id="u1", session_id="s1", action="save", attachment_id="a1",
                                    name="开心", sticker_id=None)
    assert "chat_attachments" not in result.data


@pytest.mark.asyncio
@pytest.mark.parametrize("parameters", [{"action": []}, {"action": "save"}, {"action": "remove"},
                                         {"action": "save", "attachment_id": "a", "name": 4}])
async def test_invalid_management_parameters_do_not_call_host(parameters):
    result = await ChatStickersTool().execute(parameters, ToolExecutionContext(agent_id="chat"))
    assert not result.success


@pytest.mark.asyncio
async def test_host_refuses_an_attachment_outside_the_owned_session(monkeypatch):
    read = AsyncMock(return_value=None)
    monkeypatch.setattr("magi.chat.provider.get_chat_read_service",
                        lambda: SimpleNamespace(aget_attachment_payload=read))
    with pytest.raises(ValueError, match="not available in the current session"):
        await _HostChatPort().manage_stickers(user_id="u1", session_id="s1", action="save",
                                              attachment_id="other-users-image", name="开心")
    read.assert_awaited_once_with("u1", "s1", "other-users-image")
