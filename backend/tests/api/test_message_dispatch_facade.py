from __future__ import annotations

import pytest

from magi.api.services import message_dispatch_service as service
from magi.events.user_message_dispatch import MessageDispatchOutcome


@pytest.mark.asyncio
async def test_dispatch_user_message_preserves_nondefault_envelope_and_outcome(monkeypatch):
    from unittest.mock import AsyncMock
    from magi.core.client_environment import ClientEnvironment

    expected = MessageDispatchOutcome(success=True, user_id="u1", session_id="s1")
    dispatch = AsyncMock(return_value=expected)
    monkeypatch.setattr(service, "require_user_message_dispatcher", lambda: dispatch)
    request = {
        "source": "api",
        "user_id": "u1",
        "message": "hello",
        "session_id": "s1",
        "attachments": [{"attachment_id": "asset-1", "mime_type": "image/png"}],
        "reply_to_message_id": "reply-2",
        "workspace_path": "/workspace/project",
        "client_turn_id": "client-turn-3",
        "metadata": {"request_source": "canary"},
        "runtime_namespace": "desktop",
        "interaction_kind": "chat",
        "first_context": {"question": "What should I call you?"},
        "client_environment": ClientEnvironment(timezone="Asia/Shanghai", os="macos"),
    }
    assert await service.dispatch_user_message(**request) is expected
    dispatch.assert_awaited_once_with(**request)


@pytest.mark.asyncio
async def test_dispatch_user_message_reports_missing_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "require_user_message_dispatcher",
        lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )

    outcome = await service.dispatch_user_message(
        source="api",
        user_id="u1",
        message="hello",
        session_id="s1",
    )

    assert outcome.success is False
    assert outcome.error_code == service.MESSAGE_DISPATCHER_NOT_INITIALIZED
